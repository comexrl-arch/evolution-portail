import copy
import difflib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from backend.services.portal_fiche_schemas import FICHE_SCHEMAS
from backend.services import ia_service, portal_auth_service, sheets_service

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

    if prop_type == "phone_number":
        return prop.get("phone_number")

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


_TTL_DASHBOARD = 300  # secondes (5 min : navigation instantanee, invalide a chaque ecriture)
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


# Propriete "Texte" de "[DB] Clients" qui recoit l'empreinte du mot de passe du
# portail (jamais le mot de passe en clair, voir portal_auth_service).
PASSWORD_PROPERTY = os.getenv("NOTION_CLIENT_PASSWORD_PROPERTY", "Mot de passe portail")


def client_password_hash(client_page: dict) -> str:
    return _prop_value(_prop((client_page or {}).get("properties", {}), PASSWORD_PROPERTY)) or ""


def get_client_page(client_page_id: str) -> dict:
    return _get_page(client_page_id)


def definir_mot_de_passe_client(client_page_id: str, empreinte: str) -> None:
    _update_page(client_page_id, {PASSWORD_PROPERTY: {"rich_text": [{"text": {"content": empreinte}}]}})


def definir_date_demarrage(email: str, date_iso: str) -> str:
    # Atelier : la date de la session 1 (J0 du parcours) est saisie par le coach
    # dans DocuSeal, souvent apres la creation du client. On la reporte sur sa
    # fiche Notion sans jamais remplacer une date deja presente.
    # Renvoie "reporte", "deja_a_jour" ou "absent".
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso or ""):
        raise ValueError("Date de demarrage invalide")

    client = find_client_by_email(email) if (email or "").strip() else None

    if not client:
        return "absent"

    props = client.get("properties", {})

    if _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage")):
        return "deja_a_jour"

    _update_page(client["id"], {"Date de démarrage": {"date": {"start": date_iso}}})
    _cache_clear("dashboard:")
    return "reporte"


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
    "- **Avance pas à pas :** tu avances fiche par fiche, dans l'ordre proposé.",
    "- **Déblocage progressif :** chaque fiche validée débloque la suivante, et les fiches de chaque session s'ouvrent le jour de la session.",
    "- **Ton diagnostic d'abord :** avant la session 1, tu remplis ton diagnostic commercial. Ton coach le valide : c'est ce qui ouvre la suite de ton parcours.",
    "### 🗺️ TON PARCOURS",
    "- **Avant la session 1 :** ton point de départ et ton diagnostic commercial.",
    "- **Session 1 · Clarifier :** ton offre, ta cible, ta phrase de positionnement.",
    "- **Session 2 · Prospecter :** ton script d'approche.",
    "- **Session 3 · Suivre :** ton tableau de prospection. Il reste ouvert ensuite : chaque prospect contacté se reporte tout seul dans ton Tableau de bord.",
    "- **Session 4 · Planifier :** ton plan de la semaine type.",
    "- **En fin d'atelier :** un entretien individuel de 20 minutes avec ton coach.",
    "### ⚡ LE SEUL GESTE À RETENIR",
    "Une fois que tu as lu ou complété une fiche, va tout en bas de la page et clique sur le bouton : 👉 **« Valider et continuer »**.",
    "La fiche suivante se débloque alors dans ton parcours.",
]
_ATELIER_PERMANENTES = {_NUMERO_TO_MASTER_ID["14"], _NUMERO_TO_MASTER_ID["13"]}


def _est_parcours_atelier(valeur) -> bool:
    return "atelier" in str(valeur or "").lower()


# Parcours "eVolution Autonome" (decision du 21/10/2026) : meme parcours que le
# Coaching 90 jours (memes fiches, meme frise), sans intervention du coach.
# La fiche 8 est remplie et validee automatiquement a la fin du diagnostic, et
# une synthese IA est redigee tous les 30 jours (workflow n8n).
def _est_parcours_autonome(valeur) -> bool:
    return "autonome" in str(valeur or "").lower()


def _nom_parcours(valeur) -> str:
    if _est_parcours_atelier(valeur):
        return "Atelier"

    if _est_parcours_autonome(valeur):
        return "Autonome"

    return "Coaching 90 jours"


# Texte de bienvenue (fiche 0) propre a l'Autonome : page Notion a part,
# modifiable par Rony (vide tant qu'elle n'existe pas : texte de secours).
_AUTONOME_FICHE0_TEXTE_PAGE_ID = os.getenv("NOTION_AUTONOME_FICHE0_PAGE_ID", "")
_AUTONOME_FICHE0_TEXTE = [
    "# 👋 BIENVENUE DANS TON ESPACE eVOLUTION AUTONOME",
    "Bonjour et bienvenue dans ton espace de travail personnel. Tu suis ici la méthode complète du programme 90 jours, à ton rythme.",
    "### 📖 COMMENT ÇA MARCHE ?",
    "- **Avance pas à pas :** tu avances fiche par fiche, dans l'ordre proposé.",
    "- **Déblocage progressif :** chaque fiche validée débloque la suivante, et les étapes s'ouvrent au fil des jours (de J0 à J90).",
    "- **Ton diagnostic d'abord :** tu commences par ton diagnostic commercial. Ton résultat est calculé automatiquement et t'indique ta priorité des 30 prochains jours.",
    "### 🗺️ TON PARCOURS",
    "- **Démarrage :** ton point de départ et ton diagnostic.",
    "- **Clarifier :** ton offre, ta phrase de positionnement, ta cible, ton script d'approche.",
    "- **Prospecter :** ton plan chaque lundi, ton bilan chaque vendredi. Tes chiffres se reportent tout seuls dans ton Tableau de bord.",
    "- **Convertir et stabiliser :** tes rendez-vous, tes objections, ton suivi de closing, ton bilan J90.",
    "### 🤝 CE QUI T'ACCOMPAGNE",
    "- **Une synthèse tous les 30 jours :** un point écrit sur ce que tu as fait, avec tes 3 actions pour le mois suivant.",
    "- **Un point collectif chaque mois avec Rony :** garde tes questions pour ce moment-là.",
    "### ⚡ LE SEUL GESTE À RETENIR",
    "Une fois que tu as lu ou complété une fiche, va tout en bas de la page et clique sur le bouton : 👉 **« Valider et continuer »**.",
    "La fiche suivante se débloque alors dans ton parcours.",
]


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


def _apply_acces(
    fiches: list[dict], date_demarrage=None, jours=None, permanentes=None, verrou_coach: bool = True
) -> None:
    # Calcule le deblocage nous-memes plutot que de lire la formule Notion
    # "acces". Trois regles, dans l'ordre du parcours (_PARCOURS) :
    #  1. jour d'ouverture atteint (frise J0 -> J90) ;
    #  2. fiche precedente terminee ;
    #  3. verrou coach : rien ne s'ouvre apres la fiche 8 tant que le coach
    #     ne l'a pas passee a Termine. Sans verrou (parcours Autonome), la
    #     fiche 8 suit la regle normale : filet de securite si son
    #     remplissage automatique a echoue, le client peut la valider.
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

        if verrou_coach and master_id in _FICHES_DEBLOCAGE_COACH:
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


# Rythme du parcours (affichage du 26/10/2026) : nourrit le bandeau « Ton cap
# 90 jours » du tableau de bord. Une fiche est en retard 7 jours apres son
# jour d'ouverture si elle n'est pas terminee. Ne comptent pas : les fiches de
# suivi (permanentes), la fiche 8 validee par le coach et tout ce qui attend
# cette validation, puisque le client n'y peut rien.
_DELAI_FICHE = 7
_ETAPES_90J = [("Démarrage", 0), ("Clarifier", 4), ("Prospecter", 31), ("Convertir", 61), ("Stabiliser", 75)]
_ETAPES_ATELIER = [("Session 1", 0), ("Session 2", 7), ("Session 3", 14), ("Session 4", 21)]


def _rythme_parcours(fiches: list[dict], date_demarrage, atelier: bool = False, verrou_coach: bool = True) -> dict | None:
    jour = _jour_parcours(date_demarrage)

    if jour is None:
        return None

    jours = _ATELIER_JOUR if atelier else _FICHE_JOUR
    permanentes = _ATELIER_PERMANENTES if atelier else _FICHES_PERMANENTES
    jour_fiche8 = max(jours.get(master_id, 0) for master_id in _FICHES_DEBLOCAGE_COACH)
    attente_coach = verrou_coach and any(
        f.get("master_id") in _FICHES_DEBLOCAGE_COACH and f.get("etat") != "Terminé" for f in fiches
    )
    en_retard = 0

    for fiche in fiches:
        master_id = fiche.get("master_id")

        if master_id not in jours or master_id in permanentes or fiche.get("etat") == "Terminé":
            continue
        if verrou_coach and master_id in _FICHES_DEBLOCAGE_COACH:
            continue
        if attente_coach and jours[master_id] > jour_fiche8:
            continue
        if jours[master_id] <= jour - _DELAI_FICHE:
            en_retard += 1

    return {
        "jour": jour,
        "duree": 28 if atelier else 90,
        "etapes": [{"libelle": libelle, "debut": debut} for libelle, debut in (_ETAPES_ATELIER if atelier else _ETAPES_90J)],
        "en_retard": en_retard,
    }


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
        "lien_groupe": _prop_value(_prop(cohorte_props, "Lien groupe")),
    }


def _client_sessions(props: dict) -> list[dict]:
    session_ids = _prop_value(_prop(props, "Sessions")) or []

    if not session_ids:
        return []

    def _fetch_session(session_id: str) -> dict:
        session_props = _get_page(session_id).get("properties", {})
        return {
            "id": session_id,
            "nom": _prop_value(_prop(session_props, "Nom")),
            "date_heure": _prop_value(_prop(session_props, "Date & heure")),
            "statut": _prop_value(_prop(session_props, "Statut")),
            "prochaine_echeance": _prop_value(_prop(session_props, "Prochaine échéance")),
            # Proprietes facultatives (onglet Communaute, lot 4) : absentes = None.
            "lien": _prop_value(_prop(session_props, "Lien")),
            "replay": _prop_value(_prop(session_props, "Replay")),
        }

    # _POOL_BLOCS et non _POOL : _client_sessions tourne deja dans _POOL, et
    # attendre des sous-taches du meme pool peut le bloquer sous charge.
    sessions = list(_POOL_BLOCS.map(_fetch_session, session_ids))
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


# Valeurs et objectifs KPI que le client peut saisir lui-meme depuis le
# tableau de bord, a tout moment du parcours (indispensable pour l'Autonome,
# qui n'a pas de coach pour les renseigner, et pour les clients crees par le
# webhook DocuSeal, dont le J0 reste vide). Cle du portail -> propriete Notion.
KPI_CHAMPS_SAISISSABLES = {
    "valeur_j0": "Valeur J0",
    "valeur_j30": "Valeur J30",
    "valeur_j60": "Valeur J60",
    "valeur_j90": "Valeur J90",
    "objectif_j30": "Objectif J30",
    "objectif_j60": "Objectif J60",
    "objectif_j90": "Objectif J90",
}


def update_kpi(kpi_id: str, valeurs: dict, etat_actuel: str | None = None) -> None:
    # None efface la valeur. Les cles inconnues sont ignorees (la route les
    # refuse deja en amont).
    properties = {
        KPI_CHAMPS_SAISISSABLES[cle]: {"number": None if valeur is None else float(valeur)}
        for cle, valeur in valeurs.items()
        if cle in KPI_CHAMPS_SAISISSABLES
    }

    if not properties:
        return

    # Une premiere saisie fait passer l'indicateur de "Pas commencé" a "En cours"
    # (un indicateur "Terminé" garde son etat).
    if etat_actuel == "Pas commencé" and any(v.get("number") is not None for v in properties.values()):
        properties["État"] = {"status": {"name": "En cours"}}

    _update_page(kpi_id, properties)
    _cache_clear("dashboard:")


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

    # Appels independants lances ensemble : fiches, KPI, cohorte, sessions, classeur Google.
    kpi_future = _POOL.submit(_client_kpi, client_page_id)
    cohorte_future = _POOL.submit(_client_cohorte, props)
    sessions_future = _POOL.submit(_client_sessions, props)
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
    autonome = _est_parcours_autonome(_prop_value(_prop(props, "Parcours")))
    atelier = _est_parcours_atelier(_prop_value(_prop(props, "Parcours")))

    if atelier:
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
        _apply_acces(fiches, date_demarrage, verrou_coach=not autonome)

    cohorte = cohorte_future.result()
    rythme = _rythme_parcours(fiches, date_demarrage, atelier=atelier, verrou_coach=not autonome)
    syntheses = syntheses_du_client(client_page_id, fiches) if autonome else []

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
        "cohorte": cohorte,
        "sessions": sessions_future.result(),
        "fiches": fiches,
        "kpi": kpi_future.result(),
        "syntheses": syntheses,
        "personnalisation": _personnaliser_parcours(fiches),
        "regularite": _regularite_bilans(fiches),
        "rythme": rythme,
        "lien_groupe": _lien_groupe(cohorte),
        "passerelle_coaching": _passerelle_coaching(rythme, syntheses) if autonome else None,
    }


# Passerelle Autonome vers Coaching (decision de Rony du 27/10/2026) : a
# partir de J30, quand le membre Autonome bloque (3 fiches de retard ou plus,
# ou derniere synthese mensuelle « reprise » : aucune fiche terminee dans le
# mois), Idris lui propose un appel diagnostic avec Rony. Le portail ne la
# montre qu'une fois par periode de 30 jours.
PASSERELLE_JOUR_MIN = 30
PASSERELLE_RETARD_MIN = 3
PASSERELLE_COACHING_URL = os.getenv("PASSERELLE_COACHING_URL", "https://calendly.com/rl-evolution/20min")


def _passerelle_coaching(rythme: dict | None, syntheses: list[dict]) -> dict | None:
    jour = (rythme or {}).get("jour")

    if jour is None or jour < PASSERELLE_JOUR_MIN:
        return None

    en_retard = (rythme or {}).get("en_retard") or 0
    reprise = bool(syntheses) and syntheses[0].get("axe") == "reprise"

    if en_retard < PASSERELLE_RETARD_MIN and not reprise:
        return None

    return {
        "periode": jour // 30,
        "raison": "retard" if en_retard >= PASSERELLE_RETARD_MIN else "reprise",
        "en_retard": en_retard,
        "url": PASSERELLE_COACHING_URL,
    }


def alerter_coach_passerelle(client_nom: str, client_email: str | None, telephone: str | None, details: dict) -> None:
    # Best-effort, meme canal que l'alerte diagnostic (n8n -> Telegram/email).
    webhook_url = os.getenv("N8N_WEBHOOK_COACH_ALERT")

    if not webhook_url:
        logger.warning("N8N_WEBHOOK_COACH_ALERT manquant : alerte passerelle non envoyee.")
        return

    lignes = [
        f"{client_nom} (Autonome, J{details.get('jour')}) a cliqué sur « Réserver mon appel » depuis son portail.",
        "",
        f"Fiches terminées : {details.get('fiches_terminees')} sur {details.get('fiches_total')}, dont {details.get('en_retard')} en retard.",
    ]

    if details.get("semaine"):
        s = details["semaine"]
        lignes.append(f"Dernier bilan (semaine du {s['semaine_du']}) : {s['contacts']:g} contacts, {s['rdv']:g} RDV, {s['ventes']:g} ventes.")

    if details.get("objectif"):
        lignes.append(f"Son objectif 90 jours : {details['objectif']}")

    lignes += ["", f"Email : {client_email or 'inconnu'} · Téléphone : {telephone or 'inconnu'}"]
    payload = {
        "event": "passerelle_coaching",
        "client_nom": client_nom,
        "client_email": client_email,
        "subject": f"Passerelle Coaching : {client_nom} veut un appel",
        "message": "\n".join(lignes),
    }

    try:
        requests.post(webhook_url, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as error:
        logger.warning("Alerte passerelle non envoyee : %s", _resume_erreur(error))


def _lien_groupe(cohorte: dict | None) -> str | None:
    # Lien du groupe de la cohorte, sinon le groupe commun a tous les clients
    # (variable COMMUNAUTE_LIEN_GROUPE sur Render). Seuls les liens https passent.
    lien = (cohorte or {}).get("lien_groupe") or os.getenv("COMMUNAUTE_LIEN_GROUPE") or ""
    return lien if lien.startswith("https://") else None


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

        if _options_du_todo(block):
            # "Telephone | WhatsApp | ..." : liste d'options, pas une case.
            # Une seule case pour tout cocher a la fois n'aurait aucun sens.
            return [texte]

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
            legende = _rich_text_md(data.get("caption", [])).strip().replace("|", " ")
            lines.append(f"{_IMAGE_LINE_PREFIX}{url}|{legende}")

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
_IMAGE_LINE_PREFIX = "##IMAGE## "


def _blocks_to_text(blocks: list[dict], checks: bool = False) -> str:
    lines = []

    for block in blocks:
        lines.extend(_block_lines(block, 0, checks))

    return "\n".join(lines)


def _get_page_content(page_id: str, checks: bool = False) -> str:
    return _blocks_to_text(_list_children(page_id), checks)


def _options_du_todo(block: dict) -> list[str]:
    # Motif "Oui | Plutot | Non" ecrit dans une case a cocher : ce sont des
    # options a choisir, pas une case. Vide si le texte n'a pas de "|".
    texte = _block_text(block)

    if "|" not in texte:
        return []

    return [option.strip() for option in texte.split("|") if option.strip()]


def _question_sans_zone(block: dict) -> str | None:
    # Puce en gras sans sous-puce "Ecris ici..." : "**Le segment cible :**".
    # Sans ce repere, la question s'affichait comme du texte, sans aucun
    # moyen d'y repondre. Renvoie le libelle de la question, sinon None.
    # Pas de detection des "trous" (double espace) : la fiche 8 en contient
    # ("**Score d'Offre :**  / 3") et ces lignes sont remplies par le coach.
    if block.get("type") != "bulleted_list_item" or block.get("has_children"):
        return None

    parts = block.get("bulleted_list_item", {}).get("rich_text", [])

    if not parts or not (parts[0].get("annotations") or {}).get("bold"):
        return None

    texte = "".join(part.get("plain_text", "") for part in parts)
    reste = "".join(
        part.get("plain_text", "")
        for part in parts
        if not (part.get("annotations") or {}).get("bold")
    )
    propre = texte.strip("* ").strip()

    if not reste.strip() and propre.endswith((":", "?")):
        return propre

    return None


def _page_segments(page_id: str, questions_libres: bool = True) -> list[dict]:
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
            options = _options_du_todo(block)
            segments.append({
                "type": "champ",
                "champ": {
                    "cle": block["id"].replace("-", ""),
                    "libelle": "Choisis une option" if options else _block_text(block).strip("* "),
                    "type": "choix" if options else "case",
                    **({"options": options} if options else {}),
                },
            })
            continue

        question = _question_sans_zone(block) if questions_libres else None

        if question:
            segments.append({
                "type": "champ",
                "champ": {
                    "cle": block["id"].replace("-", ""),
                    "libelle": question,
                    "type": "texte",
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
                seule = _block_text(todo_children[0]).strip()
                options = _options_du_todo(todo_children[0]) or ([seule] if seule else [])
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
    resultat = {}
    orphelins = {}

    for libelle, valeur in donnees.items():
        if libelle in libelle_vers_cle:
            resultat[libelle_vers_cle[libelle]] = valeur
        elif libelle.startswith("__"):
            resultat[libelle] = valeur
        else:
            orphelins[libelle] = valeur

    # Question reformulee dans Notion depuis la reponse (ex. "vous" -> "tu") :
    # on rattache l'ancienne reponse a la question la plus proche, pour que
    # le client ne la voie pas disparaitre.
    libres = [champ for champ in champs if champ["cle"] not in resultat]

    for libelle, valeur in orphelins.items():
        proche = max(
            libres,
            key=lambda champ: difflib.SequenceMatcher(None, libelle.lower(), champ["libelle"].lower()).ratio(),
            default=None,
        )

        if proche and difflib.SequenceMatcher(None, libelle.lower(), proche["libelle"].lower()).ratio() >= 0.75:
            resultat[proche["cle"]] = valeur
            libres.remove(proche)
        else:
            resultat[libelle] = valeur

    return resultat


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
        "retour_ia": _retour_ia_visible(props),
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
# en minuscules sur leur debut, sans guillemets : robuste a de petites
# retouches dans Notion ("C'est trop cher" -> « C'est trop cher »).
_PREFILL_ENTRE_FICHES = [
    ("9", "quel est le problème urgent", "10", "quelle est sa plus grande frustration"),
    ("11", "ma phrase officielle", "15", "mon script personnalisé"),
    ("11", "ma phrase officielle", "16", "objection : c'est trop cher"),
]


def _debut_libelle(libelle: str) -> str:
    return " ".join(re.sub(r"[\"«»“”]", " ", libelle).lower().split())


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
            (c for c in champs if _debut_libelle(c["libelle"]).startswith(dlib)), None
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
                (c for c in src_champs if _debut_libelle(c["libelle"]).startswith(lsrc)), None
            )

            if champ_src and entrees:
                valeur = entrees[-1]["donnees"].get(champ_src["cle"])

                if valeur not in (None, ""):
                    prefill[champ_dst["cle"]] = valeur
        except Exception as error:
            logger.warning("Pre-remplissage entre fiches impossible (%s)", error)

    return prefill


def reponses_des_fiches(client_page_id: str, fiches: list[dict], master_ids: list[str]) -> list[dict]:
    """Dernieres reponses texte du client aux fiches demandees, dans l'ordre :
    [{"nom", "reponses": [(libelle, valeur)]}]. Sert de matiere aux brouillons IA."""
    par_master = {f.get("master_id"): f for f in fiches}
    resultat = []

    for master_id in master_ids:
        fiche = par_master.get(master_id)

        if not fiche or master_id not in FICHE_SCHEMAS:
            continue

        try:
            champs = _champs_for(FICHE_SCHEMAS[master_id], master_id)
            pages = _query_data_source(
                ENTREES_PORTAIL_DATA_SOURCE_ID,
                {
                    "and": [
                        {"property": "Fiche Client", "relation": {"contains": fiche["id"]}},
                        {"property": "Client", "relation": {"contains": client_page_id}},
                    ]
                },
            )
        except Exception as error:
            logger.warning("Reponses de fiche illisibles (%s)", error)
            continue

        entrees = [_parse_entry(p, champs) for p in pages]
        entrees = [e for e in entrees if _CHECKLIST_KEY not in (e.get("donnees") or {})]

        if not entrees:
            continue

        entrees.sort(key=lambda e: e.get("date") or "")
        donnees = entrees[-1]["donnees"]
        reponses = [
            (champ["libelle"], donnees[champ["cle"]].strip())
            for champ in champs
            if isinstance(donnees.get(champ["cle"]), str) and donnees[champ["cle"]].strip()
        ]

        if reponses:
            resultat.append({"nom": fiche.get("nom") or FICHE_SCHEMAS[master_id]["nom"], "reponses": reponses})

    return resultat


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


def _derniere_maj_blocs(page_id: str) -> str | None:
    # Date de la derniere modification du contenu (pas des proprietes : la
    # validation de la fiche ne doit pas compter comme une mise a jour).
    try:
        dates = [b.get("last_edited_time") for b in _list_children(page_id)]
    except RuntimeError:
        return None

    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _segments_recurrents(master_id: str, schema: dict) -> list[dict] | None:
    # Fiche de suivi (plan de la semaine, bilan hebdo) : le modele Notion
    # pose les memes questions que le formulaire, dans le meme ordre. On
    # place donc les champs du formulaire directement sous chaque question,
    # au lieu d'afficher les questions en texte fige puis de les reposer plus
    # bas. Les champs date (ex. "Semaine du") restent dans le bloc
    # d'enregistrement. Si le modele et le formulaire ne correspondent pas
    # exactement (tableau, cases a cocher...), on garde l'affichage classique.
    try:
        segments = _segments_master_cache(master_id)
    except Exception:
        return None

    questions = [s for s in segments if s["type"] == "champ"]
    a_placer = [
        c for c in sorted(schema["champs"], key=lambda c: c.get("ordre", 0)) if c["type"] != "date"
    ]

    if not questions or len(questions) != len(a_placer):
        return None

    for question, champ in zip(questions, a_placer):
        if question["champ"]["type"] == "case":
            return None

        if (question["champ"]["type"] == "choix") != (champ["type"] == "choix"):
            return None

    restants = iter(a_placer)
    resultat = []

    for segment in segments:
        if segment["type"] == "champ":
            champ = next(restants)
            resultat.append({
                "type": "champ",
                "champ": {**champ, "libelle_affiche": segment["champ"]["libelle"]},
            })
        else:
            resultat.append(segment)

    return resultat


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
    mis_a_jour = None

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
            # Contenu ecrit par le coach : rien n'y est a remplir par le
            # client (sinon sa reponse enregistree masquerait les mises a
            # jour du coach).
            segments = _page_segments(fiche_client_id, questions_libres=False)
            mis_a_jour = _derniere_maj_blocs(fiche_client_id)
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

            secours = _ATELIER_FICHE0_TEXTE

            if master_id == _NUMERO_TO_MASTER_ID["0"]:
                try:
                    client_props = _get_page(client_page_id).get("properties", {})
                    parcours = _prop_value(_prop(client_props, "Parcours"))

                    if _est_parcours_atelier(parcours):
                        source_id = _ATELIER_FICHE0_TEXTE_PAGE_ID
                    elif _est_parcours_autonome(parcours):
                        # Pas encore de page Notion dediee : texte de secours.
                        source_id = _AUTONOME_FICHE0_TEXTE_PAGE_ID or None
                        secours = _AUTONOME_FICHE0_TEXTE
                except Exception:
                    source_id = master_id

            try:
                if source_id is None:
                    raise LookupError("Page de bienvenue Autonome non configuree")
                segments = _segments_master_cache(source_id)
            except Exception:
                if source_id == master_id:
                    raise
                segments = [{"type": "texte", "texte": ligne} for ligne in secours]

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

    if mis_a_jour:
        result["mis_a_jour"] = mis_a_jour

    result["retour_ia_actif"] = master_id not in _FICHES_SANS_RETOUR_IA
    result["entrainement"] = master_id in _FICHES_ENTRAINEMENT

    if mode == "unique":
        result["segments"] = segments
    else:
        segments_suivi = _segments_recurrents(master_id, schema)

        if segments_suivi is not None:
            result["segments"] = segments_suivi
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
        # Sans exclure l'entree "checklist" (etat des cases), la reponse
        # pouvait ecraser cette entree au lieu de la sienne.
        existing = _query_data_source(
            ENTREES_PORTAIL_DATA_SOURCE_ID,
            filter_={
                "and": [
                    {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
                    {"property": "Client", "relation": {"contains": client_page_id}},
                    {"property": "Nom", "title": {"does_not_contain": "checklist"}},
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

    return {
        "client_nom": dashboard["nom"],
        "client_email": (dashboard.get("identite") or {}).get("email"),
        "parcours": dashboard.get("parcours"),
    }


# --- Parcours adapte au diagnostic (demande de Rony du 22/10/2026) ---
# Une fois la fiche 8 terminee, ses scores (ceux valides par le coach en
# Coaching, ceux recalcules en Autonome) designent les zones a travailler en
# priorite. L'ordre de deblocage ne change pas : on signale seulement au
# client les fiches qui comptent le plus pour lui.
_FICHES_PAR_ZONE = {
    "Offre": [_NUMERO_TO_MASTER_ID[n] for n in ("9", "11", "10", "12")],
    "Visibilité": [_NUMERO_TO_MASTER_ID[n] for n in ("11", "12", "22", "20")],
    "Prospection": [_NUMERO_TO_MASTER_ID[n] for n in ("14", "15", "13", "17")],
    "Conversion": [_NUMERO_TO_MASTER_ID[n] for n in ("18", "16")],
    "Suivi commercial": [_NUMERO_TO_MASTER_ID[n] for n in ("19", "17")],
}
_POURQUOI_PAR_ZONE = {
    "Offre": "Tant qu'on ne comprend pas ce que tu vends en 10 secondes, prospecter plus ne servira pas.",
    "Visibilité": "On doit te trouver et se souvenir de toi avant même que tu prospectes.",
    "Prospection": "La régularité compte plus que le volume : un petit rythme tenu chaque semaine.",
    "Conversion": "Tes rendez-vous doivent se transformer en clients : trame et réponses aux objections.",
    "Suivi commercial": "Beaucoup de ventes se perdent faute de relance : chaque proposition se suit.",
}


def _scores_fiche8(fiche8_id: str) -> dict:
    # Lecture seule des lignes "Score de X : n / 3" de la fiche 8.
    libelle_vers_zone = {libelle.lower(): zone for zone, libelle in _FICHE8_LIBELLE_SCORE.items()}
    scores = {}

    for bloc in _list_children(fiche8_id):
        texte = _block_text(bloc)
        match = re.match(r"^\s*(.+?)\s*:\s*(\d)\s*/\s*3\b", texte)

        if match and match.group(1).lower() in libelle_vers_zone:
            scores[libelle_vers_zone[match.group(1).lower()]] = int(match.group(2))

    return scores


def _personnaliser_parcours(fiches: list[dict]) -> dict | None:
    """Marque les fiches liees aux zones faibles du diagnostic.

    Zones prioritaires : les 3 plus faibles sous 3/3 (a egalite, l'ordre des
    zones). Zones fortes : 3/3. Ajoute a chaque fiche concernee
    fiche["priorite"] = {"type": "prioritaire" | "point_fort", "zone": ...}.
    None tant que la fiche 8 n'est pas terminee ou illisible.
    """
    fiche8 = next((f for f in fiches if f.get("master_id") == _DIAGNOSTIC_FICHE8_MASTER_ID), None)

    if not fiche8 or fiche8.get("etat") != "Terminé":
        return None

    try:
        scores = _scores_fiche8(fiche8["id"])
    except Exception as error:
        logger.warning("Scores de la fiche 8 illisibles (%s) : parcours standard.", error)
        return None

    if len(scores) != len(_DIAGNOSTIC_ZONES):
        return None

    diagnostic = dict(scores)
    reel = None
    fiche_bilan = next((f for f in fiches if f.get("master_id") == _BILAN_HEBDO_MASTER_ID), None)

    if fiche_bilan and "Bloqué" not in str(fiche_bilan.get("acces") or ""):
        try:
            reel = _scores_reels(fiche_bilan["id"])
        except Exception as error:
            logger.warning("Bilans hebdomadaires illisibles (%s) : priorites du diagnostic.", error)

    if reel:
        scores.update(reel["scores"])

    ordre = [zone["zone"] for zone in _DIAGNOSTIC_ZONES]
    faibles = sorted((z for z in ordre if scores[z] < 3), key=lambda z: (scores[z], ordre.index(z)))[:3]
    fortes = [z for z in ordre if scores[z] == 3]
    par_id = {f.get("master_id"): f for f in fiches}

    for zone in reversed(faibles):
        for master_id in _FICHES_PAR_ZONE[zone]:
            if master_id in par_id:
                par_id[master_id]["priorite"] = {"type": "prioritaire", "zone": zone}

    for zone in fortes:
        for master_id in _FICHES_PAR_ZONE[zone]:
            if master_id in par_id and "priorite" not in par_id[master_id]:
                par_id[master_id]["priorite"] = {"type": "point_fort", "zone": zone}

    constats = (reel or {}).get("constats", {})

    return {
        "scores": scores,
        "scores_diagnostic": diagnostic,
        "total": sum(diagnostic.values()),
        "total_actuel": sum(scores.values()),
        "chiffres": (reel or {}).get("chiffres"),
        "zones_prioritaires": [
            {
                "zone": zone,
                "score": scores[zone],
                "source": "chiffres" if zone in constats else "diagnostic",
                "constat": constats.get(zone),
                "pourquoi": _POURQUOI_PAR_ZONE[zone],
                "fiches": [par_id[m]["id"] for m in _FICHES_PAR_ZONE[zone] if m in par_id],
            }
            for zone in faibles
        ],
        "zones_fortes": fortes,
    }


# --- Diagnostic vivant (decision de Rony du 22/10/2026) ---
# Des que le client a rempli au moins 2 bilans hebdomadaires sur les 4
# dernieres semaines, ses vrais chiffres remplacent les reponses du
# diagnostic de depart pour 3 zones : Prospection (contacts par semaine),
# Conversion (ventes / rendez-vous) et Suivi commercial (regularite des
# bilans). Offre et Visibilite gardent le score du diagnostic. Seuils de
# travail, a ajuster avec l'experience.
_FENETRE_REELLE_JOURS = 28


def _nombre(valeur) -> float:
    try:
        return float(str(valeur).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def _scores_reels(fiche_bilan_id: str, maintenant: datetime | None = None) -> dict | None:
    maintenant = maintenant or datetime.now(timezone.utc)
    champs = FICHE_SCHEMAS[_BILAN_HEBDO_MASTER_ID]["champs"]
    pages = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Fiche Client", "relation": {"contains": fiche_bilan_id}},
    )
    semaines = {}

    for page in pages:
        entree = _parse_entry(page, champs)
        donnees = entree["donnees"]
        quand = donnees.get("semaine_du") or entree.get("date")
        jours = _jours_depuis_iso(quand, maintenant)

        if jours is None or jours < 0 or jours >= _FENETRE_REELLE_JOURS:
            continue

        # Une seule ligne par semaine : la derniere saisie l'emporte.
        semaines[str(quand)[:10]] = donnees

    n = len(semaines)

    if n < 2:
        return None

    total = {cle: sum(_nombre(d.get(cle)) for d in semaines.values())
             for cle in ("nb_contacts_tentes", "nb_rdv_obtenus", "nb_ventes_conclues")}
    contacts_semaine = total["nb_contacts_tentes"] / n
    scores = {}
    constats = {}

    prospection = 3 if contacts_semaine >= 10 else 2 if contacts_semaine >= 5 else 1 if contacts_semaine > 0 else 0
    scores["Prospection"] = min(prospection, 2) if n < 3 else prospection
    constats["Prospection"] = f"{contacts_semaine:.0f} contacts par semaine en moyenne sur tes {n} derniers bilans."

    if total["nb_rdv_obtenus"] > 0:
        taux = total["nb_ventes_conclues"] / total["nb_rdv_obtenus"]
        scores["Conversion"] = 3 if taux >= 0.3 else 2 if taux >= 0.15 else 1 if taux > 0 else 0
        constats["Conversion"] = (
            f"{total['nb_ventes_conclues']:.0f} vente(s) pour {total['nb_rdv_obtenus']:.0f} rendez-vous sur {n} semaines."
        )

    scores["Suivi commercial"] = 3 if n >= 4 else 2 if n == 3 else 1
    constats["Suivi commercial"] = f"{n} bilan(s) hebdomadaire(s) rempli(s) sur les 4 dernières semaines."

    return {
        "scores": scores,
        "constats": constats,
        "chiffres": {
            "semaines": n,
            "contacts": total["nb_contacts_tentes"],
            "rdv": total["nb_rdv_obtenus"],
            "ventes": total["nb_ventes_conclues"],
        },
    }


# --- Report des bilans hebdomadaires dans les KPI (decision de Rony du 25/10/2026) ---
# La fiche 0 promet "Tes chiffres se reportent tout seuls dans ton Tableau de
# bord" : a chaque bilan hebdomadaire enregistre, les RDV et les ventes de la
# periode (J0-J30, J30-J60, J60-J90, d'apres "Semaine du") sont additionnes et
# ecrits dans Valeur J30 / J60 / J90 des KPI "RDV" et "Nouveaux clients". Une
# periode sans bilan garde la valeur saisie a la main. Les contacts tentes ne
# sont pas des leads : le KPI "Leads" reste saisi par le client.
_KPI_DEPUIS_BILAN = {
    "nb_rdv_obtenus": {"nom": "RDV", "categorie": "Acquisition"},
    "nb_ventes_conclues": {"nom": "Nouveaux clients", "categorie": "Conversion"},
}
# Un bilan saisi un peu apres J90 compte encore pour la derniere periode.
_BILAN_JOUR_MAX = 97


def _historique_bilans(fiche_bilan_id: str) -> list[dict]:
    """Bilans hebdomadaires du client, une ligne par semaine (la derniere
    saisie l'emporte), du plus ancien au plus recent."""
    champs = FICHE_SCHEMAS[_BILAN_HEBDO_MASTER_ID]["champs"]
    pages = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Fiche Client", "relation": {"contains": fiche_bilan_id}},
    )
    pages = sorted(pages, key=lambda page: page.get("created_time") or "")
    semaines = {}

    for page in pages:
        if "checklist" in str(_prop_value(_prop(page.get("properties", {}), "Nom")) or ""):
            continue

        entree = _parse_entry(page, champs)
        donnees = entree["donnees"]
        quand = str(donnees.get("semaine_du") or entree.get("date") or "")[:10]

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", quand):
            continue

        semaines[quand] = {
            "semaine_du": quand,
            "contacts": _nombre(donnees.get("nb_contacts_tentes")),
            "rdv": _nombre(donnees.get("nb_rdv_obtenus")),
            "propositions": _nombre(donnees.get("nb_propositions_envoyees")),
            "ventes": _nombre(donnees.get("nb_ventes_conclues")),
            "ce_qui_a_marche": donnees.get("ce_qui_a_le_mieux_fonctionne") or "",
            "difficulte": donnees.get("difficulte_principale") or "",
        }

    return [semaines[cle] for cle in sorted(semaines)]


def serie_de_semaines(semaines_du: list[str], aujourd_hui=None) -> int:
    """Semaines d'affilee avec un bilan, jusqu'a cette semaine ou la
    precedente (le bilan du vendredi peut ne pas etre encore fait)."""
    aujourd_hui = aujourd_hui or datetime.now(timezone.utc).date()
    lundis = set()

    for valeur in semaines_du:
        try:
            jour = datetime.fromisoformat(str(valeur)[:10]).date()
        except ValueError:
            continue
        lundis.add(jour - timedelta(days=jour.weekday()))

    lundi = aujourd_hui - timedelta(days=aujourd_hui.weekday())

    if lundi not in lundis:
        lundi -= timedelta(days=7)

    serie = 0

    while lundi in lundis:
        serie += 1
        lundi -= timedelta(days=7)

    return serie


def _regularite_bilans(fiches: list[dict]) -> dict | None:
    # Serie de regularite (lot 3, 25/10/2026) : affichee sur le tableau de
    # bord. None tant que le bilan hebdomadaire n'est pas ouvert.
    fiche_bilan = next((f for f in fiches if f.get("master_id") == _BILAN_HEBDO_MASTER_ID), None)

    if not fiche_bilan or "Bloqué" in str(fiche_bilan.get("acces") or ""):
        return None

    try:
        historique = _historique_bilans(fiche_bilan["id"])
    except Exception as error:
        logger.warning("Regularite des bilans illisible (%s)", error)
        return None

    return {
        "serie": serie_de_semaines([s["semaine_du"] for s in historique]),
        "semaines": len(historique),
        "derniere": historique[-1]["semaine_du"] if historique else None,
    }


def _periode_kpi(jour: int) -> str:
    return "valeur_j30" if jour < 30 else "valeur_j60" if jour < 60 else "valeur_j90"


def totaux_bilans_par_periode(historique: list[dict], date_demarrage) -> dict:
    """{"valeur_j30": {"nb_rdv_obtenus": 4.0, ...}, ...} : seules les periodes
    ayant au moins un bilan apparaissent."""
    try:
        debut = datetime.fromisoformat(str(date_demarrage)[:10]).date()
    except (TypeError, ValueError):
        return {}

    totaux = {}
    correspondance = {"nb_rdv_obtenus": "rdv", "nb_ventes_conclues": "ventes"}

    for semaine in historique:
        jour = (datetime.fromisoformat(semaine["semaine_du"]).date() - debut).days

        if jour > _BILAN_JOUR_MAX:
            continue

        periode = totaux.setdefault(_periode_kpi(max(jour, 0)), {cle: 0.0 for cle in _KPI_DEPUIS_BILAN})

        for cle, champ in correspondance.items():
            periode[cle] += semaine[champ]

    return totaux


def reporter_bilans_dans_kpi(client_page_id: str, fiche_client_id: str) -> bool:
    """Apres un bilan hebdomadaire : met a jour les KPI RDV et Nouveaux
    clients. False si la fiche n'est pas le bilan ou sans date de demarrage."""
    _schema, _nom, master_id = _fiche_schema_for(fiche_client_id)

    if master_id != _BILAN_HEBDO_MASTER_ID:
        return False

    props = _get_page(client_page_id).get("properties", {})
    date_demarrage = _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage"))
    totaux = totaux_bilans_par_periode(_historique_bilans(fiche_client_id), date_demarrage)

    if not totaux:
        return False

    kpis = {(kpi.get("nom") or "").strip().lower(): kpi for kpi in _client_kpi(client_page_id)}

    for cle, definition in _KPI_DEPUIS_BILAN.items():
        valeurs = {periode: total[cle] for periode, total in totaux.items()}
        kpi = kpis.get(definition["nom"].lower())

        if kpi:
            modifies = {champ: v for champ, v in valeurs.items() if _nombre(kpi.get(champ)) != v or kpi.get(champ) is None}
            if modifies:
                update_kpi(kpi["id"], modifies, kpi.get("etat"))
            continue

        properties = {
            "Nom": {"title": [{"text": {"content": definition["nom"]}}]},
            "Client": {"relation": [{"id": client_page_id}]},
            "Catégorie": {"select": {"name": definition["categorie"]}},
            "État": {"status": {"name": "En cours"}},
        }
        properties.update({KPI_CHAMPS_SAISISSABLES[champ]: {"number": v} for champ, v in valeurs.items()})
        _create_page(KPI_DATA_SOURCE_ID, properties)

    _cache_clear("dashboard:")
    return True


# --- Retours IA personnalises (decision de Rony du 22/10/2026) ---
# Apres chaque enregistrement, l'IA commente les reponses du client, l'encourage
# et lui explique l'interet de la fiche pour SES zones faibles. Circuit :
# l'enregistrement passe l'entree a "A generer", le workflow n8n (Gemini)
# recupere les prompts via /automation/retours-ia/a-generer puis renvoie le
# texte. Autonome : publie tout de suite. Coaching : "A relire", visible par le
# client apres _DELAI_RELECTURE_RETOUR_IA sauf si Rony le passe a "Bloque".
_DELAI_RELECTURE_RETOUR_IA_H = 12
_FICHES_SANS_RETOUR_IA = _DIAGNOSTIC_ZONE_IDS | {_DIAGNOSTIC_FICHE8_MASTER_ID} | {
    master_id for master_id, schema in FICHE_SCHEMAS.items() if schema["nom"].startswith("Bonus")
}

# Fiches qui proposent l'entrainement aux objections : trame d'entretien
# (interne 18) et gestion des objections (interne 16).
_FICHES_ENTRAINEMENT = {_NUMERO_TO_MASTER_ID["18"], _NUMERO_TO_MASTER_ID["16"]}

_RETOUR_IA_SYSTEME = ia_service.avec_style("""Tu es Idris, l'assistant IA du programme eVolution 2.0 de RL-eVolution (Rony), accompagnement commercial des indépendants et TPE des Antilles-Guyane. Un client vient d'enregistrer une fiche de travail. Tu lui écris un retour personnel.

RÈGLES
- Français, tutoiement, ton chaleureux, direct et concret, sans jargon (pas de "funnel", "mindset", "scaler").
- Appuie-toi UNIQUEMENT sur les données fournies. N'invente aucun chiffre, aucun fait, aucun résultat. Ne promets ni chiffre d'affaires ni aide publique.
- Cite ou reprends ses propres mots quand c'est utile, pour qu'il sente que tu as lu SES réponses.
- 90 à 150 mots, 3 courts paragraphes, pas de titre, pas de markdown, pas de signature.

STRUCTURE
1. Ce que tu retiens de ses réponses : un point fort précis, et si une réponse est vague ou vide, dis-le simplement et propose comment la préciser.
2. Pourquoi cette fiche compte pour lui : relie-la à son diagnostic (zone prioritaire, score) et à son objectif 90 jours s'il est fourni.
3. Un encouragement sincère et UNE action concrète pour les 7 prochains jours.""")


# Bilan hebdomadaire (25/10/2026) : Idris compare les semaines au lieu de
# commenter la seule semaine enregistree.
_RETOUR_IA_BILAN_SYSTEME = ia_service.avec_style("""Tu es Idris, l'assistant IA du programme eVolution 2.0 de RL-eVolution (Rony), accompagnement commercial des indépendants et TPE des Antilles-Guyane. Un client vient d'enregistrer son bilan hebdomadaire de prospection. Tu lui écris l'analyse de sa semaine.

RÈGLES
- Français, tutoiement, ton chaleureux, direct et concret, sans jargon.
- Appuie-toi UNIQUEMENT sur les chiffres et réponses fournis. Ne calcule que ce qui est fourni (les taux sont déjà calculés), n'invente aucun chiffre, ne promets aucun résultat.
- 90 à 150 mots, 3 courts paragraphes, pas de titre, pas de markdown, pas de signature.

STRUCTURE
1. La tendance : compare cette semaine aux précédentes (contacts, RDV, ventes). S'il n'y a qu'une semaine, dis que c'est la base de départ et que la comparaison viendra la semaine prochaine.
2. Le point qui coince le plus dans l'enchaînement contacts → RDV → ventes, relié à sa difficulté et à ce qui a marché.
3. UNE action précise et chiffrée pour la semaine prochaine (par exemple "5 relances de propositions d'ici mercredi"), puis un encouragement sincère.""")


def _lignes_historique_bilans(historique: list[dict]) -> list[str]:
    lignes = ["Ses bilans (du plus ancien au plus récent, 5 dernières semaines au plus) :"]

    for semaine in historique[-5:]:
        taux_rdv = f"{semaine['rdv'] / semaine['contacts']:.0%}" if semaine["contacts"] else "n/a"
        taux_vente = f"{semaine['ventes'] / semaine['rdv']:.0%}" if semaine["rdv"] else "n/a"
        lignes.append(
            f"- Semaine du {semaine['semaine_du']} : {semaine['contacts']:.0f} contacts, {semaine['rdv']:.0f} RDV, "
            f"{semaine['propositions']:.0f} propositions, {semaine['ventes']:.0f} ventes "
            f"(contacts → RDV {taux_rdv}, RDV → ventes {taux_vente})"
        )

    return lignes


def _retour_ia_visible(props: dict) -> dict | None:
    # Ce que le client peut voir du retour IA de cette entree.
    statut = _prop_value(_prop(props, "Retour IA statut"))
    texte = (_prop_value(_prop(props, "Retour IA")) or "").strip()
    date = _prop_value(_prop(props, "Retour IA date"))

    if statut == "À générer":
        return {"statut": "en_cours"}

    if not texte or statut not in ("Publié", "À relire"):
        return None

    if statut == "À relire":
        try:
            ecrit = datetime.fromisoformat(str(date).replace("Z", "+00:00"))
        except ValueError:
            return None

        if ecrit.tzinfo is None:
            ecrit = ecrit.replace(tzinfo=timezone.utc)

        if (datetime.now(timezone.utc) - ecrit).total_seconds() < _DELAI_RELECTURE_RETOUR_IA_H * 3600:
            return {"statut": "relecture"}

    return {"statut": "publie", "texte": texte, "date": date}


def demander_retour_ia(fiche_client_id: str, entry_id: str | None) -> bool:
    """Apres un enregistrement : met l'entree en file pour le retour IA.

    Rien pour les checklists, le diagnostic (3 a 8 : la fiche 8 en tient lieu)
    et le Bonus aides publiques.
    """
    if not entry_id:
        return False

    _schema, _nom, master_id = _fiche_schema_for(fiche_client_id)

    if master_id in _FICHES_SANS_RETOUR_IA:
        return False

    _update_page(entry_id, {"Retour IA statut": {"select": {"name": "À générer"}}})
    return True


def _prompt_retour_ia(entree: dict) -> dict | None:
    props = entree.get("properties", {})
    client_ids = _prop_value(_prop(props, "Client")) or []
    fiche_ids = _prop_value(_prop(props, "Fiche Client")) or []

    if not client_ids or not fiche_ids:
        return None

    try:
        donnees = json.loads(_prop_value(_prop(props, "Données (JSON)")) or "{}")
    except json.JSONDecodeError:
        donnees = {}

    reponses = {
        question: valeur for question, valeur in donnees.items()
        if not str(question).startswith("__") and str(valeur).strip()
    }
    dashboard = get_client_dashboard(client_ids[0])
    fiche = next((f for f in dashboard["fiches"] if f["id"].replace("-", "") == fiche_ids[0].replace("-", "")), None)

    if not fiche:
        return None

    perso = dashboard.get("personnalisation") or {}
    priorite = fiche.get("priorite") or {}
    prenom = (dashboard.get("nom") or "").split(" ")[0]
    lignes = [
        f"Prénom : {prenom}" if prenom else None,
        f"Formule : {'eVolution Autonome' if _est_parcours_autonome(dashboard.get('parcours')) else 'Coaching 90 jours'}",
        f"Objectif 90 jours : {dashboard['objectif_90j']}" if dashboard.get("objectif_90j") else None,
        f"Fiche enregistrée : {fiche['nom'].split(' - ', 1)[-1]}",
    ]

    if perso.get("scores"):
        lignes.append("Scores actuels : " + ", ".join(f"{zone} {score}/3" for zone, score in perso["scores"].items()) + f" (total {perso.get('total_actuel', perso['total'])}/15)")
        lignes.append("Zones prioritaires : " + (", ".join(z["zone"] for z in perso["zones_prioritaires"]) or "aucune"))
        lignes.extend(f"Ses chiffres réels ({z['zone']}) : {z['constat']}" for z in perso["zones_prioritaires"] if z.get("constat"))

    if priorite.get("type") == "prioritaire":
        lignes.append(f"Cette fiche travaille sa zone prioritaire : {priorite['zone']}. {_POURQUOI_PAR_ZONE[priorite['zone']]}")
    elif priorite.get("type") == "point_fort":
        lignes.append(f"Cette fiche touche un de ses points forts : {priorite['zone']}. Encourage-le à la boucler vite pour se concentrer sur ses priorités.")

    systeme = _RETOUR_IA_SYSTEME

    if fiche.get("master_id") == _BILAN_HEBDO_MASTER_ID:
        systeme = _RETOUR_IA_BILAN_SYSTEME

        try:
            historique = _historique_bilans(fiche["id"])
        except Exception as error:
            logger.warning("Historique des bilans illisible (%s) : analyse de la seule semaine.", error)
            historique = []

        if historique:
            lignes.append("")
            lignes.extend(_lignes_historique_bilans(historique))

    lignes.append("")
    lignes.append("Ses réponses :")
    lignes.extend(f"- {question} {valeur}" for question, valeur in reponses.items())

    if not reponses:
        lignes.append("(aucune réponse remplie)")

    return {
        "entry_id": entree["id"],
        "client": dashboard.get("nom"),
        "fiche": fiche["nom"].split(" - ", 1)[-1],
        "autonome": _est_parcours_autonome(dashboard.get("parcours")),
        "systeme": systeme,
        "message": "\n".join(ligne for ligne in lignes if ligne is not None),
    }


def retours_ia_a_generer(limite: int = 10) -> list[dict]:
    entrees = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Retour IA statut", "select": {"equals": "À générer"}},
    )
    prompts = []

    for entree in entrees[:limite]:
        try:
            prompt = _prompt_retour_ia(entree)
        except Exception as error:
            logger.warning("Retour IA %s : prompt impossible (%s)", entree.get("id"), error)
            prompt = None

        if prompt:
            prompts.append(prompt)
        else:
            _update_page(entree["id"], {"Retour IA statut": {"select": None}})

    return prompts


def enregistrer_retour_ia(entry_id: str, texte: str, autonome: bool) -> str:
    texte = ia_service.humaniser((texte or "").strip())

    if not texte:
        raise ValueError("Retour IA vide")

    statut = "Publié" if autonome else "À relire"
    _update_page(entry_id, {
        "Retour IA": {"rich_text": [{"text": {"content": texte[i:i + 2000]}} for i in range(0, min(len(texte), 4000), 2000)]},
        "Retour IA statut": {"select": {"name": statut}},
        "Retour IA date": {"date": {"start": datetime.now(timezone.utc).isoformat(timespec="seconds")}},
    })
    return statut


def generer_retour_ia_immediat(entry_id: str) -> bool:
    """Parcours Autonome : redige et publie le retour tout de suite, sans
    attendre le passage du workflow n8n (toutes les 2 min). En Coaching, ou
    si Gemini echoue, l'entree reste "À générer" et n8n s'en charge (avec
    l'alerte Telegram de relecture pour Rony)."""
    if not ia_service.enabled():
        return False

    prompt = _prompt_retour_ia(_get_page(entry_id))

    if not prompt or not prompt["autonome"]:
        return False

    texte = ia_service.generer(
        prompt["systeme"], [{"role": "user", "texte": prompt["message"]}], temperature=0.5, max_tokens=800
    )
    enregistrer_retour_ia(entry_id, texte, autonome=True)
    return True


# --- Relances intelligentes (decision de Rony du 22/10/2026) ---
# Chaque jour, le workflow n8n demande les clients a relancer : aucune saisie
# depuis _RELANCE_INACTIF_JOURS jours, ou bilan hebdomadaire oublie une fois
# la routine de prospection ouverte (J31). Une relance au plus tous les
# _RELANCE_INTERVALLE_JOURS jours par client. L'IA redige un e-mail court et
# personnel ; n8n l'envoie puis appelle marquer_relance_envoyee().
_RELANCE_INACTIF_JOURS = 7
_RELANCE_INTERVALLE_JOURS = 7
_RELANCE_BILAN_DES_JOUR = 31
_BILAN_HEBDO_MASTER_ID = _NUMERO_TO_MASTER_ID["17"]

_RELANCE_SYSTEME = ia_service.avec_style("""Tu écris, au nom de Rony (RL-eVolution, programme eVolution 2.0), un court e-mail de relance à un client indépendant ou TPE des Antilles-Guyane qui a un peu décroché de son parcours.

RÈGLES
- Français, tutoiement, ton chaleureux, simple et motivant, jamais culpabilisant ni insistant.
- N'utilise QUE les données fournies, n'invente aucun chiffre ni fait.
- 60 à 110 mots, pas d'objet, pas de markdown, pas de signature (elle est ajoutée ensuite).
- Commence par son prénom.
- Rappelle-lui pourquoi il fait ce parcours (son objectif s'il est fourni), propose UNE seule petite action concrète à faire aujourd'hui en 15 minutes (la fiche indiquée), et termine par une phrase d'encouragement.
- Si c'est un bilan hebdomadaire oublié : explique en une phrase que 10 minutes de bilan chaque semaine montrent ce qui marche et ce qui coince.""")


def _jours_depuis_iso(valeur, maintenant: datetime) -> int | None:
    if not valeur:
        return None

    try:
        date = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None

    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)

    return (maintenant - date).days


def _relance_du_client(row: dict, maintenant: datetime) -> dict | None:
    props = row.get("properties", {})

    if _prop_value(_prop(props, "État")) != "En cours" or _est_parcours_atelier(_prop_value(_prop(props, "Parcours"))):
        return None

    email = _prop_value(_prop(props, "E-mail"))
    debut = _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage"))
    jour = _jours_depuis_iso(debut, maintenant)

    if not email or jour is None or jour < 2 or jour > 95:
        return None

    derniere = _jours_depuis_iso(_prop_value(_prop(props, "Dernière relance")), maintenant)

    if derniere is not None and derniere < _RELANCE_INTERVALLE_JOURS:
        return None

    entrees = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Client", "relation": {"contains": row["id"]}},
    )
    activite = [_jours_depuis_iso(e.get("last_edited_time"), maintenant) for e in entrees]
    activite = [j for j in activite if j is not None]
    inactif = min(activite) if activite else jour

    dashboard = get_client_dashboard(row["id"])
    fiche_bilan = next((f for f in dashboard["fiches"] if f.get("master_id") == _BILAN_HEBDO_MASTER_ID), None)

    if inactif >= _RELANCE_INACTIF_JOURS:
        type_relance = "inactif"
    elif jour >= _RELANCE_BILAN_DES_JOUR and fiche_bilan:
        bilans = [
            _jours_depuis_iso(e.get("last_edited_time"), maintenant)
            for e in entrees
            if fiche_bilan["id"].replace("-", "") in [r.replace("-", "") for r in (_prop_value(_prop(e.get("properties", {}), "Fiche Client")) or [])]
        ]
        bilans = [j for j in bilans if j is not None]

        if bilans and min(bilans) < 7:
            return None

        type_relance = "bilan"
    else:
        return None

    ouvertes = [f for f in dashboard["fiches"] if f.get("etat") != "Terminé" and "Bloqué" not in str(f.get("acces") or "")]
    fiche = fiche_bilan if type_relance == "bilan" else next(
        (f for f in ouvertes if (f.get("priorite") or {}).get("type") == "prioritaire"),
        ouvertes[0] if ouvertes else None,
    )
    perso = dashboard.get("personnalisation") or {}
    prenom = (dashboard.get("nom") or "").split(" ")[0]
    lignes = [
        f"Prénom : {prenom}",
        f"Jour du parcours : J{jour} sur 90",
        f"Objectif 90 jours : {dashboard['objectif_90j']}" if dashboard.get("objectif_90j") else None,
        f"Jours sans activité sur son espace : {inactif}" if type_relance == "inactif" else "Bilan hebdomadaire de prospection non rempli depuis plus de 7 jours",
        f"Fiches terminées : {sum(1 for f in dashboard['fiches'] if f.get('etat') == 'Terminé')} sur {len(dashboard['fiches'])}",
        "Zones prioritaires de son diagnostic : " + ", ".join(z["zone"] for z in perso["zones_prioritaires"]) if perso.get("zones_prioritaires") else None,
        f"Fiche à faire aujourd'hui : {fiche['nom'].split(' - ', 1)[-1]}" if fiche else None,
    ]

    return {
        "client_page_id": row["id"],
        "email": email,
        "prenom": prenom,
        "client": dashboard.get("nom"),
        "type": type_relance,
        "objet": f"{prenom}, 15 minutes pour avancer aujourd'hui ?" if type_relance == "inactif" else f"{prenom}, ton bilan de la semaine t'attend",
        "systeme": _RELANCE_SYSTEME,
        "message": "\n".join(ligne for ligne in lignes if ligne),
    }


def relances_dues(maintenant: datetime | None = None) -> list[dict]:
    maintenant = maintenant or datetime.now(timezone.utc)
    relances = []

    for row in _query_data_source(CLIENTS_DATA_SOURCE_ID):
        try:
            relance = _relance_du_client(row, maintenant)
        except Exception as error:
            logger.warning("Relance %s impossible a evaluer (%s)", row.get("id"), error)
            relance = None

        if relance:
            relances.append(relance)

    return relances


def marquer_relance_envoyee(client_page_id: str) -> None:
    props = _get_page(client_page_id).get("properties", {})
    nombre = _prop_value(_prop(props, "Nb relances")) or 0
    _update_page(client_page_id, {
        "Dernière relance": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
        "Nb relances": {"number": nombre + 1},
    })


# --- Parcours Autonome : fiche 8 automatique (decision du 21/10/2026) ---
# Les numeros de fiche cites sont ceux AFFICHES (numerotation Notion du
# 07/10/2026), pas les numeros internes de _PARCOURS.
_RECOMMANDATION_AUTONOME = {
    "Offre": "Ta priorité des 30 prochains jours : rendre ton offre claire. Concentre-toi sur les fiches 9, 10 et 12, et sur le Module 1. Tant qu'on ne comprend pas ce que tu vends en 10 secondes, prospecter plus ne servira pas.",
    "Visibilité": "Ta priorité : qu'on te trouve et qu'on se souvienne de toi. Après la fiche 10, mets ta phrase de positionnement partout (profil WhatsApp, Facebook, fiche Google). Chaque semaine, demande une recommandation à un client content.",
    "Prospection": "Ta priorité : la régularité. Fixe un petit nombre de contacts par semaine que tu peux tenir, note-les dans la fiche 11 et fais tes fiches 15 et 16 chaque semaine. Mieux vaut 5 contacts chaque semaine que 30 une seule fois.",
    "Conversion": "Ta priorité : transformer tes rendez-vous en clients. Travaille la trame d'entretien (fiche 17) et tes réponses aux objections (fiche 18) avant ton prochain rendez-vous.",
    "Suivi commercial": "Ta priorité : ne plus laisser filer de devis. Note chaque proposition dans ta fiche 19 et relance à J+3 et J+7. Beaucoup de ventes se perdent faute de relance.",
}
_MENTION_FICHE8_AUTONOME = (
    "Ce résultat est calculé automatiquement à partir de tes réponses. Pour un diagnostic "
    "lu et commenté par Rony, avec 3 priorités sur mesure, découvre le Coaching 90 jours."
)


def _zone_la_plus_faible(rapport: dict) -> str | None:
    # A egalite, l'ordre des zones du rapport (ordre du parcours) departage.
    scores = [(z["zone"], z["score"]) for z in rapport.get("zones", []) if z.get("score") is not None]

    if not scores:
        return None

    return min(scores, key=lambda item: item[1])[0]


def remplir_fiche8_autonome(client_page_id: str) -> bool:
    """Parcours Autonome : remplit la fiche 8 avec les scores calcules, ajoute
    la recommandation de la zone la plus faible, puis valide la fiche.

    Renvoie False (sans rien ecrire) si le diagnostic n'est pas complet.
    """
    rapport = get_diagnostic_rapport(client_page_id)
    fiche8_id = (rapport.get("fiche_8") or {}).get("fiche_client_id")

    if not rapport.get("complet") or not fiche8_id:
        return False

    valeurs = {p["label"]: p["valeur"] for p in rapport.get("propositions", [])}
    updates = [
        {**champ, "valeur": valeurs[champ["label"]]}
        for champ in get_diagnostic_fiche8(fiche8_id)
        if champ["label"] in valeurs
    ]

    if updates:
        update_diagnostic_fiche8(updates)

    zone = _zone_la_plus_faible(rapport)

    def bloc(type_, *rich_text):
        return {"object": "block", "type": type_, type_: {"rich_text": list(rich_text)}}

    enfants = [
        {"object": "block", "type": "divider", "divider": {}},
        bloc("heading_3", _rt("\U0001F9ED TA PRIORITÉ DES 30 PROCHAINS JOURS")),
    ]

    if zone:
        enfants.append(bloc("paragraph", _rt(_RECOMMANDATION_AUTONOME[zone])))

    enfants.append(bloc("paragraph", _rt(_MENTION_FICHE8_AUTONOME, italique=True)))

    try:
        response = _http.patch(
            f"{NOTION_API_BASE}/blocks/{fiche8_id}/children",
            headers=_headers(),
            json={"children": enfants},
            timeout=20,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (fiche 8 autonome {fiche8_id}) : {error}") from error

    validate_fiche(fiche8_id)
    return True


def recalculer_fiche8_autonome(client_page_id: str, fiche_id: str) -> bool:
    """Parcours Autonome : le client a modifie une fiche de diagnostic alors
    que sa fiche 8 est deja remplie. On recalcule scores, priorites et
    recommandation, sinon la fiche 8 garde les resultats de ses premieres
    reponses. En Coaching, la fiche 8 appartient au coach : on n'y touche pas.
    """
    dashboard = get_client_dashboard(client_page_id)

    if not _est_parcours_autonome(dashboard.get("parcours")):
        return False

    fiche_id = fiche_id.replace("-", "")
    modifiee = next((f for f in dashboard["fiches"] if f["id"].replace("-", "") == fiche_id), None)
    fiche8 = next((f for f in dashboard["fiches"] if f.get("master_id") == _DIAGNOSTIC_FICHE8_MASTER_ID), None)

    if not modifiee or modifiee.get("master_id") not in _DIAGNOSTIC_ZONE_IDS:
        return False

    if not fiche8 or fiche8.get("etat") != "Terminé":
        # Pas encore remplie : remplir_fiche8_autonome s'en chargera.
        return False

    rapport = get_diagnostic_rapport(client_page_id)

    if not rapport.get("complet"):
        return False

    valeurs = {p["label"]: p["valeur"] for p in rapport.get("propositions", [])}
    updates = [
        {**champ, "valeur": valeurs[champ["label"]]}
        for champ in get_diagnostic_fiche8(fiche8["id"])
        if champ["label"] in valeurs and champ["valeur"] != valeurs[champ["label"]]
    ]

    if updates:
        update_diagnostic_fiche8(updates)

    zone = _zone_la_plus_faible(rapport)

    if zone:
        _maj_recommandation_autonome(fiche8["id"], _RECOMMANDATION_AUTONOME[zone])

    return True


def _maj_recommandation_autonome(fiche8_id: str, texte: str) -> None:
    # Le paragraphe qui suit le titre "TA PRIORITE DES 30 PROCHAINS JOURS".
    blocs = _list_children(fiche8_id)

    for index, bloc in enumerate(blocs):
        if bloc.get("type") == "heading_3" and "30 PROCHAINS JOURS" in _block_text(bloc):
            suivant = blocs[index + 1] if index + 1 < len(blocs) else None

            if not suivant or suivant.get("type") != "paragraph" or _block_text(suivant) == texte:
                return

            if _block_text(suivant) == _MENTION_FICHE8_AUTONOME:
                return

            try:
                response = _http.patch(
                    f"{NOTION_API_BASE}/blocks/{suivant['id']}",
                    headers=_headers(),
                    json={"paragraph": {"rich_text": [_rt(texte)]}},
                    timeout=15,
                )
                response.raise_for_status()
            except requests.RequestException as error:
                raise RuntimeError(f"Erreur Notion (recommandation fiche 8 {fiche8_id}) : {error}") from error

            return


# --- Parcours Autonome : syntheses mensuelles redigees par n8n ---
SYNTHESES_DATA_SOURCE_ID = os.getenv(
    "NOTION_SYNTHESES_DATA_SOURCE_ID", "9f11e9fa-34a4-48fb-9f27-658a4ad3bf83"
)
_SYNTHESE_STATUTS = {"À relire", "Envoyée", "Bloquée"}
_SYNTHESE_AXES = {"encouragement", "a_faire", "reprise"}
# Dernieres entrees lues pour la synthese : bilan hebdomadaire de prospection
# (fiche affichee 16) et suivi de closing (fiche affichee 19).
_SYNTHESE_FICHES_BILAN = ["39ffaffd875880708581d60c234aab45", "39ffaffd8758805398f7dc22d26b9626"]
_SYNTHESE_SEUIL_ENCOURAGEMENT = 3


def _syntheses_brutes(client_page_id: str) -> list[dict]:
    rows = _query_data_source(
        SYNTHESES_DATA_SOURCE_ID,
        filter_={"property": "Client", "relation": {"contains": client_page_id}},
    )
    syntheses = []

    for row in rows:
        props = row.get("properties", {})
        date = _prop_value(_prop(props, "Date"))
        syntheses.append({
            "id": row["id"],
            "mois": _prop_value(_prop(props, "Mois")),
            "date": date.get("start") if isinstance(date, dict) else date,
            "axe": _prop_value(_prop(props, "Axe")),
            "statut": _prop_value(_prop(props, "Statut")),
            "fiches_terminees": _prop_value(_prop(props, "Fiches terminées")),
            "texte": _prop_value(_prop(props, "Texte")) or "",
        })

    syntheses.sort(key=lambda item: item.get("mois") or 0, reverse=True)
    return syntheses


# Reponses du client mises en avant sur sa derniere synthese : ce qu'il a
# pose sur la periode (phrase d'accroche, cible). Fiches reperees par leur
# nom, la numerotation ayant change le 07/10.
_SYNTHESE_REPONSES_CLES = [
    ("Ta phrase d'accroche", "PHRASE DE POSITIONNEMENT", 2),
    ("Ta cible prioritaire", "CIBLE PRIORITAIRE", 2),
]


def _reponses_fiche(fiche: dict, client_page_id: str, maximum: int) -> list[dict]:
    detail = get_fiche(fiche["id"], client_page_id)
    entrees = [e for e in detail.get("entrees") or [] if e.get("id")]

    if not entrees:
        return []

    donnees = entrees[-1].get("donnees") or {}
    reponses = []

    for champ in detail.get("champs") or []:
        valeur = donnees.get(champ.get("cle"))

        if isinstance(valeur, str) and valeur.strip():
            reponses.append({"libelle": (champ.get("libelle") or "").strip().rstrip(" :"), "valeur": valeur.strip()})

        if len(reponses) >= maximum:
            break

    return reponses


def _resultats_periode(fiches: list[dict], client_page_id: str) -> list[dict]:
    resultats = []

    for titre, mot_cle, maximum in _SYNTHESE_REPONSES_CLES:
        fiche = next((f for f in fiches if mot_cle in (f.get("nom") or "").upper()), None)

        if not fiche:
            continue

        try:
            reponses = _reponses_fiche(fiche, client_page_id, maximum)
        except Exception as error:
            logger.warning("Synthese : reponses %s illisibles (%s)", mot_cle, _resume_erreur(error))
            continue

        if reponses:
            resultats.append({"titre": titre, "reponses": reponses})

    return resultats


def syntheses_du_client(client_page_id: str, fiches: list[dict] | None = None) -> list[dict]:
    # Affichage portail : seulement les syntheses envoyees. Ne fait jamais
    # tomber le tableau de bord (base absente, non partagee, Notion en panne).
    try:
        syntheses = _syntheses_brutes(client_page_id)
    except Exception as error:
        logger.warning("Syntheses Autonome illisibles : %s", _resume_erreur(error))
        return []

    par_mois = {s.get("mois"): s for s in syntheses}
    affichees = [
        {
            **{k: s[k] for k in ("mois", "date", "axe", "texte")},
            **_realisation_synthese(s, par_mois.get((s.get("mois") or 0) - 1)),
        }
        for s in syntheses
        if s.get("statut") == "Envoyée"
    ]

    if affichees and fiches:
        # Etat actuel des reponses : n'a de sens que sur la synthese la plus
        # recente (les anciennes restent telles qu'envoyees).
        affichees[0]["resultats"] = _resultats_periode(fiches, client_page_id)

    return affichees


def _fiches_prevues(jour: int) -> int:
    # Fiches du parcours 90 jours dont le jour d'ouverture est atteint.
    return sum(1 for jour_fiche in _FICHE_JOUR.values() if jour_fiche <= jour)


def _realisation_synthese(synthese: dict, precedente: dict | None) -> dict:
    # Jauge du portail : fiches terminees au moment de la synthese, comparees
    # aux fiches ouvertes a ce stade du parcours (J30, J60, J90...).
    terminees = synthese.get("fiches_terminees")

    if terminees is None:
        return {}

    prevues = _fiches_prevues(30 * (synthese.get("mois") or 0))
    avant = (precedente or {}).get("fiches_terminees") or 0

    return {
        "fiches_terminees": terminees,
        "fiches_prevues": prevues,
        "fiches_total": len(_FICHE_JOUR),
        "fiches_du_mois": max(terminees - avant, 0),
    }


def _axe_synthese(nb_terminees: int, nb_precedent: int | None) -> str:
    nouvelles = nb_terminees - (nb_precedent or 0)

    if nouvelles <= 0:
        return "reprise"

    if nouvelles >= _SYNTHESE_SEUIL_ENCOURAGEMENT:
        return "encouragement"

    return "a_faire"


def _derniere_entree(fiche: dict | None, client_page_id: str) -> dict | None:
    if not fiche:
        return None

    try:
        entrees = get_fiche(fiche["id"], client_page_id).get("entrees") or []
    except Exception as error:
        logger.warning("Synthese : fiche %s illisible (%s)", fiche.get("master_id"), _resume_erreur(error))
        return None

    return entrees[-1].get("donnees") if entrees else None


def donnees_synthese_autonome(client_page_id: str, numero_mois: int, syntheses: list[dict] | None = None) -> dict:
    dashboard = get_client_dashboard(client_page_id)
    fiches = dashboard.get("fiches") or []
    terminees = [f.get("nom") for f in fiches if f.get("etat") == "Terminé"]
    en_cours = [f.get("nom") for f in fiches if f.get("acces") == "🚀 En cours"]
    syntheses = _syntheses_brutes(client_page_id) if syntheses is None else syntheses
    precedente = next((s for s in syntheses if s.get("mois") == numero_mois - 1), None)

    try:
        zone = _zone_la_plus_faible(get_diagnostic_rapport(client_page_id))
    except Exception:
        zone = None

    par_master = {f.get("master_id"): f for f in fiches}
    nom = dashboard.get("nom") or ""

    return {
        "client_page_id": client_page_id,
        "prenom": nom.split()[0] if nom.split() else "",
        "email": (dashboard.get("identite") or {}).get("email"),
        "numero_mois": numero_mois,
        "objectif_90j": dashboard.get("objectif_90j"),
        "zone_prioritaire": zone,
        "fiches_terminees": terminees,
        "nb_fiches_terminees": len(terminees),
        "fiches_en_cours": en_cours,
        "kpi": dashboard.get("kpi") or [],
        "derniers_bilans": {
            master_id: _derniere_entree(par_master.get(master_id), client_page_id)
            for master_id in _SYNTHESE_FICHES_BILAN
        },
        "synthese_precedente": (precedente or {}).get("texte") or None,
        "axe": _axe_synthese(len(terminees), (precedente or {}).get("fiches_terminees")),
    }


def clients_autonome_synthese_due(aujourd_hui=None) -> list[dict]:
    """Membres Autonome dont c'est aujourd'hui un jour de synthese (J30, J60,
    J90, puis tous les 30 jours) et qui n'ont pas encore leur synthese du mois."""
    rows = _query_data_source(
        CLIENTS_DATA_SOURCE_ID,
        filter_={"property": "Parcours", "select": {"equals": "Autonome"}},
    )
    dus = []

    for row in rows:
        props = row.get("properties", {})

        if _prop_value(_prop(props, "État")) != "En cours":
            continue

        debut = _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage"))
        debut = debut.get("start") if isinstance(debut, dict) else debut
        jour = _jour_parcours(debut) if aujourd_hui is None else _jour_depuis(debut, aujourd_hui)

        if not jour or jour <= 0 or jour % 30 != 0:
            continue

        numero_mois = jour // 30
        syntheses = _syntheses_brutes(row["id"])

        if any(s.get("mois") == numero_mois for s in syntheses):
            continue

        dus.append(donnees_synthese_autonome(row["id"], numero_mois, syntheses))

    return dus


def _jour_depuis(date_demarrage, aujourd_hui) -> int | None:
    if not date_demarrage:
        return None

    try:
        debut = datetime.fromisoformat(str(date_demarrage)[:10]).date()
    except ValueError:
        return None

    return (aujourd_hui - debut).days


def enregistrer_synthese_autonome(
    client_page_id: str, mois: int, axe: str, texte: str, nb_fiches_terminees: int,
    statut: str = "À relire", email: str = "",
) -> str:
    if axe not in _SYNTHESE_AXES:
        raise ValueError("Axe de synthese inconnu")

    if statut not in _SYNTHESE_STATUTS:
        raise ValueError("Statut de synthese inconnu")

    client = _get_page(client_page_id)
    nom = _prop_value(_prop(client.get("properties", {}), "Nom")) or "Client"
    texte = ia_service.humaniser((texte or "").strip())
    # L'API Notion limite chaque segment de texte a 2000 caracteres.
    segments = [{"text": {"content": texte[i:i + 2000]}} for i in range(0, len(texte), 2000)]

    page = _create_page(SYNTHESES_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{nom} · Synthèse mois {mois}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Mois": {"number": mois},
        "Axe": {"select": {"name": axe}},
        "Date": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
        "Fiches terminées": {"number": nb_fiches_terminees},
        "Texte": {"rich_text": segments},
        "Statut": {"select": {"name": statut}},
        # Pour l'envoi differe par n8n (apres 24 h de relecture possible).
        **({"E-mail client": {"email": email.strip().lower()}} if (email or "").strip() else {}),
    })
    _cache_clear("dashboard:")
    return page["id"]


def changer_statut_synthese(synthese_id: str, statut: str) -> None:
    if statut not in _SYNTHESE_STATUTS:
        raise ValueError("Statut de synthese inconnu")

    _update_page(synthese_id, {"Statut": {"select": {"name": statut}}})
    _cache_clear("dashboard:")


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


def alerter_coach_onboarding(sujet: str, message: str, event: str = "onboarding_docuseal_echec") -> None:
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
            "event": event,
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
    properties["Parcours"] = {"select": {"name": _nom_parcours(extra.get("parcours"))}}

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

    except Exception as error:
        # Le client est deja cree : aucun echec d'envoi, quel qu'il soit, ne doit
        # transformer l'onboarding en erreur. Code fixe uniquement : ce resultat
        # est renvoye au navigateur du coach, et le texte de l'erreur contient
        # l'URL du webhook n8n. Le diagnostic (resume sans URL ni identite) reste
        # dans les logs serveur.
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
