import copy
import json
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from backend.services.portal_fiche_schemas import FICHE_SCHEMAS
from backend.services import portal_auth_service, sheets_service

logger = logging.getLogger(__name__)


def _resume_erreur(error: BaseException) -> str:
    # Resume d'erreur sans danger pour les logs : classe de l'exception, puis
    # classe et statut HTTP de l'erreur `requests` en cause si disponibles.
    # Jamais str(error) : son texte contient l'URL appelee (webhook n8n, API
    # Notion) et parfois des donnees du client.
    origine = error if isinstance(error, requests.RequestException) else error.__cause__
    details = []

    if isinstance(origine, requests.RequestException):
        if origine is not error:
            details.append(type(origine).__name__)

        statut = getattr(getattr(origine, "response", None), "status_code", None)

        if isinstance(statut, int):
            details.append(str(statut))

    return f"{type(error).__name__} ({' '.join(details)})" if details else type(error).__name__


load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2025-09-03"
NOTION_API_BASE = "https://api.notion.com/v1"

CLIENTS_DATA_SOURCE_ID = os.getenv(
    "NOTION_CLIENTS_DATA_SOURCE_ID", "39ffaffd-8758-8079-ad4d-000bd60487e8"
)
FICHES_CLIENT_DATA_SOURCE_ID = os.getenv(
    "NOTION_FICHES_CLIENT_DATA_SOURCE_ID", "3b1faffd-8758-80d7-8b29-000be5060b26"
)
ENTREES_PORTAIL_DATA_SOURCE_ID = os.getenv(
    "NOTION_ENTREES_PORTAIL_DATA_SOURCE_ID", "ab1f67c7-fa88-4119-8992-dc9da95e917c"
)
LIVRABLES_DATA_SOURCE_ID = os.getenv(
    "NOTION_LIVRABLES_DATA_SOURCE_ID", "39ffaffd-8758-807d-afc1-000bb979786c"
)
KPI_DATA_SOURCE_ID = os.getenv(
    "NOTION_KPI_DATA_SOURCE_ID", "39ffaffd-8758-8010-a085-000bf44d8e0f"
)
CONNEXIONS_DATA_SOURCE_ID = os.getenv(
    "NOTION_CONNEXIONS_DATA_SOURCE_ID", "c6580a4f-a53a-4359-9725-f4ebf3ef6ff2"
)

# Certains noms de propriete Notion contiennent des caracteres invisibles
# (word joiner U+2060) introduits par l'editeur Notion. On compare les noms
# nettoyes plutot que les cles brutes pour ne pas dependre de leur presence exacte.
_ZERO_WIDTH_CHARS = ["⁠", "﻿", "​"]


def _clean_prop_name(name: str) -> str:
    cleaned = name
    for char in _ZERO_WIDTH_CHARS:
        cleaned = cleaned.replace(char, "")
    return cleaned.strip()


def _prop(properties: dict, name: str) -> dict:
    target = _clean_prop_name(name)
    for key, value in properties.items():
        if _clean_prop_name(key) == target:
            return value
    return {}


def _prop_value(prop: dict):
    prop_type = prop.get("type")

    if prop_type == "title":
        return "".join(part.get("plain_text", "") for part in prop.get("title", []))

    if prop_type == "rich_text":
        return "".join(part.get("plain_text", "") for part in prop.get("rich_text", []))

    if prop_type == "email":
        return prop.get("email")

    if prop_type == "select":
        select = prop.get("select")
        return select.get("name") if select else None

    if prop_type == "status":
        status = prop.get("status")
        return status.get("name") if status else None

    if prop_type == "number":
        return prop.get("number")

    if prop_type == "date":
        date_value = prop.get("date")
        return date_value.get("start") if date_value else None

    if prop_type == "url":
        return prop.get("url")

    if prop_type == "checkbox":
        return prop.get("checkbox")

    if prop_type == "relation":
        return [item.get("id") for item in prop.get("relation", [])]

    if prop_type == "formula":
        formula = prop.get("formula", {})
        return formula.get(formula.get("type"))

    if prop_type == "rollup":
        rollup = prop.get("rollup", {})
        rollup_type = rollup.get("type")

        if rollup_type == "array":
            return [_prop_value(item) for item in rollup.get("array", [])]

        return rollup.get(rollup_type)

    return None


def _headers() -> dict:
    if not NOTION_API_KEY:
        raise RuntimeError(
            "NOTION_API_KEY manquant. Renseigne-le dans .env (voir .env.example)."
        )

    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# --- Performance : connexion Notion reutilisee (pas de nouvelle poignee de main
# TLS a chaque appel), reessai automatique sur 429/5xx, petit cache memoire a
# duree de vie courte et appels Notion independants lances en parallele. ---

_retry = Retry(
    total=3,
    backoff_factor=0.4,
    status_forcelist=(429,),
    allowed_methods=None,
    respect_retry_after_header=True,
    raise_on_status=False,
)
_http = requests.Session()
_http.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=_retry))

_POOL = ThreadPoolExecutor(max_workers=8)
_POOL_BLOCS = ThreadPoolExecutor(max_workers=8)

_cache_lock = threading.Lock()
_cache: dict = {}


def _cache_get(key):
    with _cache_lock:
        hit = _cache.get(key)

    if hit and hit[0] > time.monotonic():
        return copy.deepcopy(hit[1])

    return None


def _cache_set(key, value, ttl: float):
    with _cache_lock:
        _cache[key] = (time.monotonic() + ttl, copy.deepcopy(value))

    return value


def _cache_clear(prefix: str | None = None) -> None:
    with _cache_lock:
        for key in [k for k in _cache if prefix is None or str(k).startswith(prefix)]:
            del _cache[key]


_TTL_DASHBOARD = 20  # secondes
_TTL_MASTER = 600    # contenu des fiches master (quasi jamais modifie)


def _query_data_source(data_source_id: str, filter_: dict | None = None) -> list[dict]:
    payload = {"filter": filter_} if filter_ else {}

    try:
        response = _http.post(
            f"{NOTION_API_BASE}/data_sources/{data_source_id}/query",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (query) : {error}") from error

    return response.json().get("results", [])


def _get_page(page_id: str) -> dict:
    try:
        response = _http.get(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (page {page_id}) : {error}") from error

    return response.json()


def _create_page(parent_data_source_id: str, properties: dict) -> dict:
    payload = {
        "parent": {"type": "data_source_id", "data_source_id": parent_data_source_id},
        "properties": properties,
    }

    try:
        response = _http.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (creation page) : {error}") from error

    return response.json()


def _update_page(page_id: str, properties: dict) -> dict:
    try:
        response = _http.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(),
            json={"properties": properties},
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (mise a jour page {page_id}) : {error}") from error

    return response.json()


def _archive_page(page_id: str) -> None:
    try:
        response = _http.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_headers(),
            json={"archived": True},
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (archivage page {page_id}) : {error}") from error


def _rollback_pages(page_ids: list[str]) -> list[str]:
    # Notion n'a pas de vraie transaction multi-pages : en cas d'echec en
    # cours d'onboarding, on annule au mieux en archivant tout ce qui a deja
    # ete cree, plutot que de laisser un client "a moitie onboarde" (fiches
    # orphelines, aucun signal d'erreur). Retourne les IDs qui n'ont pas pu
    # etre archives (a nettoyer a la main dans Notion en dernier recours).
    echecs = []

    for page_id in page_ids:
        try:
            _archive_page(page_id)
        except RuntimeError:
            echecs.append(page_id)

    return echecs


def client_display_name(client_page: dict) -> str:
    return _prop_value(_prop(client_page.get("properties", {}), "Nom"))


def find_client_by_email(email: str) -> dict | None:
    email = (email or "").strip().lower()

    results = _query_data_source(
        CLIENTS_DATA_SOURCE_ID,
        filter_={"property": "E-mail", "email": {"equals": email}},
    )

    return results[0] if results else None


# Renumerotation de "[DB] Fiches Master" (07/10/2026) : les fiches gardent
# leur identifiant interne historique (utilise par le parcours, Sheets, les
# alertes), seul l'affichage suit la nouvelle numerotation. Les fiches client
# deja creees portent encore l'ancien titre : on les reconnait aussi par lui.
_ANCIENS_NOMS = {
    "39ffaffd875880deb56ce1395ae32687": "10. MA CIBLE PRIORITAIRE",
    "39ffaffd875880f980a9f99a718d4141": "11. MA PHRASE DE POSITIONNEMENT",
    "39ffaffd875880d7bf80c72c865a88b2": "12. VALIDATION TERRAIN DE MON POSITIONNEMENT",
    "39ffaffd875880ebbcdde70a29c35269": "13. MON PLAN DE PROSPECTION DE LA SEMAINE",
    "39ffaffd875880f7aee1e8b138416d0a": "14. MON TABLEAU DE PROSPECTION",
    "39ffaffd875880f9a066e6a7e1dc7d37": "15. SCRIPT D'APPROCHE (MODÈLE)",
    "39ffaffd8758808c91dfdd277b66fa2a": "16. GESTION DES OBJECTIONS",
    "39ffaffd875880708581d60c234aab45": "17. BILAN HEBDOMADAIRE : PROSPECTION",
    "39ffaffd87588001b983e13aa1a06cda": "18. TRAME D'ENTRETIEN DE VENTE",
    "39ffaffd875880448c4fe3287b893bf1": "21. MA VISION LONG TERME : eVolution 2.0",
    "3f0faffd875881778743eb169a6915fb": "22. MES RECOMMANDATIONS",
    "3f0faffd87588137927fda435c873a9f": "23. MON BILAN J90"
}
for _mid, _ancien in _ANCIENS_NOMS.items():
    FICHE_SCHEMAS[_mid]["numero_interne"] = re.match(r"^\s*(\d+)", _ancien).group(1)

_NOM_TO_MASTER_ID = {schema["nom"]: master_id for master_id, schema in FICHE_SCHEMAS.items()}
_NOM_TO_MASTER_ID.update({ancien: mid for mid, ancien in _ANCIENS_NOMS.items()})


def _num_interne(schema: dict) -> str | None:
    return schema.get("numero_interne") or _leading_number(schema["nom"])


def _leading_number(text: str) -> str | None:
    match = re.match(r"^\s*(\d+)", text)
    return match.group(1) if match else None


_NUMERO_TO_MASTER_ID = {
    _num_interne(schema): master_id
    for master_id, schema in FICHE_SCHEMAS.items()
    if _num_interne(schema) is not None
}

# Regroupement par module, source : "[DB] Modules" (collection
# 39ffaffd-8758-80b1-ac6b-000bbeb2d780), relation "[DB] Fiches" de chaque
# module vers les fiches master qu'il contient. Fige ici comme les autres
# schemas plutot que requete a chaque affichage : la structure des modules
# ne change pas au fil de l'eau, contrairement aux donnees d'un client.
# Libelles alignes sur la numerotation de la formation systeme.io (Modules 0
# a 7) : le portail n'a plus sa propre numerotation de modules, il renvoie
# aux modules de la formation. L'ordre d'affichage vient de l'ordre du dict.
# Parcours unique valide par Rony le 05/10/2026 (frise J0 -> J90).
# Chaque etape = (libelle affiche, [(numero de fiche, jour d'ouverture)]).
# L'ordre de cette liste EST l'ordre du parcours (il remplace le tri par
# numero de fiche). Une fiche s'ouvre quand son jour est atteint (compte
# depuis "Date de demarrage" du client) ET que la fiche precedente du
# parcours est terminee.
_PARCOURS = [
    ("Démarrage · J0", [(0, 0), (1, 0), (2, 0)]),
    ("Diagnostic · J1 à J3", [(3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1)]),
    ("Clarifier · Module 1 · Mon offre (J4)", [(9, 4), (11, 4), (14, 4)]),
    ("Clarifier · Module 2 · Ma cible (J11)", [(10, 11), (12, 11)]),
    ("Clarifier · Module 3 · Mon pitch (J18)", [(15, 18)]),
    ("Prospecter · Module 4 · Ma routine (J31)", [(13, 31), (17, 31)]),
    ("Convertir · Module 5 · Mes rendez-vous (J61)", [(18, 61)]),
    ("Convertir · Module 6 · Prix et propositions (J68)", [(16, 68), (19, 68)]),
    ("Stabiliser · Module 7 et bilan (J75 à J90)", [(20, 75), (22, 75), (23, 85), (21, 85)]),
]

# Fiches de suivi qui restent ouvertes jusqu'a J90 une fois leur jour
# atteint : elles ne bloquent pas la suite du parcours (14 = tableau de
# prospection, 13 = plan de la semaine, 17 = bilan hebdomadaire, 19 = suivi
# des propositions).
_FICHES_PERMANENTES = {_NUMERO_TO_MASTER_ID[n] for n in ("13", "14", "17", "19")}

_FICHES_PAR_MODULE = {
    libelle: [_NUMERO_TO_MASTER_ID[str(numero)] for numero, _jour in etapes]
    for libelle, etapes in _PARCOURS
}

_FICHE_JOUR = {
    _NUMERO_TO_MASTER_ID[str(numero)]: jour
    for _libelle, etapes in _PARCOURS
    for numero, jour in etapes
}

# Parcours "Atelier Collectif Terrain" (decision du 05/10/2026) : portail en
# version courte, 15 fiches, une etape par session hebdomadaire. Pas de
# Diagnostic de l'onboarding conserve (fiche 8 validee par le coach). Le tableau de prospection (14) reste ouvert.
_PARCOURS_ATELIER = [
    # Demarrage et diagnostic de l'onboarding (fiches 0 a 8), ouverts des
    # l'inscription, donc avant la date de la session 1 (jour negatif).
    ("Avant la session 1 · Démarrage et diagnostic", [(n, -60) for n in range(0, 9)]),
    ("Session 1 · Clarifier ton offre (J0)", [(9, 0), (10, 0), (11, 0)]),
    ("Session 2 · Prospecter (J7)", [(15, 7)]),
    ("Session 3 · Suivre tes prospects (J14)", [(14, 14)]),
    ("Session 4 · Planifier ta semaine (J21)", [(13, 21)]),
]
_ATELIER_MODULE = {
    _NUMERO_TO_MASTER_ID[str(numero)]: libelle
    for libelle, etapes in _PARCOURS_ATELIER
    for numero, _jour in etapes
}
_ATELIER_JOUR = {
    _NUMERO_TO_MASTER_ID[str(numero)]: jour
    for _libelle, etapes in _PARCOURS_ATELIER
    for numero, jour in etapes
}
_ATELIER_POSITION = {master_id: position for position, master_id in enumerate(_ATELIER_JOUR)}
# Livrables masques pour l'atelier (decision du 05/10/2026) : ceux des fiches
# 8 (aides publiques, bonus du coaching) et 14 (plan 30 jours, KPI 90 jours).
_ATELIER_SANS_LIVRABLES = {_NUMERO_TO_MASTER_ID["8"], _NUMERO_TO_MASTER_ID["14"]}
# Texte de bienvenue (fiche 0) propre a l'atelier : page Notion a part, modifiable
# par Rony, lue a la place du master quand le client suit le parcours Atelier.
_ATELIER_FICHE0_TEXTE_PAGE_ID = "3f0faffd8758812882e6d74429466129"
# Texte de secours de la fiche 0 atelier, utilise si la page Notion ci-dessus
# n'est pas lisible par l'integration (page non partagee, Notion indisponible).
_ATELIER_FICHE0_TEXTE = [
    "# 👋 BIENVENUE DANS TON ESPACE ATELIER COLLECTIF TERRAIN",
    "Bonjour et bienvenue dans ton espace de travail personnel pour les 4 semaines de l'atelier.",
    "Cet espace te sert à préparer chaque session et à garder ce que tu produis : tes réponses, ton script, tes prospects, ton plan de la semaine.",
    "### 📖 COMMENT ÇA MARCHE ?",
    "- **Avance pas à pas :** Tu avances fiche par fiche, dans l'ordre proposé.",
    "- **Déblocage progressif :** Chaque fiche validée débloque la suivante, et les fiches de chaque session s'ouvrent le jour de la session.",
    "- **Ton diagnostic d'abord :** Avant la session 1, tu remplis ton diagnostic commercial. Ton coach le valide : c'est ce qui ouvre la suite de ton parcours.",
    "### 🗺️ TON PARCOURS",
    "- **Avant la session 1 :** ton point de départ et ton diagnostic commercial.",
    "- **Session 1 · Clarifier :** ton offre, ta cible, ta phrase de positionnement.",
    "- **Session 2 · Prospecter :** ton script d'approche.",
    "- **Session 3 · Suivre :** ton tableau de prospection. Il reste ouvert ensuite : chaque prospect contacté se reporte tout seul dans ton Tableau de bord.",
    "- **Session 4 · Planifier :** ton plan de la semaine type.",
    "- **En fin d'atelier :** un entretien individuel de 20 minutes avec ton coach.",
    "### ⚡ LE SEUL GESTE À RETENIR",
    "Une fois que tu as lu ou complété une fiche, va tout en bas de la page et clique sur le bouton : 👉 **\"Valider et continuer\"**.",
    "La fiche suivante se débloque alors dans ton parcours.",
]
_ATELIER_PERMANENTES = {_NUMERO_TO_MASTER_ID["14"], _NUMERO_TO_MASTER_ID["13"]}


def _est_parcours_atelier(valeur) -> bool:
    return "atelier" in str(valeur or "").lower()


_FICHE_POSITION = {
    _NUMERO_TO_MASTER_ID[str(numero)]: position
    for position, numero in enumerate(
        numero for _libelle, etapes in _PARCOURS for numero, _jour in etapes
    )
}

# Fiche "Bonus" (diagnostic d'eligibilite aux aides publiques) : hors parcours
# J0-J90, ouverte en permanence et ne bloquant jamais la suite.
_BONUS_MASTER_ID = "3f2faffd87588099b815ed70c549204b"
_FICHES_PAR_MODULE["Bonus · Aides publiques"] = [_BONUS_MASTER_ID]
_FICHES_PERMANENTES.add(_BONUS_MASTER_ID)
_FICHE_POSITION[_BONUS_MASTER_ID] = len(_FICHE_POSITION)

FICHE_MODULES = {
    master_id: {"nom": module_nom, "ordre": ordre}
    for ordre, (module_nom, master_ids) in enumerate(_FICHES_PAR_MODULE.items())
    for master_id in master_ids
}


def _resolve_master_id(props: dict) -> str | None:
    # Methode principale : la relation explicite vers la fiche master.
    master_ids = _prop_value(_prop(props, "[DB] Fiches Master")) or []

    if master_ids:
        return master_ids[0].replace("-", "")

    # Repli : le pipeline n8n de duplication ne renseigne pas cette relation
    # sur les fiches existantes (verifie sur les 60 fiches client en prod : 0
    # avec relation). Les titres dupliques suivent le format "{Client} - {Nom
    # master}", donc on matche sur le titre plutot que de dependre de n8n.
    nom = _prop_value(_prop(props, "Nom")) or ""
    suffixe = nom.split(" - ", 1)[-1]

    if suffixe in _NOM_TO_MASTER_ID:
        return _NOM_TO_MASTER_ID[suffixe]

    for master_nom, master_id in _NOM_TO_MASTER_ID.items():
        if nom.endswith(master_nom):
            return master_id

    # Dernier repli : le titre du master peut contenir un emoji au milieu
    # (ex. "1. \U0001f9ed MON POINT DE DEPART") qui casse la comparaison
    # exacte ci-dessus. Le numero en tete du titre suffit a identifier la
    # fiche sans ambiguite dans cette numerotation (0 a 21, tous uniques).
    numero = _leading_number(suffixe)

    if numero is not None:
        return _NUMERO_TO_MASTER_ID.get(numero)

    return None


def _fiche_summary(fiche_client_id: str) -> dict:
    return _fiche_summary_from_page(_get_page(fiche_client_id))


def _fiche_summary_from_page(page: dict) -> dict:
    fiche_client_id = page["id"]
    props = page.get("properties", {})
    nom = _prop_value(_prop(props, "Nom"))

    master_id = _resolve_master_id(props)

    if master_id is None:
        # FICHE_SCHEMAS/FICHE_MODULES sont des cartographies figees, construites
        # une fois depuis l'etat de Notion a un instant T (voir commentaires
        # plus haut). Si le coach ajoute/renomme une fiche master dans Notion
        # sans mettre a jour ces dicts, _resolve_master_id() ne trouve rien -
        # avant, la fiche tombait silencieusement sans module/schema, sans
        # aucun signal. On log au moins un warning explicite pour que ce ne
        # soit plus invisible (le vrai correctif reste de mettre a jour
        # FICHE_SCHEMAS/portal_fiche_schemas.py).
        logger.warning(
            "Fiche %s ('%s') non reconnue : aucune fiche master ne correspond "
            "dans FICHE_SCHEMAS/_NOM_TO_MASTER_ID. Verifie si une fiche a ete "
            "ajoutee/renommee dans '[DB] Fiches Master' depuis Notion sans "
            "mise a jour de portal_fiche_schemas.py.",
            fiche_client_id, nom,
        )

    schema = FICHE_SCHEMAS.get(master_id) if master_id else None
    module = FICHE_MODULES.get(master_id) if master_id else None

    if schema and nom:
        # Affichage : toujours le nom a jour du master (nouvelle numerotation),
        # meme si la fiche client a ete creee avec l'ancien titre.
        prefixe = nom.rsplit(" - ", 1)[0] + " - " if " - " in nom else ""
        nom = prefixe + schema["nom"]

    if master_id and module is None:
        logger.warning(
            "Fiche %s ('%s') reconnue (master_id=%s) mais absente de "
            "FICHE_MODULES : la structure des modules a probablement change "
            "dans '[DB] Modules' depuis Notion. Met a jour "
            "_FICHES_PAR_MODULE dans notion_service.py.",
            fiche_client_id, nom, master_id,
        )

    return {
        "id": page["id"],
        "master_id": master_id,
        "nom": nom,
        "ordre": _prop_value(_prop(props, "Ordre")),
        "etat": _prop_value(_prop(props, "État")),
        "mode": (schema or {}).get("mode"),
        "module": (module or {}).get("nom"),
    }


def _fiche_sort_key(fiche: dict):
    # Ordre du parcours (_PARCOURS) en priorite : il ne suit plus le numero
    # de fiche (ex. la fiche 11 passe avant la 10, la 15 avant la 13).
    position = _FICHE_POSITION.get(fiche.get("master_id"))

    if position is not None:
        return position

    if fiche.get("ordre") is not None:
        return 100 + fiche["ordre"]

    nom = fiche.get("nom") or ""
    suffixe = nom.split(" - ", 1)[-1]
    match = re.match(r"^\s*(\d+)", suffixe)
    return 100 + int(match.group(1)) if match else 999


# "8. MON RÉSULTAT DE DIAGNOSTIC" se remplit avec le coach en session (scores
# /3 et /15, voir _KPI_FIELD_SYNC plus bas) - jamais seul par le client. Elle
# ne doit donc jamais s'auto-debloquer via la sequence normale : elle reste
# Bloquee tant que le coach ne l'a pas lui-meme passee a En cours/Termine
# directement dans Notion, et son propre etat n'influence pas le
# deverrouillage de la fiche suivante (sinon tout le parcours resterait
# bloque derriere elle).
_FICHES_DEBLOCAGE_COACH = {"39ffaffd87588015a47febbf572e6f62"}


# Les 5 fiches de zone du diagnostic initial (fiches 3 a 7) + la fiche 8
# "resultat". Sert a get_coach_diagnostic_bundle() : la vue lecture seule
# consommee par l'assistant de synthese qui redige la fiche 8. master_id
# sans tirets, memes cles que FICHE_SCHEMAS / _PARCOURS (etape Diagnostic).
_DIAGNOSTIC_ZONES = [
    {"numero": 1, "zone": "Offre", "master_id": "39ffaffd87588001824bdaf6c91b3632"},
    {"numero": 2, "zone": "Visibilité", "master_id": "39ffaffd8758802d93c6e790f165b53e"},
    {"numero": 3, "zone": "Prospection", "master_id": "39ffaffd87588048a076e678e9b24230"},
    {"numero": 4, "zone": "Conversion", "master_id": "39ffaffd875880abae31d7fd1f7a1c99"},
    {"numero": 5, "zone": "Suivi commercial", "master_id": "39ffaffd87588086b588e7a82738c7b1"},
]
_DIAGNOSTIC_FICHE8_MASTER_ID = "39ffaffd87588015a47febbf572e6f62"
_DIAGNOSTIC_ZONE_IDS = {zone["master_id"] for zone in _DIAGNOSTIC_ZONES}


def _jour_parcours(date_demarrage) -> int | None:
    # Nombre de jours ecoules depuis la date de demarrage du client (J0 = le
    # jour meme). None si la date est absente ou illisible : dans ce cas
    # aucun verrou par jour ne s'applique (seul l'enchainement compte).
    if not date_demarrage:
        return None

    try:
        debut = datetime.fromisoformat(str(date_demarrage)[:10]).date()
    except ValueError:
        return None

    return (datetime.now(timezone.utc).date() - debut).days


def _apply_acces(fiches: list[dict], date_demarrage=None, jours=None, permanentes=None) -> None:
    # Calcule le deblocage nous-memes plutot que de lire la formule Notion
    # "acces". Trois regles, dans l'ordre du parcours (_PARCOURS) :
    #  1. jour d'ouverture atteint (frise J0 -> J90) ;
    #  2. fiche precedente terminee ;
    #  3. verrou coach : rien ne s'ouvre apres la fiche 8 tant que le coach
    #     ne l'a pas passee a Termine.
    jour = _jour_parcours(date_demarrage)
    jours = _FICHE_JOUR if jours is None else jours
    permanentes = _FICHES_PERMANENTES if permanentes is None else permanentes
    previous_terminee = True

    for fiche in fiches:
        master_id = fiche.get("master_id")
        etat = fiche.get("etat")
        jour_ouverture = jours.get(master_id, 0)
        trop_tot = jour is not None and jour < jour_ouverture

        if master_id == _BONUS_MASTER_ID:
            # Bonus : ouvert des le debut de la formation, sans condition de
            # jour ni de fiche precedente, et sans jamais bloquer la suite.
            fiche["acces"] = "✅ Terminé" if etat == "Terminé" else "🚀 En cours"
            continue

        if master_id in _FICHES_DEBLOCAGE_COACH:
            fiche["acces"] = "✅ Terminé" if etat == "Terminé" else (
                "🚀 En cours" if etat == "En cours" else "🔒 Bloqué"
            )
            previous_terminee = etat == "Terminé"
            continue

        if etat == "Terminé":
            fiche["acces"] = "✅ Terminé"
        elif trop_tot and previous_terminee:
            fiche["acces"] = f"🔒 Bloqué · ouvre à J{jour_ouverture}"
        elif previous_terminee:
            fiche["acces"] = "🚀 En cours"
        else:
            fiche["acces"] = "🔒 Bloqué"

        if master_id in permanentes:
            # Fiche de suivi : elle ne bloque pas la suite, sauf si elle
            # n'est pas encore ouverte elle-meme.
            previous_terminee = previous_terminee and not trop_tot
            continue

        previous_terminee = etat == "Terminé"


def _client_identite(props: dict) -> dict:
    return {
        "nom": _prop_value(_prop(props, "Nom")),
        "email": _prop_value(_prop(props, "E-mail")),
        "telephone": _prop_value(_prop(props, "Téléphone")),
        "contact": _prop_value(_prop(props, "Contact")),
        "activite": _prop_value(_prop(props, "Activité")),
        "secteur": _prop_value(_prop(props, "Secteur")),
        "territoire": _prop_value(_prop(props, "Territoire")),
        "offre_principale": _prop_value(_prop(props, "Offre Principale")),
        "site_reseaux": _prop_value(_prop(props, "Site / Réseaux")),
    }


def _client_cohorte(props: dict) -> dict | None:
    cohorte_ids = _prop_value(_prop(props, "Cohorte")) or []

    if not cohorte_ids:
        return None

    page = _get_page(cohorte_ids[0])
    cohorte_props = page.get("properties", {})

    return {
        "nom": _prop_value(_prop(cohorte_props, "Nom")),
        "statut": _prop_value(_prop(cohorte_props, "Statut")),
        "date_debut": _prop_value(_prop(cohorte_props, "Date début")),
        "date_fin": _prop_value(_prop(cohorte_props, "Date fin")),
    }


def _client_sessions(props: dict) -> list[dict]:
    session_ids = _prop_value(_prop(props, "Sessions")) or []
    sessions = []

    for session_id in session_ids:
        session_props = _get_page(session_id).get("properties", {})
        sessions.append({
            "id": session_id,
            "nom": _prop_value(_prop(session_props, "Nom")),
            "date_heure": _prop_value(_prop(session_props, "Date & heure")),
            "statut": _prop_value(_prop(session_props, "Statut")),
            "prochaine_echeance": _prop_value(_prop(session_props, "Prochaine échéance")),
        })

    sessions.sort(key=lambda session: session.get("date_heure") or "")
    return sessions


def _client_kpi(client_page_id: str) -> list[dict]:
    rows = _query_data_source(
        KPI_DATA_SOURCE_ID,
        filter_={"property": "Client", "relation": {"contains": client_page_id}},
    )

    kpis = []

    for row in rows:
        props = row.get("properties", {})
        kpis.append({
            "id": row["id"],
            "nom": _prop_value(_prop(props, "Nom")),
            "categorie": _prop_value(_prop(props, "Catégorie")),
            "phase": _prop_value(_prop(props, "Phase")),
            "etat": _prop_value(_prop(props, "État")),
            "valeur_j0": _prop_value(_prop(props, "Valeur J0")),
            "valeur_j30": _prop_value(_prop(props, "Valeur J30")),
            "valeur_j60": _prop_value(_prop(props, "Valeur J60")),
            "valeur_j90": _prop_value(_prop(props, "Valeur J90")),
            "objectif_j30": _prop_value(_prop(props, "Objectif J30")),
            "objectif_j60": _prop_value(_prop(props, "Objectif J60")),
            "objectif_j90": _prop_value(_prop(props, "Objectif J90")),
        })

    kpis.sort(key=lambda kpi: kpi.get("nom") or "")
    return kpis


def _livrables_for_fiche(fiche_client_id: str, master_id: str) -> list[dict]:
    # "[DB] Livrables" relie chaque livrable a une fiche via deux relations
    # possibles : "Fiche Master (référence)" pour les 13 modeles generiques
    # actuels (memes documents pour tous les clients - verifie en direct,
    # aucun n'a encore "Fiche Client" renseigne), et "Fiche Client" pour un
    # livrable propre a un client une fois cette liaison faite. On affiche
    # l'union des deux, pour que ca marche des aujourd'hui avec les modeles
    # generiques et plus tard sans changement quand des livrables
    # client-specifiques existeront.
    rows = _query_data_source(
        LIVRABLES_DATA_SOURCE_ID,
        filter_={
            "or": [
                {"property": "Fiche Master (référence)", "relation": {"contains": _add_dashes(master_id)}},
                {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
            ]
        },
    )

    livrables = []

    for row in rows:
        props = row.get("properties", {})
        livrables.append({
            "id": row["id"],
            "nom": _prop_value(_prop(props, "Nom")),
            "etat": _prop_value(_prop(props, "État")),
            "validation_coach": _prop_value(_prop(props, "Validation coach")),
            "obligatoire": _prop_value(_prop(props, "Obligatoire")),
            "commentaire_coach": _prop_value(_prop(props, "Commentaire coach")),
            "date_depot": _prop_value(_prop(props, "Date de dépôt")),
            "date_validation": _prop_value(_prop(props, "Date de validation")),
        })

    livrables.sort(key=lambda l: l.get("nom") or "")
    return livrables


class LivrableNonAutorise(LookupError):
    # Levee uniquement quand le livrable a ete lu avec succes mais n'est pas
    # rattache a une fiche ouverte du client. Sous-classe dediee : une KeyError
    # (autre LookupError) venant d'un vrai bug ne doit jamais devenir un 404.
    pass


def _livrable_autorise(props: dict, dashboard: dict) -> bool:
    # Un livrable n'est lisible que s'il depend d'une fiche OUVERTE du client :
    # soit lie directement a sa fiche client, soit au master de cette fiche
    # (livrables generiques). Meme exclusion Atelier que get_fiche().
    atelier = _est_parcours_atelier(dashboard.get("parcours"))
    ouvertes = [
        f for f in dashboard.get("fiches", [])
        if "Bloqué" not in (f.get("acces") or "")
        and not (atelier and f.get("master_id") in _ATELIER_SANS_LIVRABLES)
    ]
    ids_client = {
        (i or "").replace("-", "") for i in (_prop_value(_prop(props, "Fiche Client")) or [])
    }
    ids_master = {
        (i or "").replace("-", "") for i in (_prop_value(_prop(props, "Fiche Master (référence)")) or [])
    }
    ids_client.discard("")
    ids_master.discard("")

    for fiche in ouvertes:
        fiche_id = (fiche.get("id") or "").replace("-", "")
        master_id = (fiche.get("master_id") or "").replace("-", "")

        if (fiche_id and fiche_id in ids_client) or (master_id and master_id in ids_master):
            return True

    return False


def get_livrable(livrable_id: str, dashboard: dict) -> dict:
    # Contenu affiche tel quel dans le portail (sous-page de la fiche) via
    # le meme rendu que les fiches "Suivi recurrent" (_get_page_content).
    # Limite connue : les blocs "table" Notion ne remontent pas (le
    # comptage cellule par cellule n'est pas gere ici), seuls titres,
    # paragraphes, listes, callouts et to_do le sont.
    # LivrableNonAutorise (un LookupError) uniquement quand la page a ete lue
    # mais n'est pas autorisee pour ce client : les erreurs Notion restent des
    # RuntimeError (503).
    page = _get_page(livrable_id)
    props = page.get("properties", {})

    if not _livrable_autorise(props, dashboard):
        raise LivrableNonAutorise("Livrable introuvable.")

    return {
        "id": page["id"],
        "nom": _prop_value(_prop(props, "Nom")),
        "contenu": _get_page_content(livrable_id),
    }


def _repair_missing_fiches(client_page_id: str, nom_client: str, fiches: list[dict], autorisees=None) -> list[dict]:
    # Le pipeline n8n de duplication a deja laisse des clients avec des
    # fiches manquantes (verifie en direct : Tarzan n'en avait que 16/22 -
    # aucun signal d'erreur nulle part, juste des fiches absentes sans
    # explication). Plutot qu'un correctif ponctuel a refaire a la main
    # client par client, on complete automatiquement ici : n'importe quel
    # chargement du tableau de bord auto-repare un client incomplet, avec la
    # meme logique de creation qu'onboard_client(). Idempotent par
    # construction (compare aux master_id deja presents avant de creer).
    existing_master_ids = {f["master_id"] for f in fiches if f.get("master_id")}
    nouvelles = []

    for master_id, schema in _fiche_master_items_sorted():
        if master_id in existing_master_ids:
            continue

        if autorisees is not None and master_id not in autorisees:
            continue

        ordre = int(_leading_number(schema["nom"]) or 0)
        fiche_properties = {
            "Nom": {"title": [{"text": {"content": f"{nom_client} - {schema['nom']}"}}]},
            "⁠[DB] Clients⁠": {"relation": [{"id": client_page_id}]},
            "⁠[DB] Fiches Master": {"relation": [{"id": _add_dashes(master_id)}]},
            "Ordre": {"number": ordre},
            "État": {"status": {"name": "Pas commencé"}},
            "✅ Valider cette fiche": {"checkbox": False},
        }

        page = _create_page(FICHES_CLIENT_DATA_SOURCE_ID, fiche_properties)
        nouvelles.append(_fiche_summary(page["id"]))

    if nouvelles:
        logger.warning(
            "Client %s ('%s') avait %d fiche(s) manquante(s) sur 22 - "
            "recreees automatiquement : %s",
            client_page_id, nom_client, len(nouvelles),
            [f["nom"] for f in nouvelles],
        )

    return fiches + nouvelles


def get_client_dashboard(client_page_id: str) -> dict:
    # Calcul lourd (une vingtaine d'appels Notion) : memorise ~20 s, et vide a
    # chaque enregistrement/validation pour que le client voie toujours son
    # etat a jour juste apres une action.
    cle = f"dashboard:{client_page_id}"
    en_cache = _cache_get(cle)

    if en_cache is not None:
        return en_cache

    return _cache_set(cle, _build_client_dashboard(client_page_id), _TTL_DASHBOARD)


def _fiches_du_client(client_page_id: str, fiche_ids: list[str]) -> list[dict]:
    # UNE requete (filtre sur la relation) au lieu d'un GET par fiche. Toute
    # fiche annoncee par le client mais absente du resultat est relue
    # individuellement : comportement identique a l'ancien, en bien plus rapide.
    voulues = [fid.replace("-", "") for fid in fiche_ids]
    pages: dict[str, dict] = {}

    try:
        for page in _query_data_source(
            FICHES_CLIENT_DATA_SOURCE_ID,
            filter_={"property": "\u2060[DB] Clients\u2060", "relation": {"contains": client_page_id}},
        ):
            pages[page["id"].replace("-", "")] = page
    except Exception as error:
        logger.warning("Requete groupee des fiches impossible (%s), lecture une par une.", error)

    manquantes = [fid for fid in voulues if fid not in pages]

    if manquantes:
        for fid, page in zip(manquantes, _POOL.map(_get_page, manquantes)):
            pages[fid] = page

    return [_fiche_summary_from_page(pages[fid]) for fid in voulues]


def _build_client_dashboard(client_page_id: str) -> dict:
    page = _get_page(client_page_id)
    props = page.get("properties", {})
    nom_client = _prop_value(_prop(props, "Nom"))

    # Appels independants lances ensemble : fiches, KPI, classeur Google.
    kpi_future = _POOL.submit(_client_kpi, client_page_id)
    sheets_future = None

    if sheets_service.enabled():
        sheets_future = _POOL.submit(
            sheets_service.sheet_url,
            client_page_id,
            nom_client,
            _prop_value(_prop(props, "E-mail")) or "",
            _est_parcours_atelier(_prop_value(_prop(props, "Parcours"))),
        )

    fiche_ids = _prop_value(_prop(props, "[DB] Fiches Client")) or []
    fiches = _fiches_du_client(client_page_id, fiche_ids)

    date_demarrage = _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage"))

    if _est_parcours_atelier(_prop_value(_prop(props, "Parcours"))):
        # Atelier : seules les fiches du parcours court sont visibles.
        fiches = [f for f in fiches if f.get("master_id") in _ATELIER_JOUR]

        if len(fiches) < len(_ATELIER_JOUR):
            fiches = _repair_missing_fiches(client_page_id, nom_client, fiches, autorisees=set(_ATELIER_JOUR))
            fiches = [f for f in fiches if f.get("master_id") in _ATELIER_JOUR]

        for fiche in fiches:
            fiche["module"] = _ATELIER_MODULE.get(fiche.get("master_id"))

        fiches.sort(key=lambda f: _ATELIER_POSITION.get(f.get("master_id"), 999))
        _apply_acces(fiches, date_demarrage, jours=_ATELIER_JOUR, permanentes=_ATELIER_PERMANENTES)
    else:
        if len(fiches) < len(FICHE_SCHEMAS):
            fiches = _repair_missing_fiches(client_page_id, nom_client, fiches)

        fiches.sort(key=_fiche_sort_key)
        _apply_acces(fiches, date_demarrage)

    return {
        "nom": nom_client,
        "objectif_90j": _prop_value(_prop(props, "Objectif 90j")),
        "date_demarrage": _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage")),
        "date_bilan_90j": _prop_value(_prop(props, "Date bilan 90 jours")),
        "phase_parcours": _prop_value(_prop(props, "Phase parcours")),
        "sheets_url": _resultat_sheets(sheets_future),
        "parcours": _prop_value(_prop(props, "Parcours")),
        "progression_kpi_j90": _prop_value(_prop(props, "Progression KPI J90")),
        "progression_livrables": _prop_value(_prop(props, "Progression livrables")),
        "identite": _client_identite(props),
        "cohorte": _client_cohorte(props),
        "sessions": _client_sessions(props),
        "fiches": fiches,
        "kpi": kpi_future.result(),
    }


def _resultat_sheets(future) -> str | None:
    # Le classeur Google ne doit jamais retarder le portail : on attend 2,5 s
    # au plus (il continue en arriere-plan et sera pret au prochain chargement).
    if future is None:
        return None

    try:
        return future.result(timeout=2.5)
    except Exception:
        return None


def _fiche_schema_for(fiche_client_id: str) -> tuple[dict, str, str]:
    page = _get_page(fiche_client_id)
    props = page.get("properties", {})

    master_id = _resolve_master_id(props)

    if not master_id:
        raise RuntimeError(f"Fiche {fiche_client_id} : impossible de trouver sa fiche master associee.")

    schema = FICHE_SCHEMAS.get(master_id)

    if not schema:
        raise RuntimeError(f"Aucun schema de champs defini pour la fiche master {master_id}.")

    return schema, _prop_value(_prop(props, "Nom")), master_id


_BLOCK_TYPE_PREFIX = {
    "heading_1": "# ",
    "heading_2": "## ",
    "heading_3": "### ",
    "bulleted_list_item": "- ",
    "numbered_list_item": "- ",
    "callout": "> ",
    "quote": "> ",
    "to_do": "- ",
}

# Note interne laissee par le pipeline n8n a la place des blocs "button"
# (non manipulables via l'API Notion) - jamais destinee au client.
_WARNING_MARKER = "non copiable automatiquement"


def _block_text(block: dict) -> str:
    block_type = block.get("type")
    rich_text = block.get(block_type, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rich_text)


def _is_internal_warning(block: dict) -> bool:
    if block.get("type") != "callout":
        return False

    return _WARNING_MARKER in _block_text(block).lower()


def _list_children(block_id: str) -> list[dict]:
    # Pagine : l'API Notion plafonne a 100 blocs par appel, et une fiche plus
    # longue perdait sinon tout ce qui suivait.
    results: list[dict] = []
    cursor = None

    for _ in range(20):
        params = {"page_size": 100}

        if cursor:
            params["start_cursor"] = cursor

        try:
            response = _http.get(
                f"{NOTION_API_BASE}/blocks/{block_id}/children",
                headers=_headers(),
                params=params,
                timeout=15,
            )
            response.raise_for_status()

        except requests.RequestException as error:
            raise RuntimeError(f"Erreur Notion (blocs {block_id}) : {error}") from error

        data = response.json()
        results.extend(data.get("results", []))

        if not data.get("has_more") or not data.get("next_cursor"):
            break

        cursor = data["next_cursor"]

    return results


# Marqueur de ligne pour un tableau Notion complet (bloc "table" + ses
# "table_row" enfants). Un bloc "table" devient UNE seule ligne (JSON
# compact), pas plusieurs - _blocks_to_text() joint les blocs avec "\n" et
# le frontend re-splitte sur "\n", donc un tableau multi-lignes serait
# fragmente si on ne l'encodait pas en une seule ligne. Le frontend
# reconnait ce prefixe et rend un vrai <table> (voir renderTextLine dans
# App.jsx) plutot que du texte brut.
_TABLE_LINE_PREFIX = "##TABLE## "


def _table_row_cells(block: dict) -> list[str]:
    cells = block.get("table_row", {}).get("cells", [])
    return [_rich_text_md(cell) for cell in cells]


def _table_to_line(block: dict) -> str | None:
    row_blocks = _list_children(block["id"])
    rows = [_table_row_cells(row) for row in row_blocks if row.get("type") == "table_row"]

    if not rows:
        return None

    payload = {
        "hasHeader": bool(block.get("table", {}).get("has_column_header")),
        "rows": rows,
    }

    return _TABLE_LINE_PREFIX + json.dumps(payload, ensure_ascii=False)


_NOTION_HOSTS = ("notion.so", "notion.site", "notion.com", "notion.new")


def _lien_externe(href: str | None) -> str | None:
    # Un lien Notion interne (page, mention, ancre) ne mene a rien pour le
    # client : seuls les liens http(s)/mailto/tel vers l'exterieur sont gardes.
    if not href:
        return None

    href = href.strip()

    if not href.lower().startswith(("http://", "https://", "mailto:", "tel:")):
        return None

    if href.lower().startswith("http"):
        hote = href.split("/")[2].lower() if href.count("/") >= 2 else ""

        if any(hote == h or hote.endswith("." + h) for h in _NOTION_HOSTS):
            return None

    return href


def _rich_text_md(rich_text: list[dict]) -> str:
    out = []

    for part in rich_text:
        texte = part.get("plain_text", "")
        lien = _lien_externe(part.get("href"))

        if texte and lien:
            texte = f"[{texte.strip()}]({lien})"

        out.append(texte)

    return "".join(out)


def _block_text_md(block: dict) -> str:
    block_type = block.get("type")
    return _rich_text_md(block.get(block_type, {}).get("rich_text", []))


def _file_block_url(data: dict) -> str | None:
    kind = data.get("type")
    return (data.get(kind) or {}).get("url") if kind else None


def _block_lines(block: dict, depth: int = 0, checks: bool = False) -> list[str]:
    # Un bloc -> ses lignes de texte (avec ses enfants : listes imbriquees,
    # blocs repliables, colonnes...). Avant, les enfants etaient ignores :
    # le contenu d'un bloc repliable (exemples, astuces, "a eviter") ne
    # remontait pas et seul son titre restait, sans rien derriere.
    block_type = block.get("type")

    if block_type == "divider" or _is_internal_warning(block):
        return []

    if block_type == "table":
        line = _table_to_line(block)
        return [line] if line else []

    if checks and block_type == "to_do":
        # Case a cocher reelle (etat memorise par client) : "##CHECK## cle|texte"
        texte = _block_text(block).strip("* ")
        return [f"{_CHECK_LINE_PREFIX}{block['id'].replace('-', '')}|{texte}"] if texte else []

    lines: list[str] = []
    data = block.get(block_type, {}) or {}

    if block_type in ("bookmark", "embed", "link_preview"):
        url = _lien_externe(data.get("url"))
        legende = _rich_text_md(data.get("caption", [])).strip()

        if url:
            lines.append(f"[{legende or url}]({url})")

    elif block_type in ("file", "pdf", "video", "audio"):
        url = _file_block_url(data)
        legende = _rich_text_md(data.get("caption", [])).strip()

        if url:
            lines.append(f"[{legende or 'Ouvrir le fichier'}]({url})")

    elif block_type == "image":
        url = _file_block_url(data)

        if url:
            legende = _rich_text_md(data.get("caption", [])).strip() or "Voir l'image"
            lines.append(f"[{legende}]({url})")

    elif block_type == "child_page":
        titre = (data.get("title") or "").strip()

        if titre:
            lines.append(titre)

    else:
        text = _block_text_md(block)

        if text:
            prefix = _BLOCK_TYPE_PREFIX.get(block_type, "")

            if block_type == "toggle":
                prefix = "### "

            lines.append(prefix + text)

    if block.get("has_children") and depth < 3 and block_type not in ("child_page", "child_database", "table"):
        for child in _list_children(block["id"]):
            lines.extend(_block_lines(child, depth + 1, checks))

    return lines


_CHECK_LINE_PREFIX = "##CHECK## "


def _blocks_to_text(blocks: list[dict], checks: bool = False) -> str:
    lines = []

    for block in blocks:
        lines.extend(_block_lines(block, 0, checks))

    return "\n".join(lines)


def _get_page_content(page_id: str, checks: bool = False) -> str:
    return _blocks_to_text(_list_children(page_id), checks)


def _page_segments(page_id: str) -> list[dict]:
    # Rendu "fidele" d'une fiche Q&A : chaque question Notion (puce en gras
    # suivie d'une sous-puce "Ecrivez ici...") devient un champ affiche en
    # ligne juste apres son enonce, plutot qu'une zone de reponses separee.
    # Les cases a cocher Notion (to_do) restent des cases a cocher.
    segments = []
    blocs = _list_children(page_id)

    # Sous-blocs de toutes les questions lus en parallele (au lieu d'un appel
    # Notion par question, l'un apres l'autre).
    enfants = {
        bloc["id"]: _POOL_BLOCS.submit(_list_children, bloc["id"])
        for bloc in blocs
        if bloc.get("type") in ("bulleted_list_item", "numbered_list_item") and bloc.get("has_children")
    }

    for block in blocs:
        block_type = block.get("type")

        if block_type == "divider" or _is_internal_warning(block):
            continue

        if block_type == "to_do":
            segments.append({
                "type": "champ",
                "champ": {
                    "cle": block["id"].replace("-", ""),
                    "libelle": _block_text(block).strip("* "),
                    "type": "case",
                },
            })
            continue

        if block_type in ("bulleted_list_item", "numbered_list_item") and block.get("has_children"):
            children = enfants[block["id"]].result()

            # Motif "Oui | Plutot | Non" : une sous-case a cocher (to_do)
            # unique servant de texte d'options, plutot qu'une vraie case.
            # On la convertit en champ a choix, ce qui evite au client de se
            # retrouver avec une question sans aucun moyen d'y repondre.
            todo_children = [child for child in children if child.get("type") == "to_do"]

            if todo_children:
                options = [
                    option.strip()
                    for option in _block_text(todo_children[0]).split("|")
                    if option.strip()
                ]
                segments.append({
                    "type": "champ",
                    "champ": {
                        "cle": block["id"].replace("-", ""),
                        "libelle": _block_text(block).strip("* "),
                        "type": "choix",
                        "options": options,
                    },
                })
                continue

            has_placeholder = any(
                child.get("type") in ("bulleted_list_item", "numbered_list_item", "paragraph")
                for child in children
            )

            if has_placeholder:
                segments.append({
                    "type": "champ",
                    "champ": {
                        "cle": block["id"].replace("-", ""),
                        "libelle": _block_text(block).strip("* "),
                        "type": "texte",
                    },
                })
                continue

        for ligne in _block_lines(block):
            segments.append({"type": "texte", "texte": ligne})

    return segments


def _donnees_vers_libelles(data: dict, champs: list[dict]) -> dict:
    # On stocke les reponses par libelle de question (et non par identifiant
    # interne) dans "[DB] Entrees Portail" pour que le coach puisse les lire
    # directement dans Notion sans repasser par le portail.
    cle_vers_libelle = {champ["cle"]: champ["libelle"] for champ in champs}
    return {cle_vers_libelle.get(cle, cle): valeur for cle, valeur in data.items()}


def _donnees_vers_cles(donnees: dict, champs: list[dict]) -> dict:
    libelle_vers_cle = {champ["libelle"]: champ["cle"] for champ in champs}
    return {libelle_vers_cle.get(libelle, libelle): valeur for libelle, valeur in donnees.items()}


def _parse_entry(page: dict, champs: list[dict]) -> dict:
    props = page.get("properties", {})
    donnees_raw = _prop_value(_prop(props, "Donnees (JSON)")) or _prop_value(_prop(props, "Données (JSON)")) or "{}"

    try:
        donnees = json.loads(donnees_raw)
    except json.JSONDecodeError:
        donnees = {}

    return {
        "id": page["id"],
        "date": _prop_value(_prop(props, "Date")),
        "donnees": _donnees_vers_cles(donnees, champs),
    }


def _champs_for(schema: dict, master_id: str, segments: list[dict] | None = None) -> list[dict]:
    if schema["mode"] == "unique":
        if segments is None:
            # Cache : sinon chaque enregistrement relisait toutes les questions
            # de la fiche master dans Notion (un appel par question).
            segments = _segments_master_cache(master_id)

        return [segment["champ"] for segment in segments if segment["type"] == "champ"]

    return schema["champs"]


def _prefill_from_client(master_id: str, client_page_id: str, champs: list[dict]) -> dict:
    client_props = None
    prefill = {}

    for champ in champs:
        client_prop = _CLIENT_FIELD_SYNC.get((master_id, champ["libelle"]))

        if not client_prop:
            continue

        if client_props is None:
            client_props = _get_page(client_page_id).get("properties", {})

        valeur = _prop_value(_prop(client_props, client_prop))

        if valeur not in (None, ""):
            prefill[champ["cle"]] = valeur

    return prefill


# Pre-remplissage entre fiches : (master source, debut du libelle source,
# master destination, debut du libelle destination). Les libelles sont compares
# en minuscules sur leur debut : robuste a de petites retouches dans Notion.
_PREFILL_ENTRE_FICHES = [
    ("9", "quel est le problème urgent", "10", "quelle est sa plus grande frustration"),
    ("11", "ma phrase officielle", "15", "mon script personnalisé"),
    ("11", "ma phrase officielle", "16", "objection \"c'est trop cher\""),
]


def _prefill_entre_fiches(master_id: str, client_page_id: str, champs: list[dict]) -> dict:
    regles = [
        (_NUMERO_TO_MASTER_ID.get(src), lsrc, dlib)
        for src, lsrc, dst, dlib in _PREFILL_ENTRE_FICHES
        if _NUMERO_TO_MASTER_ID.get(dst) == master_id
    ]

    if not regles:
        return {}

    try:
        fiches = get_client_dashboard(client_page_id).get("fiches", [])
    except Exception:
        return {}

    client_fiche_par_master = {f.get("master_id"): f.get("id") for f in fiches}
    prefill = {}
    sources: dict = {}

    for src_master, lsrc, dlib in regles:
        champ_dst = next(
            (c for c in champs if c["libelle"].strip().lower().startswith(dlib)), None
        )
        fiche_src = client_fiche_par_master.get(src_master)

        if not champ_dst or not fiche_src or champ_dst["cle"] in prefill:
            continue

        try:
            if src_master not in sources:
                src_champs = _champs_for(FICHE_SCHEMAS[src_master], src_master)
                pages = _query_data_source(
                    ENTREES_PORTAIL_DATA_SOURCE_ID,
                    {
                        "and": [
                            {"property": "Fiche Client", "relation": {"contains": fiche_src}},
                            {"property": "Client", "relation": {"contains": client_page_id}},
                        ]
                    },
                )
                entrees = [_parse_entry(p, src_champs) for p in pages]
                entrees.sort(key=lambda e: e.get("date") or "")
                sources[src_master] = (src_champs, entrees)

            src_champs, entrees = sources[src_master]
            champ_src = next(
                (c for c in src_champs if c["libelle"].strip().lower().startswith(lsrc)), None
            )

            if champ_src and entrees:
                valeur = entrees[-1]["donnees"].get(champ_src["cle"])

                if valeur not in (None, ""):
                    prefill[champ_dst["cle"]] = valeur
        except Exception as error:
            logger.warning("Pre-remplissage entre fiches impossible (%s)", error)

    return prefill


def _segments_master_cache(page_id: str) -> list[dict]:
    # Les fiches master ne changent quasi jamais : on evite de re-lire tous
    # leurs blocs Notion (plusieurs appels) a chaque ouverture de fiche.
    cle = f"segments:{page_id}"
    en_cache = _cache_get(cle)

    if en_cache is not None:
        return en_cache

    return _cache_set(cle, _page_segments(page_id), _TTL_MASTER)


def _contenu_master_cache(page_id: str) -> str:
    cle = f"contenu:{page_id}"
    en_cache = _cache_get(cle)

    if en_cache is not None:
        return en_cache

    return _cache_set(cle, _get_page_content(page_id, checks=True), _TTL_MASTER)


def get_fiche(fiche_client_id: str, client_page_id: str) -> dict:
    schema, nom, master_id = _fiche_schema_for(fiche_client_id)
    mode = schema["mode"]

    # Requetes independantes lancees des le depart, en parallele du contenu.
    entries_future = _POOL.submit(
        _query_data_source,
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        {
            "and": [
                {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
                {"property": "Client", "relation": {"contains": client_page_id}},
            ]
        },
    )
    livrables_future = _POOL.submit(_livrables_for_fiche, fiche_client_id, master_id)

    segments = None

    if mode == "unique":
        if master_id in _FICHES_DEBLOCAGE_COACH:
            # Exception au repli "master fait foi" ci-dessous : ces fiches
            # (ex. "8. MON RESULTAT DE DIAGNOSTIC") ne sont justement PAS
            # des Q&A generiques remplies via le portail - le coach ecrit
            # directement les resultats personnalises (scores, priorites)
            # dans le contenu de la page CLIENT elle-meme. Verifie en direct
            # : le contenu de Tarzan differait bien du master (scores et
            # priorites reellement remplis), mais restait invisible dans le
            # portail tant qu'on lisait le master. Ces fiches n'ont pas de
            # champs to_do/sous-puce a proteger du bug de flattening n8n
            # decrit ci-dessous, donc rien ne justifie le repli sur master.
            segments = _page_segments(fiche_client_id)
        else:
            # Toujours lu depuis la fiche MASTER plutot que la copie client :
            # le pipeline n8n de duplication (Sub_InjectBlocksTree) peut
            # aplatir l'arborescence de blocs de la copie (perte de
            # l'imbrication bulleted_list_item -> to_do/paragraph), ce qui
            # rend des questions invisibles comme champs sans que
            # _page_segments() renvoie pour autant une liste vide. Le
            # contenu de ces fiches client n'est de toute facon jamais
            # modifie individuellement : le master fait foi.
            source_id = master_id

            if master_id == _NUMERO_TO_MASTER_ID["0"]:
                try:
                    client_props = _get_page(client_page_id).get("properties", {})

                    if _est_parcours_atelier(_prop_value(_prop(client_props, "Parcours"))):
                        source_id = _ATELIER_FICHE0_TEXTE_PAGE_ID
                except Exception:
                    source_id = master_id

            try:
                segments = _segments_master_cache(source_id)
            except Exception:
                if source_id == master_id:
                    raise
                segments = [{"type": "texte", "texte": ligne} for ligne in _ATELIER_FICHE0_TEXTE]

    champs = _champs_for(schema, master_id, segments)

    entries_raw = entries_future.result()
    entries = [_parse_entry(page, champs) for page in entries_raw]
    entries.sort(key=lambda entry: entry.get("date") or "")

    # L'etat des cases a cocher est memorise dans une entree speciale : elle
    # n'est jamais une ligne du tableau.
    checks_etat: dict = {}

    for entry in list(entries):
        if isinstance(entry.get("donnees"), dict) and _CHECKLIST_KEY in entry["donnees"]:
            checks_etat = entry["donnees"][_CHECKLIST_KEY] or {}
            entries.remove(entry)

    if mode == "unique" and not entries:
        # Pre-remplissage : si le client n'a encore jamais repondu a cette
        # fiche, on propose comme valeur de depart ce qui a deja ete capture
        # cote coach/onboarding dans "[DB] Clients" (via _CLIENT_FIELD_SYNC),
        # plutot que de faire retaper au client une info deja connue. Reste
        # editable normalement au moment de l'enregistrement.
        prefill = _prefill_from_client(master_id, client_page_id, champs)

        for cle, valeur in _prefill_entre_fiches(master_id, client_page_id, champs).items():
            prefill.setdefault(cle, valeur)

        if prefill:
            entries = [{"id": None, "date": None, "donnees": prefill}]

    livrables = livrables_future.result()

    if livrables and master_id in _ATELIER_SANS_LIVRABLES:
        try:
            client_props = _get_page(client_page_id).get("properties", {})

            if _est_parcours_atelier(_prop_value(_prop(client_props, "Parcours"))):
                livrables = []
        except Exception:
            # Dans le doute, on ne montre pas un livrable reserve au coaching.
            livrables = []

    result = {
        "fiche_client_id": fiche_client_id,
        "nom": nom,
        "mode": mode,
        "champs": champs,
        "entrees": entries,
        "livrables": livrables,
        "checks": checks_etat,
    }

    if mode == "unique":
        result["segments"] = segments
    else:
        result["contenu"] = _contenu_master_cache(master_id)

    return result


# Premier cas concret de "reponse de fiche connectee ailleurs" : la question
# objectif 90j de la fiche 1 alimente directement la propriete "Objectif 90j"
# de [DB] Clients (deja affichee sur le tableau de bord). D'autres couples
# (fiche master, libelle) -> propriete client pourront s'ajouter ici au fur
# et a mesure que l'utilisateur precise les correspondances KPI souhaitees.
_CLIENT_FIELD_SYNC = {
    (
        "39ffaffd8758809e9807c4c5e5504352",
        "Quel est votre objectif chiffré ou personnel pour les 90 prochains jours ?",
    ): "Objectif 90j",
    (
        "39ffaffd8758809e9807c4c5e5504352",
        "Quel est ton objectif chiffré ou personnel pour les 90 prochains jours ?",
    ): "Objectif 90j",
    (
        "39ffaffd8758809e9807c4c5e5504352",
        "Votre activité / Votre métier :",
    ): "Activité",
    # Variantes au tutoiement : les fiches master passent au "tu" (harmonisation
    # avec la formation). Les deux formulations restent acceptees pour que la
    # synchro ne casse pas pendant la transition.
    (
        "39ffaffd8758809e9807c4c5e5504352",
        "Ton activité / Ton métier :",
    ): "Activité",
}


def _sync_special_fields(master_id: str, client_page_id: str, donnees_lisibles: dict) -> None:
    for libelle, valeur in donnees_lisibles.items():
        client_prop = _CLIENT_FIELD_SYNC.get((master_id, libelle))

        if not client_prop:
            continue

        try:
            response = _http.patch(
                f"{NOTION_API_BASE}/pages/{client_page_id}",
                headers=_headers(),
                json={"properties": {client_prop: {"rich_text": [{"text": {"content": str(valeur)}}]}}},
                timeout=15,
            )
            response.raise_for_status()

        except requests.RequestException as error:
            raise RuntimeError(f"Erreur Notion (synchro {client_prop}) : {error}") from error


def _add_dashes(page_id_no_dashes: str) -> str:
    p = page_id_no_dashes
    return f"{p[0:8]}-{p[8:12]}-{p[12:16]}-{p[16:20]}-{p[20:32]}"


# Deuxieme cas de "reponse de fiche connectee ailleurs" : certaines reponses
# chiffrees des fiches de diagnostic alimentent de vraies lignes de "[DB] KPI"
# (une ligne par metrique suivie dans le temps via Valeur J0/J30/J60/J90),
# plutot qu'une simple propriete de "[DB] Clients" comme _CLIENT_FIELD_SYNC.
# On ecrit dans "Valeur J0" car ces fiches sont remplies au moment du
# diagnostic initial.
#
# NB : la fiche 8 "MON RESULTAT DE DIAGNOSTIC" (scores /3 et /15) a ete
# ecartee de ce mapping - verifie en direct dans Notion, son contenu est
# explicitement "A remplir avec votre coach" (blancs "____" en texte simple,
# pas de bloc to_do/sous-puce), donc jamais rempli par le client via le
# portail. La cle utilisee ici doit correspondre au libelle EXACT tel que
# _page_segments() le parse en direct depuis les blocs Notion (pas au libelle
# du fichier portal_fiche_schemas.py, qui ne s'applique qu'aux fiches
# "Suivi recurrent").
_KPI_FIELD_SYNC = {
    (
        "39ffaffd875880abae31d7fd1f7a1c99",
        "Sur 10 rendez-vous commerciaux réalisés, combien de clients signez-vous en moyenne aujourd'hui ?",
    ): {"nom": "Taux de signature (/10 RDV)", "categorie": "Conversion"},
    (
        "39ffaffd875880abae31d7fd1f7a1c99",
        "Sur 10 rendez-vous commerciaux réalisés, combien de clients signes-tu en moyenne aujourd'hui ?",
    ): {"nom": "Taux de signature (/10 RDV)", "categorie": "Conversion"},
}


def _upsert_kpi_entry(
    client_page_id: str, master_id: str | None, kpi_nom: str, categorie: str, valeur: float
) -> None:
    existing = _query_data_source(
        KPI_DATA_SOURCE_ID,
        filter_={
            "and": [
                {"property": "Nom", "title": {"equals": kpi_nom}},
                {"property": "Client", "relation": {"contains": client_page_id}},
            ]
        },
    )

    if existing:
        try:
            response = _http.patch(
                f"{NOTION_API_BASE}/pages/{existing[0]['id']}",
                headers=_headers(),
                json={"properties": {"Valeur J0": {"number": valeur}}},
                timeout=15,
            )
            response.raise_for_status()

        except requests.RequestException as error:
            raise RuntimeError(f"Erreur Notion (mise a jour KPI {kpi_nom}) : {error}") from error

        return

    properties = {
        "Nom": {"title": [{"text": {"content": kpi_nom}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Catégorie": {"select": {"name": categorie}},
        "Phase": {"select": {"name": "J0 · Diagnostic"}},
        "État": {"status": {"name": "En cours"}},
        "Valeur J0": {"number": valeur},
    }

    if master_id:
        properties["Fiche associée"] = {"relation": [{"id": _add_dashes(master_id)}]}

    _create_page(KPI_DATA_SOURCE_ID, properties)


def _sync_kpi_fields(master_id: str, client_page_id: str, donnees_lisibles: dict) -> None:
    for libelle, valeur in donnees_lisibles.items():
        kpi = _KPI_FIELD_SYNC.get((master_id, libelle))

        if not kpi:
            continue

        try:
            valeur_num = float(valeur)
        except (TypeError, ValueError):
            continue

        _upsert_kpi_entry(client_page_id, master_id, kpi["nom"], kpi["categorie"], valeur_num)


def create_entry(fiche_client_id: str, client_page_id: str, client_nom: str, data: dict) -> dict:
    # Une saisie ne change le tableau de bord (objectif, activite, KPI) que pour
    # quelques fiches precises : sinon on garde le cache, la sauvegarde reste
    # rapide et les etats des fiches ne bougent pas.
    affecte = []

    try:
        return _create_entry(fiche_client_id, client_page_id, client_nom, data, affecte)
    finally:
        if affecte:
            _cache_clear("dashboard:")


_CHECKLIST_KEY = "__checklist__"


def _save_checklist(fiche_client_id: str, client_page_id: str, client_nom: str, fiche_nom: str, data: dict) -> dict:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    properties = {
        "Nom": {"title": [{"text": {"content": f"{client_nom} — {fiche_nom} — checklist"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Fiche Client": {"relation": [{"id": fiche_client_id}]},
        "Date": {"date": {"start": now_iso}},
        "Données (JSON)": {"rich_text": [{"text": {"content": json.dumps(data, ensure_ascii=False)}}]},
    }

    existing = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={
            "and": [
                {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
                {"property": "Client", "relation": {"contains": client_page_id}},
                {"property": "Nom", "title": {"contains": "checklist"}},
            ]
        },
    )

    if existing:
        page = _update_page(existing[0]["id"], properties)
    else:
        page = _create_page(ENTREES_PORTAIL_DATA_SOURCE_ID, properties)

    return {"id": page["id"], "date": now_iso, "donnees": data}


def _create_entry(fiche_client_id: str, client_page_id: str, client_nom: str, data: dict, affecte: list) -> dict:
    schema, fiche_nom, master_id = _fiche_schema_for(fiche_client_id)

    if _CHECKLIST_KEY in data:
        return _save_checklist(fiche_client_id, client_page_id, client_nom, fiche_nom, data)

    if any(m == master_id for m, _ in _CLIENT_FIELD_SYNC) or any(m == master_id for m, _ in _KPI_FIELD_SYNC):
        affecte.append(True)

    champs = _champs_for(schema, master_id)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    donnees_lisibles = _donnees_vers_libelles(data, champs)
    _sync_special_fields(master_id, client_page_id, donnees_lisibles)
    _sync_kpi_fields(master_id, client_page_id, donnees_lisibles)

    properties = {
        "Nom": {"title": [{"text": {"content": f"{client_nom} — {fiche_nom} — {now_iso}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Fiche Client": {"relation": [{"id": fiche_client_id}]},
        "Date": {"date": {"start": now_iso}},
        "Données (JSON)": {"rich_text": [{"text": {"content": json.dumps(donnees_lisibles, ensure_ascii=False)}}]},
    }

    if schema["mode"] == "unique":
        existing = _query_data_source(
            ENTREES_PORTAIL_DATA_SOURCE_ID,
            filter_={
                "and": [
                    {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
                    {"property": "Client", "relation": {"contains": client_page_id}},
                ]
            },
        )

        if existing:
            entree = _parse_entry(_update_page(existing[0]["id"], properties), champs)
            _reporter_vers_sheets(schema, client_page_id, client_nom, data)
            return entree

    entree = _parse_entry(_create_page(ENTREES_PORTAIL_DATA_SOURCE_ID, properties), champs)
    _reporter_vers_sheets(schema, client_page_id, client_nom, data)
    return entree


def _reporter_vers_sheets(schema: dict, client_page_id: str, client_nom: str, data: dict) -> None:
    # Les saisies utiles sont reportees dans le Google Sheets du client, en
    # arriere-plan : un probleme Google ne doit jamais empecher d'enregistrer.
    if not sheets_service.enabled():
        return

    def _tache():
        _reporter_vers_sheets_sync(schema, client_page_id, client_nom, data)

    threading.Thread(target=_tache, daemon=True).start()


def _reporter_vers_sheets_sync(schema: dict, client_page_id: str, client_nom: str, data: dict) -> None:
    try:
        props = _get_page(client_page_id).get("properties", {})
        sheets_service.sync_entry_async(
            _num_interne(schema),
            data,
            client_page_id,
            client_nom,
            _prop_value(_prop(props, "E-mail")) or "",
            _est_parcours_atelier(_prop_value(_prop(props, "Parcours"))),
            _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage")),
        )

    except Exception as error:
        logging.getLogger(__name__).warning("Report Sheets impossible : %s", error)


def validate_fiche(fiche_client_id: str) -> None:
    # Remplace le bouton Notion natif "Valider et passer a la fiche suivante"
    # (les blocs "button" ne sont pas manipulables via l'API Notion). On coche
    # directement la case et on passe l'Etat a "Termine" nous-memes plutot que
    # de dependre du polling/webhook n8n existant, pour un deblocage instantane
    # cote client.
    try:
        response = _http.patch(
            f"{NOTION_API_BASE}/pages/{fiche_client_id}",
            headers=_headers(),
            json={
                "properties": {
                    "✅ Valider cette fiche": {"checkbox": True},
                    "État": {"status": {"name": "Terminé"}},
                }
            },
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (validation fiche {fiche_client_id}) : {error}") from error

    _cache_clear("dashboard:")


def list_diagnostics_fiche8() -> list[dict]:
    # Pour l'espace coach : une ligne par client "En cours" avec sa fiche 8
    # (diagnostic), pour valider sans ouvrir Notion. Filtre les fiches du
    # client via sa relation "[DB] Fiches Client" plutot qu'une requete
    # globale sur la relation Fiches Master -> evite de remonter les pages
    # orphelines (anciennes copies non liees, jamais nettoyees) qui trainent
    # dans la base suite a d'anciens cycles de duplication n8n.
    diagnostic_master_id = next(iter(_FICHES_DEBLOCAGE_COACH))

    clients = _query_data_source(
        CLIENTS_DATA_SOURCE_ID,
        filter_={"property": "État", "status": {"equals": "En cours"}},
    )

    result = []

    for client in clients:
        client_id = client["id"]
        nom_client = client_display_name(client)

        fiches = _query_data_source(
            FICHES_CLIENT_DATA_SOURCE_ID,
            filter_={"property": "⁠[DB] Clients⁠", "relation": {"contains": client_id}},
        )

        fiche8 = None
        zones_terminees = 0

        for page in fiches:
            props = page.get("properties", {})
            master_id = _resolve_master_id(props)

            if master_id == diagnostic_master_id:
                fiche8 = {
                    "fiche_client_id": page["id"],
                    "etat": _prop_value(_prop(props, "État")),
                }
            elif master_id in _DIAGNOSTIC_ZONE_IDS and _prop_value(_prop(props, "État")) == "Terminé":
                zones_terminees += 1

        if fiche8:
            result.append({
                "client_page_id": client_id,
                "client_nom": nom_client,
                "fiche_client_id": fiche8["fiche_client_id"],
                "etat": fiche8["etat"],
                "zones_terminees": zones_terminees,
                "diagnostic_pret": zones_terminees >= len(_DIAGNOSTIC_ZONES) and fiche8["etat"] != "Terminé",
            })

    # Les diagnostics prets a valider remontent en premier.
    result.sort(key=lambda d: (not d["diagnostic_pret"], d["client_nom"] or ""))
    return result


_ANNOT_BOLD = {
    "bold": True, "italic": False, "strikethrough": False,
    "underline": False, "code": False, "color": "default",
}
_ANNOT_PLAIN = {
    "bold": False, "italic": False, "strikethrough": False,
    "underline": False, "code": False, "color": "default",
}


def _rt(texte: str, gras: bool = False, italique: bool = False) -> dict:
    annotations = dict(_ANNOT_BOLD if gras else _ANNOT_PLAIN)
    annotations["italic"] = italique
    return {"type": "text", "text": {"content": texte}, "annotations": annotations}


def _initialiser_fiche8(fiche_client_id: str) -> None:
    # Meme structure que la fiche master "8. MON RESULTAT DE DIAGNOSTIC".
    def bloc(type_, *rich_text):
        return {"object": "block", "type": type_, type_: {"rich_text": list(rich_text)}}

    enfants = [
        bloc("heading_1", _rt("\U0001F3C6 MON RÉSULTAT DE DIAGNOSTIC")),
        bloc("paragraph", _rt("C'est ici que nous posons ton point de départ chiffré avant d'attaquer la restructuration.")),
        {"object": "block", "type": "divider", "divider": {}},
        bloc("heading_3", _rt("\U0001F4CA 1. LE SCORE GLOBAL")),
        bloc("bulleted_list_item", _rt("Score d'Offre :", gras=True), _rt(" / 3")),
        bloc("bulleted_list_item", _rt("Score de Visibilité :", gras=True), _rt(" / 3")),
        bloc("bulleted_list_item", _rt("Score de Prospection :", gras=True), _rt(" / 3")),
        bloc("bulleted_list_item", _rt("Score de Conversion :", gras=True), _rt(" / 3")),
        bloc("bulleted_list_item", _rt("Score de Suivi :", gras=True), _rt(" / 3")),
        bloc("bulleted_list_item", _rt("SCORE TOTAL :", gras=True), _rt(" / 15")),
        {"object": "block", "type": "divider", "divider": {}},
        bloc("heading_3", _rt("\U0001F3AF 2. NOS 3 PRIORITÉS POUR LES 90 JOURS")),
        bloc("paragraph", _rt("Sur la base de tes résultats, voici les trois chantiers prioritaires que nous allons mener ensemble :", italique=True)),
        bloc("numbered_list_item", _rt("Priorité 1 :", gras=True), _rt(" ")),
        bloc("numbered_list_item", _rt("Priorité 2 :", gras=True), _rt(" ")),
        bloc("numbered_list_item", _rt("Priorité 3 :", gras=True), _rt(" ")),
    ]

    try:
        response = _http.patch(
            f"{NOTION_API_BASE}/blocks/{fiche_client_id}/children",
            headers=_headers(),
            json={"children": enfants},
            timeout=20,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (initialisation fiche 8 {fiche_client_id}) : {error}") from error


def get_diagnostic_fiche8(fiche_client_id: str) -> list[dict]:
    # Chaque score/priorite de la fiche 8 est un bulleted/numbered_list_item
    # avec exactement 2 segments de rich_text : le libelle en gras ("Score
    # d'Offre :") suivi de la valeur en texte normal (" _0 / 3"). On ne
    # generalise pas au-dela de ce motif precis (skip silencieux si un bloc
    # ne matche pas) pour ne jamais toucher les titres/paragraphes/instructions
    # de la fiche par erreur.
    champs = []
    blocs = _list_children(fiche_client_id)

    if not blocs:
        # La fiche 8 d'un client est parfois une page vide (copie du modele non
        # injectee par le pipeline de duplication) : sans structure, il n'y a
        # aucun champ a remplir. On la cree a l'identique du modele.
        _initialiser_fiche8(fiche_client_id)
        blocs = _list_children(fiche_client_id)

    for block in blocs:
        block_type = block.get("type")

        if block_type not in ("bulleted_list_item", "numbered_list_item"):
            continue

        rich_text = block.get(block_type, {}).get("rich_text", [])

        if len(rich_text) < 2 or not rich_text[0].get("annotations", {}).get("bold"):
            continue

        label = rich_text[0].get("plain_text", "").rstrip().rstrip(":").strip()
        valeur = "".join(part.get("plain_text", "") for part in rich_text[1:]).strip()

        champs.append({
            "block_id": block["id"],
            "type": block_type,
            "label": label,
            "valeur": valeur,
        })

    return champs


def update_diagnostic_fiche8(updates: list[dict]) -> None:
    for update in updates:
        payload = {
            update["type"]: {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": f"{update['label']} :"},
                        "annotations": _ANNOT_BOLD,
                    },
                    {
                        "type": "text",
                        "text": {"content": f" {update['valeur']}"},
                        "annotations": _ANNOT_PLAIN,
                    },
                ]
            }
        }

        try:
            response = _http.patch(
                f"{NOTION_API_BASE}/blocks/{update['block_id']}",
                headers=_headers(),
                json=payload,
                timeout=15,
            )
            response.raise_for_status()

        except requests.RequestException as error:
            raise RuntimeError(
                f"Erreur mise a jour bloc diagnostic {update['block_id']} : {error}"
            ) from error


def _resolve_client(client_id: str) -> dict | None:
    # Identifiant accepte par l'endpoint /coach/diagnostic : l'email du client
    # (chemin nominal, s'appuie sur find_client_by_email) ou, a defaut, un id
    # de page Notion "[DB] Clients". Renvoie None si rien ne correspond plutot
    # que de lever, pour que l'appelant reponde un 404 propre.
    client_id = (client_id or "").strip()

    if not client_id:
        return None

    if "@" in client_id:
        return find_client_by_email(client_id)

    try:
        return _get_page(client_id)

    except RuntimeError:
        return None


def get_coach_diagnostic_bundle(client_id: str) -> dict:
    """Vue lecture seule consolidee du diagnostic initial d'un client.

    Pour chacune des 5 fiches de zone (Offre, Visibilite, Prospection,
    Conversion, Suivi commercial) : les questions fermees Oui/Plutot/Non avec
    la reponse choisie et la reponse ouverte ("ressenti") quand la fiche en
    comporte une. Plus l'etat courant de la fiche 8 (scores/priorites deja
    saisis le cas echeant). Reutilise get_client_dashboard / get_fiche /
    get_diagnostic_fiche8 : aucune logique de parsing dupliquee ici.

    client_id : email du client ou id de page Notion "[DB] Clients".
    Leve LookupError si le client est introuvable.
    """
    client = _resolve_client(client_id)

    if client is None:
        raise LookupError(f"Aucun client trouve pour l'identifiant '{client_id}'.")

    client_page_id = client["id"]
    client_props = client.get("properties", {})

    fiches_par_master = {
        fiche["master_id"]: fiche
        for fiche in get_client_dashboard(client_page_id)["fiches"]
        if fiche.get("master_id")
    }

    zones = []

    for zone in _DIAGNOSTIC_ZONES:
        fiche = fiches_par_master.get(zone["master_id"])

        if fiche is None:
            zones.append({
                "numero": zone["numero"],
                "zone": zone["zone"],
                "fiche_nom": None,
                "fiche_client_id": None,
                "master_id": zone["master_id"],
                "etat": None,
                "repondu_le": None,
                "questions_fermees": [],
                "reponse_ouverte": None,
            })
            continue

        detail = get_fiche(fiche["id"], client_page_id)
        entrees = detail.get("entrees") or []
        derniere = entrees[-1]["donnees"] if entrees else {}
        repondu_le = entrees[-1].get("date") if entrees else None

        questions_fermees = []
        reponse_ouverte = None

        for champ in detail.get("champs") or []:
            valeur = derniere.get(champ["cle"])

            if champ.get("type") == "choix":
                questions_fermees.append({
                    "libelle": champ["libelle"],
                    "options": champ.get("options", []),
                    "reponse": valeur,
                })
            else:
                # Zones 1 a 3 : une question ouverte "texte". Zone 4 : le 4e
                # champ est un nombre (taux de signature /10). Zone 5 : aucune
                # question ouverte -> reste None. On expose le type pour que
                # l'assistant sache a quoi il a affaire.
                reponse_ouverte = {
                    "libelle": champ["libelle"],
                    "type": champ.get("type"),
                    "reponse": valeur,
                }

        zones.append({
            "numero": zone["numero"],
            "zone": zone["zone"],
            "fiche_nom": fiche.get("nom"),
            "fiche_client_id": fiche["id"],
            "master_id": zone["master_id"],
            "etat": fiche.get("etat"),
            "repondu_le": repondu_le,
            "questions_fermees": questions_fermees,
            "reponse_ouverte": reponse_ouverte,
        })

    fiche8 = fiches_par_master.get(_DIAGNOSTIC_FICHE8_MASTER_ID)

    fiche_8 = {
        "fiche_client_id": fiche8["id"] if fiche8 else None,
        "etat": fiche8.get("etat") if fiche8 else None,
        "champs": get_diagnostic_fiche8(fiche8["id"]) if fiche8 else [],
    }

    return {
        "client": {
            "page_id": client_page_id,
            "nom": _prop_value(_prop(client_props, "Nom")),
            "email": _prop_value(_prop(client_props, "E-mail")),
            "etat": _prop_value(_prop(client_props, "État")),
            "objectif_90j": _prop_value(_prop(client_props, "Objectif 90j")),
        },
        "zones": zones,
        "fiche_8": fiche_8,
    }


def _norm(texte) -> str:
    texte = unicodedata.normalize("NFD", str(texte or ""))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return texte.strip().lower()


_REPONSE_POINTS = {"oui": 1.0, "plutot": 0.5, "non": 0.0}

# Libelles exacts de la fiche 8 (page Notion "8. MON RESULTAT DE DIAGNOSTIC").
_FICHE8_LIBELLE_SCORE = {
    "Offre": "Score d'Offre",
    "Visibilité": "Score de Visibilité",
    "Prospection": "Score de Prospection",
    "Conversion": "Score de Conversion",
    "Suivi commercial": "Score de Suivi",
}
_PRIORITE_PAR_ZONE = {
    "Offre": "Clarifier ton offre : un message simple que ta cible comprend tout de suite",
    "Visibilité": "Gagner en visibilité auprès de ta cible, avec une présence régulière",
    "Prospection": "Structurer ta prospection : un rythme, des contacts, un suivi",
    "Conversion": "Améliorer ta conversion : de l'échange au rendez-vous, du rendez-vous à la vente",
    "Suivi commercial": "Mettre en place ton suivi commercial : relances, tableau de bord, chiffres",
}


def get_diagnostic_rapport(client_page_id: str) -> dict:
    """Rapport de diagnostic pour le coach : reponses par zone + proposition de scores.

    Score d'une zone /3 = part de reponses positives (Oui = 1, Plutot = 0,5,
    Non = 0) ramenee sur 3 et arrondie. C'est une PROPOSITION calculee, que le
    coach relit et ajuste avant de valider la fiche 8.
    """
    bundle = get_coach_diagnostic_bundle(client_page_id)
    zones = []
    scores = {}

    for zone in bundle["zones"]:
        points = []

        for question in zone["questions_fermees"]:
            valeur = _REPONSE_POINTS.get(_norm(question.get("reponse")))

            if valeur is not None:
                points.append(valeur)

        score = int(3 * sum(points) / len(points) + 0.5) if points else None
        scores[zone["zone"]] = score
        zones.append({
            "zone": zone["zone"],
            "etat": zone["etat"],
            "repondu_le": zone["repondu_le"],
            "score": score,
            "reponses_positives": sum(points),
            "nb_questions": len(zone["questions_fermees"]),
            "questions": [
                {"libelle": q["libelle"], "reponse": q.get("reponse")}
                for q in zone["questions_fermees"]
            ],
            "reponse_ouverte": zone["reponse_ouverte"],
        })

    scores_connus = {zone: s for zone, s in scores.items() if s is not None}
    total = sum(scores_connus.values())

    propositions = [
        {"label": _FICHE8_LIBELLE_SCORE[zone], "valeur": f"{score} / 3"}
        for zone, score in scores_connus.items()
    ]
    propositions.append({"label": "SCORE TOTAL", "valeur": f"{total} / 15"})

    # Priorites : les 3 zones aux scores les plus bas (a egalite, l'ordre du parcours).
    plus_faibles = sorted(scores_connus.items(), key=lambda item: item[1])[:3]

    for rang, (zone, _score) in enumerate(plus_faibles, start=1):
        propositions.append({"label": f"Priorité {rang}", "valeur": _PRIORITE_PAR_ZONE[zone]})

    return {
        "client": bundle["client"],
        "fiche_8": bundle["fiche_8"],
        "zones": zones,
        "total": total,
        "complet": len(scores_connus) == len(_DIAGNOSTIC_ZONES),
        "propositions": propositions,
    }


def diagnostic_vient_de_se_terminer(client_page_id: str, fiche_client_id: str) -> dict | None:
    """Appelee APRES la validation d'une fiche par le client.

    Renvoie les infos du client si cette validation est celle qui termine les 5
    fiches de zone du diagnostic (et que la fiche 8 n'est pas deja validee),
    sinon None. Sert a alerter le coach une seule fois.
    """
    dashboard = get_client_dashboard(client_page_id)
    fiche_id = fiche_client_id.replace("-", "")
    validee = next((f for f in dashboard["fiches"] if f["id"].replace("-", "") == fiche_id), None)

    if not validee or validee.get("master_id") not in _DIAGNOSTIC_ZONE_IDS:
        return None

    zones = [f for f in dashboard["fiches"] if f.get("master_id") in _DIAGNOSTIC_ZONE_IDS]
    fiche8 = next((f for f in dashboard["fiches"] if f.get("master_id") == _DIAGNOSTIC_FICHE8_MASTER_ID), None)

    # La fiche qu'on vient de valider est comptee comme terminee meme si Notion
    # n'a pas encore propage son nouvel etat.
    toutes_terminees = len(zones) == len(_DIAGNOSTIC_ZONES) and all(
        f.get("etat") == "Terminé" or f["id"].replace("-", "") == fiche_id for f in zones
    )

    if not toutes_terminees or (fiche8 and fiche8.get("etat") == "Terminé"):
        return None

    return {"client_nom": dashboard["nom"], "client_email": (dashboard.get("identite") or {}).get("email")}


def alerter_coach_diagnostic(client_nom: str, client_email: str | None) -> None:
    # Best-effort : un probleme d'alerte ne doit jamais bloquer le client.
    webhook_url = os.getenv("N8N_WEBHOOK_COACH_ALERT")

    if not webhook_url:
        logger.warning("N8N_WEBHOOK_COACH_ALERT manquant : alerte diagnostic non envoyee.")
        return

    portail = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").rstrip("/")
    payload = {
        "event": "diagnostic_termine",
        "client_nom": client_nom,
        "client_email": client_email,
        "coach_url": f"{portail}/coach",
        "subject": f"Diagnostic terminé : {client_nom} (fiche 8 à valider)",
        "message": (
            f"{client_nom} vient de terminer son diagnostic (fiches 3 à 7).\n\n"
            f"Ouvre l'Espace Coach, onglet Diagnostics : le rapport et les scores proposés sont prêts.\n"
            f"{portail}/coach"
        ),
    }

    try:
        requests.post(webhook_url, json=payload, timeout=15).raise_for_status()
        logger.info("Alerte diagnostic envoyee au coach.")

    except requests.RequestException as error:
        logger.warning("Alerte diagnostic non envoyee : %s", _resume_erreur(error))


def _calculer_bonus(champs: list[dict], valeurs: dict) -> dict:
    # Meme logique que BonusPanel (App.jsx) : score d'ancrage local /25 + aides.
    def rep(debut):
        c = next((c for c in champs if c["libelle"].strip().lower().startswith(debut)), None)
        return (valeurs.get(c["cle"]) or "") if c else ""

    total = maxi = repondus = 0

    for c in champs:
        if not re.match(r"^ancrage \d", c["libelle"].strip(), re.I):
            continue
        m = re.search(r"\(max (\d+)\)", c["libelle"])
        maxi += int(m.group(1)) if m else 0
        p = re.search(r"\((\d+) pts?\)", str(valeurs.get(c["cle"]) or ""))
        if p:
            total += int(p.group(1))
            repondus += 1

    terr, eff, exclu = rep("territoire"), rep("effectif"), rep("mon activité relève")
    invest, export, fret = rep("montant de mon projet"), rep("je prospecte"), rep("j'importe")
    apprenti, regulier, rien = rep("je prévois"), rep("mes obligations"), rep("je n'ai encore")
    gp, mq, gf = terr == "Guadeloupe", terr == "Martinique", terr == "Guyane"
    aides = []

    if gp and exclu == "Non" and eff != "5 salariés ou plus" and invest == "Moins de 25 000 €":
        aides.append("ARDDA (jusqu'à 10 000 €, dépôt avant le 31 octobre)")
    if gp and invest == "25 000 à 100 000 €":
        aides.append("ARICE (jusqu'à 40 % des investissements, max 40 000 €)")
    if gp and export == "Oui":
        aides.append("Aide à la prospection internationale (jusqu'à 10 000 €)")
    if (gp and invest == "Plus de 200 000 €") or (mq and invest in ("25 000 à 100 000 €", "100 000 à 200 000 €", "Plus de 200 000 €")):
        aides.append("FEDER (seuil CTM 50 000 €)" if mq else "FEDER-FSE+ Action 1.3 (coût min. 200 000 €)")
    if mq and fret == "Oui":
        aides.append("Aide au fret Martinique")
    if mq and apprenti == "Oui":
        aides.append("ATR / ATEF (apprentissage)")
    if gf:
        aides.append("France 2030 régionalisé / AAP ESS 2026 (valider le guichet)")

    alertes = []
    if regulier == "Non":
        alertes.append("URSSAF / CGSS pas à jour")
    if rien == "Non":
        alertes.append("Dépenses déjà engagées avant dépôt")

    niveau = ("Maximal" if total >= 19 else "Fort" if total >= 12 else "Modéré" if total >= 8 else "Faible")
    return {"territoire": terr, "score": total, "max": maxi or 25, "niveau": niveau,
            "repondus": repondus, "aides": aides, "alertes": alertes}


def get_bonus_resultat(client_page_id: str) -> dict | None:
    fiches = get_client_dashboard(client_page_id).get("fiches", [])
    fiche = next((f for f in fiches if f.get("master_id") == _BONUS_MASTER_ID), None)

    if not fiche:
        return None

    data = get_fiche(fiche["id"], client_page_id)
    valeurs = data["entrees"][-1]["donnees"] if data["entrees"] else {}
    resultat = _calculer_bonus(data["champs"], valeurs)
    resultat["etat"] = fiche.get("etat")
    return resultat


def bonus_vient_de_se_terminer(client_page_id: str, fiche_id: str) -> dict | None:
    fiches = get_client_dashboard(client_page_id).get("fiches", [])
    fiche = next((f for f in fiches if f["id"].replace("-", "") == fiche_id.replace("-", "")), None)

    if not fiche or fiche.get("master_id") != _BONUS_MASTER_ID:
        return None

    resultat = get_bonus_resultat(client_page_id)
    props = _get_page(client_page_id).get("properties", {})
    return {"client_nom": _prop_value(_prop(props, "Nom")), "resultat": resultat}


def alerter_coach_bonus(client_nom: str, r: dict) -> None:
    webhook_url = os.getenv("N8N_WEBHOOK_COACH_ALERT")

    if not webhook_url:
        return

    portail = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").rstrip("/")
    lignes = [
        f"{client_nom} a validé son diagnostic d'éligibilité aux aides.",
        f"Territoire : {r['territoire'] or 'non précisé'}",
        f"Score d'ancrage local : {r['score']} / {r['max']} ({r['niveau']}, seuil bonus 12)",
        "Aides à explorer : " + (", ".join(r["aides"]) or "aucune identifiée"),
    ]
    if r["alertes"]:
        lignes.append("Points de vigilance : " + ", ".join(r["alertes"]))
    lignes.append(f"{portail}/coach")

    try:
        requests.post(webhook_url, json={
            "event": "bonus_termine",
            "client_nom": client_nom,
            "subject": f"Bonus aides : {client_nom} ({r['score']}/{r['max']})",
            "message": "\n".join(lignes),
        }, timeout=15).raise_for_status()
    except requests.RequestException as error:
        logger.warning("Alerte bonus non envoyee : %s", _resume_erreur(error))


def alerter_coach_onboarding(sujet: str, message: str) -> None:
    # Best-effort, sur le modele de alerter_coach_diagnostic : un probleme
    # d'alerte ne doit jamais bloquer l'onboarding ni le webhook. En cas
    # d'echec reseau on ne logue QUE la classe de l'exception : le texte d'une
    # erreur `requests` contient l'URL du webhook n8n (jamais journalisee ici,
    # pas plus que le payload ou l'email).
    journal = logging.getLogger("uvicorn.error")  # visible dans les logs Render
    webhook_url = os.getenv("N8N_WEBHOOK_COACH_ALERT")

    if not webhook_url:
        journal.warning("N8N_WEBHOOK_COACH_ALERT manquant : alerte onboarding non envoyee.")
        return

    portail = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").rstrip("/")

    try:
        requests.post(webhook_url, json={
            "event": "onboarding_docuseal_echec",
            "subject": sujet,
            "message": f"{message}\n{portail}/coach",
            "coach_url": f"{portail}/coach",
        }, timeout=15).raise_for_status()

    except requests.RequestException as error:
        journal.warning("Alerte onboarding non envoyee (%s).", type(error).__name__)


def send_portal_invite(email: str, client_page_id: str, client_nom: str) -> None:
    # Factorise la logique utilisee par /portal/auth/request-link : partagee
    # avec onboard_client() pour que le lien d'acces parte automatiquement
    # des la creation du client, sans repasser par le formulaire de login.
    webhook_url = os.getenv("N8N_WEBHOOK_MAGIC_LINK")

    if not webhook_url:
        raise RuntimeError(
            "N8N_WEBHOOK_MAGIC_LINK manquant. "
            "Copie .env.example vers .env et renseigne l'URL du webhook n8n."
        )

    portal_frontend_url = os.getenv("PORTAL_FRONTEND_URL", "http://localhost:5174")
    token = portal_auth_service.create_magic_link_token(email, client_page_id)
    magic_link = f"{portal_frontend_url}/verify?token={token}"

    payload = {"to": email, "client_name": client_nom, "magic_link": magic_link}

    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur envoi invitation portail : {error}") from error


def log_portal_connection(email: str, client_page_id: str) -> None:
    # Journal des connexions reussies (lien magique verifie -> session creee).
    # Best-effort : une erreur ici ne doit jamais faire echouer une vraie
    # connexion client, donc on avale l'exception et on logue un warning.
    try:
        client_page = _get_page(client_page_id)
        client_nom = client_display_name(client_page)
    except RuntimeError:
        client_nom = ""

    properties = {
        "Email": {"title": [{"text": {"content": email}}]},
        "Client": {"rich_text": [{"text": {"content": client_nom}}]},
        "Date de connexion": {
            "date": {"start": datetime.now(timezone.utc).isoformat()}
        },
    }

    try:
        _create_page(CONNEXIONS_DATA_SOURCE_ID, properties)
    except RuntimeError as error:
        logger.warning("Echec journalisation connexion portail : %s", _resume_erreur(error))


# Champs optionnels que le coach peut renseigner des l'onboarding minimal
# (nom + email obligatoires, tout le reste facultatif - "les deux temps" :
# ce que le coach connait deja apres l'appel de vente est pre-rempli ici : le
# reste sera complete par le client lui-meme dans le portail, fiche par
# fiche). cle -> (propriete Notion exacte, type de propriete API Notion).
CLIENT_ONBOARDING_FIELDS = {
    "activite": ("Activité", "rich_text"),
    "secteur": ("Secteur", "rich_text"),
    "territoire": ("Territoire", "rich_text"),
    "contact": ("Contact", "rich_text"),
    "offre_principale": ("Offre Principale", "rich_text"),
    "client_cible": ("Client Cible", "rich_text"),
    "objectif_90j": ("Objectif 90j", "rich_text"),
    "urgence_echeance": ("Urgence / Échéance", "rich_text"),
    "telephone": ("Téléphone", "phone_number"),
    "site_reseaux": ("Site / Réseaux", "url"),
}

# KPI de depart crees automatiquement a l'onboarding (memes 4 indicateurs que
# la section "3) KPI de depart & Objectifs" du modele "Onboarding Client").
# Cle de gauche = cle attendue dans le dict optionnel "kpi_j0" transmis par
# le coach a l'onboarding (typiquement les chiffres donnes par le client
# pendant l'appel de vente). Aucune fiche de diagnostic du parcours ne pose
# ces 4 questions sous forme de nombre exploitable (zones 1-5 sont des
# auto-evaluations Oui/Plutot/Non + une question ouverte texte chacune) : la
# seule source fiable pour une valeur J0 immediate est donc le coach
# lui-meme, saisie une fois ici plutot que laissee vide sans aucun moyen de
# la remplir depuis le portail.
_KPI_ONBOARDING_DEFAULTS = [
    {"cle": "leads_j0", "nom": "Leads", "categorie": "Acquisition"},
    {"cle": "rdv_j0", "nom": "RDV", "categorie": "Acquisition"},
    {"cle": "nouveaux_clients_j0", "nom": "Nouveaux clients", "categorie": "Conversion"},
    {"cle": "ca_j0", "nom": "Chiffre d’affaires", "categorie": "Chiffre d’affaires"},
]


def _fiche_master_items_sorted() -> list[tuple[str, dict]]:
    items = list(FICHE_SCHEMAS.items())
    items.sort(key=lambda item: int(_leading_number(item[1]["nom"]) or 999))
    return items


class ClientDejaExistant(RuntimeError):
    # Doublon d'onboarding. Sous-classe de RuntimeError : tous les appelants et
    # tests existants continuent de fonctionner, le message reste inchange.
    pass


def onboard_client(nom: str, email: str, kpi_j0: dict | None = None, **extra) -> dict:
    # Remplace entierement la procedure manuelle "[Procedure] Nouveau client -
    # copie & acces" (creation client + duplication des 22 fiches + KPI J0)
    # par de vrais appels API Notion, plutot que de dependre du bouton Notion
    # "Creer le parcours complet" (type "button", non pilotable via l'API) ou
    # du declencheur reel du pipeline n8n existant (non verifiable depuis
    # cette session). Corrige au passage les lacunes connues du pipeline n8n :
    # "Ordre" et la relation "[DB] Fiches Master" sont renseignes des la
    # creation, sur chacune des 22 fiches.
    #
    # Notion n'offre aucune transaction multi-appels : ~27 creations de pages
    # se suivent (client + 22 fiches + 4 KPI). Deux garde-fous compensent
    # cette absence de transaction :
    # - idempotence : un email deja onboarde bloque l'appel avant toute
    #   creation, pour eviter un doublon si l'endpoint est rappele par erreur.
    # - rollback : toute page deja creee est archivee si une etape echoue en
    #   cours de route, plutot que de laisser un client "a moitie onboarde".
    email = (email or "").strip().lower()
    client_existant = find_client_by_email(email)

    if client_existant:
        raise ClientDejaExistant(
            f"Un client existe deja avec l'email {email} "
            f"(page Notion {client_existant['id']}). Onboarding annule pour eviter un doublon."
        )

    properties = {
        "Nom": {"title": [{"text": {"content": nom}}]},
        "E-mail": {"email": email},
        "Phase parcours": {"select": {"name": "Module 0 actif"}},
        "État": {"status": {"name": "En cours"}},
        "Date de démarrage": {
            "date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        },
    }

    for cle, valeur in extra.items():
        champ = CLIENT_ONBOARDING_FIELDS.get(cle)

        if not champ or valeur in (None, ""):
            continue

        prop_name, prop_type = champ

        if prop_type == "rich_text":
            properties[prop_name] = {"rich_text": [{"text": {"content": str(valeur)}}]}
        elif prop_type == "url":
            properties[prop_name] = {"url": str(valeur)}
        elif prop_type == "phone_number":
            properties[prop_name] = {"phone_number": str(valeur)}

    date_demarrage = str(extra.get("date_demarrage") or "").strip()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_demarrage):
        properties["Date de démarrage"] = {"date": {"start": date_demarrage}}

    atelier = _est_parcours_atelier(extra.get("parcours"))
    properties["Parcours"] = {"select": {"name": "Atelier" if atelier else "Coaching 90 jours"}}

    kpi_j0 = kpi_j0 or {}
    created_page_ids: list[str] = []

    try:
        client_page = _create_page(CLIENTS_DATA_SOURCE_ID, properties)
        client_id = client_page["id"]
        created_page_ids.append(client_id)

        fiches_creees = 0

        for master_id, schema in _fiche_master_items_sorted():
            if atelier and master_id not in _ATELIER_JOUR:
                continue

            ordre = int(_leading_number(schema["nom"]) or 0)

            fiche_properties = {
                "Nom": {"title": [{"text": {"content": f"{nom} - {schema['nom']}"}}]},
                "⁠[DB] Clients⁠": {"relation": [{"id": client_id}]},
                "⁠[DB] Fiches Master": {"relation": [{"id": _add_dashes(master_id)}]},
                "Ordre": {"number": ordre},
                "État": {"status": {"name": "Pas commencé"}},
                "✅ Valider cette fiche": {"checkbox": False},
            }

            fiche_page = _create_page(FICHES_CLIENT_DATA_SOURCE_ID, fiche_properties)
            created_page_ids.append(fiche_page["id"])
            fiches_creees += 1

        kpi_crees = 0
        kpi_a_completer = []

        for kpi in _KPI_ONBOARDING_DEFAULTS:
            valeur_j0 = kpi_j0.get(kpi["cle"])
            a_une_valeur = valeur_j0 not in (None, "")

            kpi_properties = {
                "Nom": {"title": [{"text": {"content": kpi["nom"]}}]},
                "Client": {"relation": [{"id": client_id}]},
                "Catégorie": {"select": {"name": kpi["categorie"]}},
                "Phase": {"select": {"name": "J0 · Diagnostic"}},
                "État": {"status": {"name": "En cours" if a_une_valeur else "Pas commencé"}},
            }

            if a_une_valeur:
                kpi_properties["Valeur J0"] = {"number": float(valeur_j0)}
            else:
                kpi_a_completer.append(kpi["nom"])

            kpi_page = _create_page(KPI_DATA_SOURCE_ID, kpi_properties)
            created_page_ids.append(kpi_page["id"])
            kpi_crees += 1

    except RuntimeError as error:
        echecs_rollback = _rollback_pages(created_page_ids)

        if echecs_rollback:
            raise RuntimeError(
                f"Onboarding de {nom} echoue ({error}). Rollback partiel : "
                f"{len(created_page_ids) - len(echecs_rollback)}/{len(created_page_ids)} page(s) archivee(s), "
                f"{len(echecs_rollback)} page(s) restent orphelines et doivent etre archivees a la main dans "
                f"Notion : {echecs_rollback}."
            ) from error

        raise RuntimeError(
            f"Onboarding de {nom} echoue et annule proprement ({error}). "
            f"{len(created_page_ids)} page(s) deja creee(s) ont ete archivees automatiquement, aucun residu."
        ) from error

    invite_envoyee = False
    invite_erreur = None

    try:
        send_portal_invite(email, client_id, nom)
        invite_envoyee = True

    except RuntimeError as error:
        # Code fixe uniquement : ce resultat est renvoye au navigateur du coach,
        # et le texte de l'erreur contient l'URL du webhook n8n. Le diagnostic
        # (resume sans URL ni identite) reste dans les logs serveur.
        invite_erreur = "envoi_invitation_echoue"
        logger.warning("Invitation portail non envoyee : %s", _resume_erreur(error))

    return {
        "client_id": client_id,
        "nom": nom,
        "email": email,
        "fiches_creees": fiches_creees,
        "kpi_crees": kpi_crees,
        "kpi_a_completer": kpi_a_completer,
        "invite_envoyee": invite_envoyee,
        "invite_erreur": invite_erreur,
    }
