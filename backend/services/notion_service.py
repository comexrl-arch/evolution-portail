import json
import logging
import os
import re
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from backend.services.portal_fiche_schemas import FICHE_SCHEMAS
from backend.services import portal_auth_service

logger = logging.getLogger(__name__)

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


def _query_data_source(data_source_id: str, filter_: dict | None = None) -> list[dict]:
    payload = {"filter": filter_} if filter_ else {}

    try:
        response = requests.post(
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
        response = requests.get(
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
        response = requests.post(
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
        response = requests.patch(
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
        response = requests.patch(
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
    results = _query_data_source(
        CLIENTS_DATA_SOURCE_ID,
        filter_={"property": "E-mail", "email": {"equals": email}},
    )

    return results[0] if results else None


_NOM_TO_MASTER_ID = {schema["nom"]: master_id for master_id, schema in FICHE_SCHEMAS.items()}


def _leading_number(text: str) -> str | None:
    match = re.match(r"^\s*(\d+)", text)
    return match.group(1) if match else None


_NUMERO_TO_MASTER_ID = {
    _leading_number(schema["nom"]): master_id
    for master_id, schema in FICHE_SCHEMAS.items()
    if _leading_number(schema["nom"]) is not None
}

# Regroupement par module, source : "[DB] Modules" (collection
# 39ffaffd-8758-80b1-ac6b-000bbeb2d780), relation "[DB] Fiches" de chaque
# module vers les fiches master qu'il contient. Fige ici comme les autres
# schemas plutot que requete a chaque affichage : la structure des modules
# ne change pas au fil de l'eau, contrairement aux donnees d'un client.
_FICHES_PAR_MODULE = {
    "0. Commencer ici": [
        "39ffaffd87588016a405da4d8a0582d4",
        "39ffaffd8758809e9807c4c5e5504352",
        "39ffaffd875880a6aad2f438e54855dd",
    ],
    "1. Diagnostic": [
        "39ffaffd87588001824bdaf6c91b3632",
        "39ffaffd8758802d93c6e790f165b53e",
        "39ffaffd87588048a076e678e9b24230",
        "39ffaffd875880abae31d7fd1f7a1c99",
        "39ffaffd87588086b588e7a82738c7b1",
        "39ffaffd87588015a47febbf572e6f62",
    ],
    "2. Offre & Positionnement": [
        "39ffaffd8758805ebebfd5f5c3914a56",
        "39ffaffd875880deb56ce1395ae32687",
        "39ffaffd875880f980a9f99a718d4141",
        "39ffaffd875880d7bf80c72c865a88b2",
    ],
    "3. Prospection Terrain": [
        "39ffaffd875880ebbcdde70a29c35269",
        "39ffaffd875880f7aee1e8b138416d0a",
        "39ffaffd875880f9a066e6a7e1dc7d37",
        "39ffaffd8758808c91dfdd277b66fa2a",
        "39ffaffd875880708581d60c234aab45",
    ],
    "4. RDV & Conversion": [
        "39ffaffd87588001b983e13aa1a06cda",
        "39ffaffd8758805398f7dc22d26b9626",
    ],
    "5. KPI & Pilotage": [
        "39ffaffd875880809b88e03b18dd4be3",
        "39ffaffd875880448c4fe3287b893bf1",
    ],
}

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
    page = _get_page(fiche_client_id)
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
    if fiche.get("ordre") is not None:
        return fiche["ordre"]

    # Repli : "Ordre" n'est pas renseigne par le pipeline n8n de duplication
    # (meme lacune que la relation Fiches Master). Les titres suivent le
    # format "{Client} - {N}. {Titre}", on utilise ce numero comme tri.
    nom = fiche.get("nom") or ""
    suffixe = nom.split(" - ", 1)[-1]
    match = re.match(r"^\s*(\d+)", suffixe)
    return int(match.group(1)) if match else 999


# "8. MON RÉSULTAT DE DIAGNOSTIC" se remplit avec le coach en session (scores
# /3 et /15, voir _KPI_FIELD_SYNC plus bas) - jamais seul par le client. Elle
# ne doit donc jamais s'auto-debloquer via la sequence normale : elle reste
# Bloquee tant que le coach ne l'a pas lui-meme passee a En cours/Termine
# directement dans Notion, et son propre etat n'influence pas le
# deverrouillage de la fiche suivante (sinon tout le parcours resterait
# bloque derriere elle).
_FICHES_DEBLOCAGE_COACH = {"39ffaffd87588015a47febbf572e6f62"}


def _apply_acces(fiches: list[dict]) -> None:
    # Calcule le deblocage nous-memes plutot que de lire la formule Notion
    # "acces", qui depend de "Ordre" et de la relation "Fiche Precedente
    # (client)" - non renseignees par le pipeline n8n de duplication (0/60
    # fiches client en prod les ont). La sequence triee + l'Etat de chaque
    # fiche suffisent et ne dependent d'aucune donnee Notion fragile.
    previous_terminee = True

    for fiche in fiches:
        if fiche.get("master_id") in _FICHES_DEBLOCAGE_COACH:
            etat = fiche.get("etat")
            fiche["acces"] = "✅ Terminé" if etat == "Terminé" else (
                "🚀 En cours" if etat == "En cours" else "🔒 Bloqué"
            )
            continue

        if fiche.get("etat") == "Terminé":
            fiche["acces"] = "✅ Terminé"
        elif previous_terminee:
            fiche["acces"] = "🚀 En cours"
        else:
            fiche["acces"] = "🔒 Bloqué"

        previous_terminee = fiche.get("etat") == "Terminé"


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


def get_livrable(livrable_id: str) -> dict:
    # Contenu affiche tel quel dans le portail (sous-page de la fiche) via
    # le meme rendu que les fiches "Suivi recurrent" (_get_page_content).
    # Limite connue : les blocs "table" Notion ne remontent pas (le
    # comptage cellule par cellule n'est pas gere ici), seuls titres,
    # paragraphes, listes, callouts et to_do le sont.
    page = _get_page(livrable_id)
    props = page.get("properties", {})

    return {
        "id": page["id"],
        "nom": _prop_value(_prop(props, "Nom")),
        "contenu": _get_page_content(livrable_id),
    }


def _repair_missing_fiches(client_page_id: str, nom_client: str, fiches: list[dict]) -> list[dict]:
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
    page = _get_page(client_page_id)
    props = page.get("properties", {})
    nom_client = _prop_value(_prop(props, "Nom"))

    fiche_ids = _prop_value(_prop(props, "[DB] Fiches Client")) or []
    fiches = [_fiche_summary(fiche_id) for fiche_id in fiche_ids]

    if len(fiches) < len(FICHE_SCHEMAS):
        fiches = _repair_missing_fiches(client_page_id, nom_client, fiches)

    fiches.sort(key=_fiche_sort_key)
    _apply_acces(fiches)

    return {
        "nom": nom_client,
        "objectif_90j": _prop_value(_prop(props, "Objectif 90j")),
        "date_demarrage": _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage")),
        "date_bilan_90j": _prop_value(_prop(props, "Date bilan 90 jours")),
        "phase_parcours": _prop_value(_prop(props, "Phase parcours")),
        "progression_kpi_j90": _prop_value(_prop(props, "Progression KPI J90")),
        "progression_livrables": _prop_value(_prop(props, "Progression livrables")),
        "identite": _client_identite(props),
        "cohorte": _client_cohorte(props),
        "sessions": _client_sessions(props),
        "fiches": fiches,
        "kpi": _client_kpi(client_page_id),
    }


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
    try:
        response = requests.get(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            headers=_headers(),
            params={"page_size": 100},
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (blocs {block_id}) : {error}") from error

    return response.json().get("results", [])


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
    return ["".join(part.get("plain_text", "") for part in cell) for cell in cells]


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


def _blocks_to_text(blocks: list[dict]) -> str:
    lines = []

    for block in blocks:
        block_type = block.get("type")

        if block_type == "divider" or _is_internal_warning(block):
            continue

        if block_type == "table":
            table_line = _table_to_line(block)

            if table_line:
                lines.append(table_line)

            continue

        text = _block_text(block)

        if not text:
            continue

        lines.append(_BLOCK_TYPE_PREFIX.get(block_type, "") + text)

    return "\n".join(lines)


def _get_page_content(page_id: str) -> str:
    return _blocks_to_text(_list_children(page_id))


def _page_segments(page_id: str) -> list[dict]:
    # Rendu "fidele" d'une fiche Q&A : chaque question Notion (puce en gras
    # suivie d'une sous-puce "Ecrivez ici...") devient un champ affiche en
    # ligne juste apres son enonce, plutot qu'une zone de reponses separee.
    # Les cases a cocher Notion (to_do) restent des cases a cocher.
    segments = []

    for block in _list_children(page_id):
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
            children = _list_children(block["id"])

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

        text = _block_text(block)

        if not text:
            continue

        prefix = "- " if block_type in ("bulleted_list_item", "numbered_list_item") else _BLOCK_TYPE_PREFIX.get(block_type, "")
        segments.append({"type": "texte", "texte": prefix + text})

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
            segments = _page_segments(master_id)

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


def get_fiche(fiche_client_id: str, client_page_id: str) -> dict:
    schema, nom, master_id = _fiche_schema_for(fiche_client_id)
    mode = schema["mode"]

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
            segments = _page_segments(master_id)

    champs = _champs_for(schema, master_id, segments)

    entries_raw = _query_data_source(
        ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={
            "and": [
                {"property": "Fiche Client", "relation": {"contains": fiche_client_id}},
                {"property": "Client", "relation": {"contains": client_page_id}},
            ]
        },
    )
    entries = [_parse_entry(page, champs) for page in entries_raw]
    entries.sort(key=lambda entry: entry.get("date") or "")

    if mode == "unique" and not entries:
        # Pre-remplissage : si le client n'a encore jamais repondu a cette
        # fiche, on propose comme valeur de depart ce qui a deja ete capture
        # cote coach/onboarding dans "[DB] Clients" (via _CLIENT_FIELD_SYNC),
        # plutot que de faire retaper au client une info deja connue. Reste
        # editable normalement au moment de l'enregistrement.
        prefill = _prefill_from_client(master_id, client_page_id, champs)

        if prefill:
            entries = [{"id": None, "date": None, "donnees": prefill}]

    result = {
        "fiche_client_id": fiche_client_id,
        "nom": nom,
        "mode": mode,
        "champs": champs,
        "entrees": entries,
        "livrables": _livrables_for_fiche(fiche_client_id, master_id),
    }

    if mode == "unique":
        result["segments"] = segments
    else:
        result["contenu"] = _get_page_content(master_id)

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
        "Votre activité / Votre métier :",
    ): "Activité",
}


def _sync_special_fields(master_id: str, client_page_id: str, donnees_lisibles: dict) -> None:
    for libelle, valeur in donnees_lisibles.items():
        client_prop = _CLIENT_FIELD_SYNC.get((master_id, libelle))

        if not client_prop:
            continue

        try:
            response = requests.patch(
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
            response = requests.patch(
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
    schema, fiche_nom, master_id = _fiche_schema_for(fiche_client_id)
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
            return _parse_entry(_update_page(existing[0]["id"], properties), champs)

    return _parse_entry(_create_page(ENTREES_PORTAIL_DATA_SOURCE_ID, properties), champs)


def validate_fiche(fiche_client_id: str) -> None:
    # Remplace le bouton Notion natif "Valider et passer a la fiche suivante"
    # (les blocs "button" ne sont pas manipulables via l'API Notion). On coche
    # directement la case et on passe l'Etat a "Termine" nous-memes plutot que
    # de dependre du polling/webhook n8n existant, pour un deblocage instantane
    # cote client.
    try:
        response = requests.patch(
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
        logger.warning("Echec journalisation connexion portail (%s) : %s", email, error)


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
    client_existant = find_client_by_email(email)

    if client_existant:
        raise RuntimeError(
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

    kpi_j0 = kpi_j0 or {}
    created_page_ids: list[str] = []

    try:
        client_page = _create_page(CLIENTS_DATA_SOURCE_ID, properties)
        client_id = client_page["id"]
        created_page_ids.append(client_id)

        fiches_creees = 0

        for master_id, schema in _fiche_master_items_sorted():
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
        invite_erreur = str(error)

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
