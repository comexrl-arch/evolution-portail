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

CLIENTS_DATA_SOURCE_ID = os.getenv("NOTION_CLIENTS_DATA_SOURCE_ID", "39ffaffd-8758-8079-ad4d-000bd60487e8")
FICHES_CLIENT_DATA_SOURCE_ID = os.getenv("NOTION_FICHES_CLIENT_DATA_SOURCE_ID", "3b1faffd-8758-80d7-8b29-000be5060b26")
ENTREES_PORTAIL_DATA_SOURCE_ID = os.getenv("NOTION_ENTREES_PORTAIL_DATA_SOURCE_ID", "ab1f67c7-fa88-4119-8992-dc9da95e917c")
LIVRABLES_DATA_SOURCE_ID = os.getenv("NOTION_LIVRABLES_DATA_SOURCE_ID", "39ffaffd-8758-807d-afc1-000bb979786c")
KPI_DATA_SOURCE_ID = os.getenv("NOTION_KPI_DATA_SOURCE_ID", "39ffaffd-8758-8010-a085-000bf44d8e0f")
CONNEXIONS_DATA_SOURCE_ID = os.getenv("NOTION_CONNEXIONS_DATA_SOURCE_ID", "c6580a4f-a53a-4359-9725-f4ebf3ef6ff2")

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
        raise RuntimeError("NOTION_API_KEY manquant. Renseigne-le dans .env (voir .env.example).")
    return {"Authorization": f"Bearer {NOTION_API_KEY}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}


def _query_data_source(data_source_id: str, filter_: dict | None = None) -> list[dict]:
    payload = {"filter": filter_} if filter_ else {}
    try:
        response = requests.post(f"{NOTION_API_BASE}/data_sources/{data_source_id}/query", headers=_headers(), json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (query) : {error}") from error
    return response.json().get("results", [])


def _get_page(page_id: str) -> dict:
    try:
        response = requests.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(), timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (page {page_id}) : {error}") from error
    return response.json()


def _create_page(parent_data_source_id: str, properties: dict) -> dict:
    payload = {"parent": {"type": "data_source_id", "data_source_id": parent_data_source_id}, "properties": properties}
    try:
        response = requests.post(f"{NOTION_API_BASE}/pages", headers=_headers(), json=payload, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (creation page) : {error}") from error
    return response.json()


def _update_page(page_id: str, properties: dict) -> dict:
    try:
        response = requests.patch(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(), json={"properties": properties}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (mise a jour page {page_id}) : {error}") from error
    return response.json()


def _archive_page(page_id: str) -> None:
    try:
        response = requests.patch(f"{NOTION_API_BASE}/pages/{page_id}", headers=_headers(), json={"archived": True}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (archivage page {page_id}) : {error}") from error


def _rollback_pages(page_ids: list[str]) -> list[str]:
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
    results = _query_data_source(CLIENTS_DATA_SOURCE_ID, filter_={"property": "E-mail", "email": {"equals": email}})
    return results[0] if results else None


_NOM_TO_MASTER_ID = {schema["nom"]: master_id for master_id, schema in FICHE_SCHEMAS.items()}


def _leading_number(text: str) -> str | None:
    match = re.match(r"^\s*(\d+)", text)
    return match.group(1) if match else None


_NUMERO_TO_MASTER_ID = {_leading_number(schema["nom"]): master_id for master_id, schema in FICHE_SCHEMAS.items() if _leading_number(schema["nom"]) is not None}
_FICHES_PAR_MODULE = {
    "0. Commencer ici": ["39ffaffd87588016a405da4d8a0582d4", "39ffaffd8758809e9807c4c5e5504352", "39ffaffd875880a6aad2f438e54855dd"],
    "1. Diagnostic": ["39ffaffd87588001824bdaf6c91b3632", "39ffaffd8758802d93c6e790f165b53e", "39ffaffd87588048a076e678e9b24230", "39ffaffd875880abae31d7fd1f7a1c99", "39ffaffd87588086b588e7a82738c7b1", "39ffaffd87588015a47febbf572e6f62"],
    "2. Offre & Positionnement": ["39ffaffd8758805ebebfd5f5c3914a56", "39ffaffd875880deb56ce1395ae32687", "39ffaffd875880f980a9f99a718d4141", "39ffaffd875880d7bf80c72c865a88b2"],
    "3. Prospection Terrain": ["39ffaffd875880ebbcdde70a29c35269", "39ffaffd875880f7aee1e8b138416d0a", "39ffaffd875880f9a066e6a7e1dc7d37", "39ffaffd875880f7aee1e8b24230", "39ffaffd875880708581d60c234aab45"],
    "4. RDV & Conversion": ["39ffaffd87588001b983e13aa1a06cda", "39ffaffd8758805398f7dc22d26b9626"],
    "5. KPI & Pilotage": ["39ffaffd875880809b88e03b18dd4be3", "39ffaffd875880448c4fe3287b893bf1"],
}
FICHE_MODULES = {master_id: {"nom": module_nom, "ordre": ordre} for ordre, (module_nom, master_ids) in enumerate(_FICHES_PAR_MODULE.items()) for master_id in master_ids}
_FICHES_DEBLOCAGE_COACH = {"39ffaffd87588015a47febbf572e6f62"}
_DIAGNOSTIC_ZONES = [
    {"numero": 1, "zone": "Offre", "master_id": "39ffaffd87588001824bdaf6c91b3632"},
    {"numero": 2, "zone": "Visibilité", "master_id": "39ffaffd8758802d93c6e790f165b53e"},
    {"numero": 3, "zone": "Prospection", "master_id": "39ffaffd87588048a076e678e9b24230"},
    {"numero": 4, "zone": "Conversion", "master_id": "39ffaffd875880abae31d7fd1f7a1c99"},
    {"numero": 5, "zone": "Suivi commercial", "master_id": "39ffaffd87588086b588e7a82738c7b1"},
]
_DIAGNOSTIC_FICHE8_MASTER_ID = "39ffaffd87588015a47febbf572e6f62"


def _resolve_master_id(props: dict) -> str | None:
    master_ids = _prop_value(_prop(props, "[DB] Fiches Master")) or []
    if master_ids:
        return master_ids[0].replace("-", "")
    nom = _prop_value(_prop(props, "Nom")) or ""
    suffixe = nom.split(" - ", 1)[-1]
    if suffixe in _NOM_TO_MASTER_ID:
        return _NOM_TO_MASTER_ID[suffixe]
    for master_nom, master_id in _NOM_TO_MASTER_ID.items():
        if nom.endswith(master_nom):
            return master_id
    numero = _leading_number(suffixe)
    return _NUMERO_TO_MASTER_ID.get(numero) if numero is not None else None


def _fiche_summary(fiche_client_id: str) -> dict:
    page = _get_page(fiche_client_id)
    props = page.get("properties", {})
    nom = _prop_value(_prop(props, "Nom"))
    master_id = _resolve_master_id(props)
    schema = FICHE_SCHEMAS.get(master_id) if master_id else None
    module = FICHE_MODULES.get(master_id) if master_id else None
    return {"id": page["id"], "master_id": master_id, "nom": nom, "ordre": _prop_value(_prop(props, "Ordre")), "etat": _prop_value(_prop(props, "État")), "mode": (schema or {}).get("mode"), "module": (module or {}).get("nom")}


def _fiche_sort_key(fiche: dict):
    if fiche.get("ordre") is not None:
        return fiche["ordre"]
    suffixe = (fiche.get("nom") or "").split(" - ", 1)[-1]
    match = re.match(r"^\s*(\d+)", suffixe)
    return int(match.group(1)) if match else 999


def _apply_acces(fiches: list[dict]) -> None:
    previous_terminee = True
    for fiche in fiches:
        if fiche.get("master_id") in _FICHES_DEBLOCAGE_COACH:
            etat = fiche.get("etat")
            fiche["acces"] = "✅ Terminé" if etat == "Terminé" else ("🚀 En cours" if etat == "En cours" else "🔒 Bloqué")
            continue
        if fiche.get("etat") == "Terminé":
            fiche["acces"] = "✅ Terminé"
        elif previous_terminee:
            fiche["acces"] = "🚀 En cours"
        else:
            fiche["acces"] = "🔒 Bloqué"
        previous_terminee = fiche.get("etat") == "Terminé"


def _client_identite(props: dict) -> dict:
    return {"nom": _prop_value(_prop(props, "Nom")), "email": _prop_value(_prop(props, "E-mail")), "telephone": _prop_value(_prop(props, "Téléphone")), "contact": _prop_value(_prop(props, "Contact")), "activite": _prop_value(_prop(props, "Activité")), "secteur": _prop_value(_prop(props, "Secteur")), "territoire": _prop_value(_prop(props, "Territoire")), "offre_principale": _prop_value(_prop(props, "Offre Principale")), "site_reseaux": _prop_value(_prop(props, "Site / Réseaux"))}


def _client_cohorte(props: dict) -> dict | None:
    cohorte_ids = _prop_value(_prop(props, "Cohorte")) or []
    if not cohorte_ids:
        return None
    cohorte_props = _get_page(cohorte_ids[0]).get("properties", {})
    return {"nom": _prop_value(_prop(cohorte_props, "Nom")), "statut": _prop_value(_prop(cohorte_props, "Statut")), "date_debut": _prop_value(_prop(cohorte_props, "Date début")), "date_fin": _prop_value(_prop(cohorte_props, "Date fin"))}


def _client_sessions(props: dict) -> list[dict]:
    sessions = []
    for session_id in _prop_value(_prop(props, "Sessions")) or []:
        session_props = _get_page(session_id).get("properties", {})
        sessions.append({"id": session_id, "nom": _prop_value(_prop(session_props, "Nom")), "date_heure": _prop_value(_prop(session_props, "Date & heure")), "statut": _prop_value(_prop(session_props, "Statut")), "prochaine_echeance": _prop_value(_prop(session_props, "Prochaine échéance"))})
    sessions.sort(key=lambda session: session.get("date_heure") or "")
    return sessions


def _client_kpi(client_page_id: str) -> list[dict]:
    rows = _query_data_source(KPI_DATA_SOURCE_ID, filter_={"property": "Client", "relation": {"contains": client_page_id}})
    kpis = []
    for row in rows:
        props = row.get("properties", {})
        kpis.append({"id": row["id"], "nom": _prop_value(_prop(props, "Nom")), "categorie": _prop_value(_prop(props, "Catégorie")), "phase": _prop_value(_prop(props, "Phase")), "etat": _prop_value(_prop(props, "État")), "valeur_j0": _prop_value(_prop(props, "Valeur J0")), "valeur_j30": _prop_value(_prop(props, "Valeur J30")), "valeur_j60": _prop_value(_prop(props, "Valeur J60")), "valeur_j90": _prop_value(_prop(props, "Valeur J90")), "objectif_j30": _prop_value(_prop(props, "Objectif J30")), "objectif_j60": _prop_value(_prop(props, "Objectif J60")), "objectif_j90": _prop_value(_prop(props, "Objectif J90"))})
    kpis.sort(key=lambda kpi: kpi.get("nom") or "")
    return kpis


def _add_dashes(page_id_no_dashes: str) -> str:
    p = page_id_no_dashes
    return f"{p[0:8]}-{p[8:12]}-{p[12:16]}-{p[16:20]}-{p[20:32]}"


def _livrables_for_fiche(fiche_client_id: str, master_id: str) -> list[dict]:
    rows = _query_data_source(LIVRABLES_DATA_SOURCE_ID, filter_={"or": [{"property": "Fiche Master (référence)", "relation": {"contains": _add_dashes(master_id)}}, {"property": "Fiche Client", "relation": {"contains": fiche_client_id}}]})
    livrables = []
    for row in rows:
        props = row.get("properties", {})
        livrables.append({"id": row["id"], "nom": _prop_value(_prop(props, "Nom")), "etat": _prop_value(_prop(props, "État")), "validation_coach": _prop_value(_prop(props, "Validation coach")), "obligatoire": _prop_value(_prop(props, "Obligatoire")), "commentaire_coach": _prop_value(_prop(props, "Commentaire coach")), "date_depot": _prop_value(_prop(props, "Date de dépôt")), "date_validation": _prop_value(_prop(props, "Date de validation"))})
    livrables.sort(key=lambda l: l.get("nom") or "")
    return livrables


def _repair_missing_fiches(client_page_id: str, nom_client: str, fiches: list[dict]) -> list[dict]:
    existing_master_ids = {f["master_id"] for f in fiches if f.get("master_id")}
    nouvelles = []
    for master_id, schema in _fiche_master_items_sorted():
        if master_id in existing_master_ids:
            continue
        ordre = int(_leading_number(schema["nom"]) or 0)
        page = _create_page(FICHES_CLIENT_DATA_SOURCE_ID, {"Nom": {"title": [{"text": {"content": f"{nom_client} - {schema['nom']}"}}]}, "⁠[DB] Clients⁠": {"relation": [{"id": client_page_id}]}, "⁠[DB] Fiches Master": {"relation": [{"id": _add_dashes(master_id)}]}, "Ordre": {"number": ordre}, "État": {"status": {"name": "Pas commencé"}}, "✅ Valider cette fiche": {"checkbox": False}})
        nouvelles.append(_fiche_summary(page["id"]))
    return fiches + nouvelles


def get_client_dashboard(client_page_id: str) -> dict:
    page = _get_page(client_page_id)
    props = page.get("properties", {})
    fiche_ids = _prop_value(_prop(props, "[DB] Fiches Client")) or []
    fiches = [_fiche_summary(fiche_id) for fiche_id in fiche_ids]
    if len(fiches) < len(FICHE_SCHEMAS):
        fiches = _repair_missing_fiches(client_page_id, _prop_value(_prop(props, "Nom")), fiches)
    fiches.sort(key=_fiche_sort_key)
    _apply_acces(fiches)
    return {"nom": _prop_value(_prop(props, "Nom")), "objectif_90j": _prop_value(_prop(props, "Objectif 90j")), "date_demarrage": _prop_value(_prop(props, "Date de demarrage")) or _prop_value(_prop(props, "Date de démarrage")), "date_bilan_90j": _prop_value(_prop(props, "Date bilan 90 jours")), "phase_parcours": _prop_value(_prop(props, "Phase parcours")), "progression_kpi_j90": _prop_value(_prop(props, "Progression KPI J90")), "progression_livrables": _prop_value(_prop(props, "Progression livrables")), "identite": _client_identite(props), "cohorte": _client_cohorte(props), "sessions": _client_sessions(props), "fiches": fiches, "kpi": _client_kpi(client_page_id)}


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


_BLOCK_TYPE_PREFIX = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ", "numbered_list_item": "- ", "callout": "> ", "quote": "> ", "to_do": "- "}
_WARNING_MARKER = "non copiable automatiquement"


def _block_text(block: dict) -> str:
    block_type = block.get("type")
    return "".join(part.get("plain_text", "") for part in block.get(block_type, {}).get("rich_text", []))


def _is_internal_warning(block: dict) -> bool:
    return block.get("type") == "callout" and _WARNING_MARKER in _block_text(block).lower()


def _list_children(block_id: str) -> list[dict]:
    try:
        response = requests.get(f"{NOTION_API_BASE}/blocks/{block_id}/children", headers=_headers(), params={"page_size": 100}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (blocs {block_id}) : {error}") from error
    return response.json().get("results", [])


def _blocks_to_text(blocks: list[dict]) -> str:
    lines = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "divider" or _is_internal_warning(block):
            continue
        text = _block_text(block)
        if text:
            lines.append(_BLOCK_TYPE_PREFIX.get(block_type, "") + text)
    return "\n".join(lines)


def _get_page_content(page_id: str) -> str:
    return _blocks_to_text(_list_children(page_id))


def _page_segments(page_id: str) -> list[dict]:
    segments = []
    for block in _list_children(page_id):
        block_type = block.get("type")
        if block_type == "divider" or _is_internal_warning(block):
            continue
        if block_type == "to_do":
            segments.append({"type": "champ", "champ": {"cle": block["id"].replace("-", ""), "libelle": _block_text(block).strip("* "), "type": "case"}})
            continue
        text = _block_text(block)
        if text:
            segments.append({"type": "texte", "texte": _BLOCK_TYPE_PREFIX.get(block_type, "") + text})
    return segments


def _donnees_vers_libelles(data: dict, champs: list[dict]) -> dict:
    cle_vers_libelle = {champ["cle"]: champ["libelle"] for champ in champs}
    return {cle_vers_libelle.get(cle, cle): valeur for cle, valeur in data.items()}


def _donnees_vers_cles(donnees: dict, champs: list[dict]) -> dict:
    libelle_vers_cle = {champ["libelle"]: champ["cle"] for champ in champs}
    return {libelle_vers_cle.get(libelle, libelle): valeur for libelle, valeur in donnees.items()}


def _parse_entry(page: dict, champs: list[dict]) -> dict:
    props = page.get("properties", {})
    raw = _prop_value(_prop(props, "Données (JSON)")) or _prop_value(_prop(props, "Donnees (JSON)")) or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    return {"id": page["id"], "date": _prop_value(_prop(props, "Date")), "donnees": _donnees_vers_cles(data, champs)}


def _champs_for(schema: dict, master_id: str, segments: list[dict] | None = None) -> list[dict]:
    if schema["mode"] == "unique":
        segments = segments if segments is not None else _page_segments(master_id)
        return [segment["champ"] for segment in segments if segment["type"] == "champ"]
    return schema["champs"]


def get_fiche(fiche_client_id: str, client_page_id: str) -> dict:
    schema, nom, master_id = _fiche_schema_for(fiche_client_id)
    segments = _page_segments(fiche_client_id if master_id in _FICHES_DEBLOCAGE_COACH else master_id) if schema["mode"] == "unique" else None
    champs = _champs_for(schema, master_id, segments)
    entries_raw = _query_data_source(ENTREES_PORTAIL_DATA_SOURCE_ID, filter_={"and": [{"property": "Fiche Client", "relation": {"contains": fiche_client_id}}, {"property": "Client", "relation": {"contains": client_page_id}}]})
    entries = [_parse_entry(page, champs) for page in entries_raw]
    entries.sort(key=lambda entry: entry.get("date") or "")
    result = {"fiche_client_id": fiche_client_id, "nom": nom, "mode": schema["mode"], "champs": champs, "entrees": entries, "livrables": _livrables_for_fiche(fiche_client_id, master_id)}
    if schema["mode"] == "unique":
        result["segments"] = segments
    else:
        result["contenu"] = _get_page_content(master_id)
    return result


_CLIENT_FIELD_SYNC = {("39ffaffd8758809e9807c4c5e5504352", "Quel est votre objectif chiffré ou personnel pour les 90 prochains jours ?"): "Objectif 90j", ("39ffaffd8758809e9807c4c5e5504352", "Votre activité / Votre métier :"): "Activité"}
_KPI_FIELD_SYNC = {("39ffaffd875880abae31d7fd1f7a1c99", "Sur 10 rendez-vous commerciaux réalisés, combien de clients signez-vous en moyenne aujourd'hui ?"): {"nom": "Taux de signature (/10 RDV)", "categorie": "Conversion"}}


def _sync_special_fields(master_id: str, client_page_id: str, data: dict) -> None:
    for label, value in data.items():
        client_prop = _CLIENT_FIELD_SYNC.get((master_id, label))
        if client_prop:
            try:
                response = requests.patch(f"{NOTION_API_BASE}/pages/{client_page_id}", headers=_headers(), json={"properties": {client_prop: {"rich_text": [{"text": {"content": str(value)}}]}}}, timeout=15)
                response.raise_for_status()
            except requests.RequestException as error:
                raise RuntimeError(f"Erreur Notion (synchro {client_prop}) : {error}") from error


def _upsert_kpi_entry(client_page_id: str, master_id: str | None, kpi_nom: str, categorie: str, valeur: float) -> None:
    existing = _query_data_source(KPI_DATA_SOURCE_ID, filter_={"and": [{"property": "Nom", "title": {"equals": kpi_nom}}, {"property": "Client", "relation": {"contains": client_page_id}}]})
    if existing:
        try:
            response = requests.patch(f"{NOTION_API_BASE}/pages/{existing[0]['id']}", headers=_headers(), json={"properties": {"Valeur J0": {"number": valeur}}}, timeout=15)
            response.raise_for_status()
        except requests.RequestException as error:
            raise RuntimeError(f"Erreur Notion (mise a jour KPI {kpi_nom}) : {error}") from error
        return
    properties = {"Nom": {"title": [{"text": {"content": kpi_nom}}]}, "Client": {"relation": [{"id": client_page_id}]}, "Catégorie": {"select": {"name": categorie}}, "Phase": {"select": {"name": "J0 · Diagnostic"}}, "État": {"status": {"name": "En cours"}}, "Valeur J0": {"number": valeur}}
    if master_id:
        properties["Fiche associée"] = {"relation": [{"id": _add_dashes(master_id)}]}
    _create_page(KPI_DATA_SOURCE_ID, properties)


def _sync_kpi_fields(master_id: str, client_page_id: str, data: dict) -> None:
    for label, value in data.items():
        kpi = _KPI_FIELD_SYNC.get((master_id, label))
        if not kpi:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        _upsert_kpi_entry(client_page_id, master_id, kpi["nom"], kpi["categorie"], number)


def create_entry(fiche_client_id: str, client_page_id: str, client_nom: str, data: dict) -> dict:
    schema, fiche_nom, master_id = _fiche_schema_for(fiche_client_id)
    champs = _champs_for(schema, master_id)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    readable = _donnees_vers_libelles(data, champs)
    _sync_special_fields(master_id, client_page_id, readable)
    _sync_kpi_fields(master_id, client_page_id, readable)
    properties = {"Nom": {"title": [{"text": {"content": f"{client_nom} — {fiche_nom} — {now_iso}"}}]}, "Client": {"relation": [{"id": client_page_id}]}, "Fiche Client": {"relation": [{"id": fiche_client_id}]}, "Date": {"date": {"start": now_iso}}, "Données (JSON)": {"rich_text": [{"text": {"content": json.dumps(readable, ensure_ascii=False)}}]}}
    if schema["mode"] == "unique":
        existing = _query_data_source(ENTREES_PORTAIL_DATA_SOURCE_ID, filter_={"and": [{"property": "Fiche Client", "relation": {"contains": fiche_client_id}}, {"property": "Client", "relation": {"contains": client_page_id}}]})
        if existing:
            return _parse_entry(_update_page(existing[0]["id"], properties), champs)
    return _parse_entry(_create_page(ENTREES_PORTAIL_DATA_SOURCE_ID, properties), champs)


def validate_fiche(fiche_client_id: str) -> None:
    try:
        response = requests.patch(f"{NOTION_API_BASE}/pages/{fiche_client_id}", headers=_headers(), json={"properties": {"✅ Valider cette fiche": {"checkbox": True}, "État": {"status": {"name": "Terminé"}}}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur Notion (validation fiche {fiche_client_id}) : {error}") from error


def send_portal_invite(email: str, client_page_id: str, client_nom: str) -> dict:
    webhook_url = os.getenv("N8N_WEBHOOK_MAGIC_LINK")
    if not webhook_url:
        raise RuntimeError("N8N_WEBHOOK_MAGIC_LINK manquant. Copie .env.example vers .env et renseigne lURL du webhook n8n.")
    portal_frontend_url = os.getenv("PORTAL_FRONTEND_URL", "http://localhost:5174")
    token = portal_auth_service.create_magic_link_token(email, client_page_id)
    magic_link = f"{portal_frontend_url}/verify?token={token}"
    try:
        response = requests.post(webhook_url, json={"to": email, "client_name": client_nom, "magic_link": magic_link}, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Erreur envoi invitation portail : {error}") from error
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def log_portal_connection(email: str, client_page_id: str) -> None:
    try:
        client_nom = client_display_name(_get_page(client_page_id))
    except RuntimeError:
        client_nom = ""
    try:
        _create_page(CONNEXIONS_DATA_SOURCE_ID, {"Email": {"title": [{"text": {"content": email}}]}, "Client": {"rich_text": [{"text": {"content": client_nom}}]}, "Date de connexion": {"date": {"start": datetime.now(timezone.utc).isoformat()}}})
    except RuntimeError as error:
        logger.warning("Echec journalisation connexion portail (%s) : %s", email, error)


CLIENT_ONBOARDING_FIELDS = {"activite": ("Activité", "rich_text"), "secteur": ("Secteur", "rich_text"), "territoire": ("Territoire", "rich_text"), "contact": ("Contact", "rich_text"), "offre_principale": ("Offre Principale", "rich_text"), "client_cible": ("Client Cible", "rich_text"), "objectif_90j": ("Objectif 90j", "rich_text"), "urgence_echeance": ("Urgence / Échéance", "rich_text"), "telephone": ("Téléphone", "phone_number"), "site_reseaux": ("Site / Réseaux", "url")}
_KPI_ONBOARDING_DEFAULTS = [{"cle": "leads_j0", "nom": "Leads", "categorie": "Acquisition"}, {"cle": "rdv_j0", "nom": "RDV", "categorie": "Acquisition"}, {"cle": "nouveaux_clients_j0", "nom": "Nouveaux clients", "categorie": "Conversion"}, {"cle": "ca_j0", "nom": "Chiffre d’affaires", "categorie": "Chiffre d’affaires"}]


def _fiche_master_items_sorted() -> list[tuple[str, dict]]:
    items = list(FICHE_SCHEMAS.items())
    items.sort(key=lambda item: int(_leading_number(item[1]["nom"]) or 999))
    return items


def onboard_client(nom: str, email: str, kpi_j0: dict | None = None, **extra) -> dict:
    email = (email or "").strip().lower()
    if find_client_by_email(email):
        raise RuntimeError(f"Un client existe deja avec l'email {email}. Onboarding annule pour eviter un doublon.")
    properties = {"Nom": {"title": [{"text": {"content": nom}}]}, "E-mail": {"email": email}, "Phase parcours": {"select": {"name": "Module 0 actif"}}, "État": {"status": {"name": "En cours"}}, "Date de démarrage": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}}}
    for key, value in extra.items():
        field = CLIENT_ONBOARDING_FIELDS.get(key)
        if not field or value in (None, ""):
            continue
        name, field_type = field
        if field_type == "rich_text":
            properties[name] = {"rich_text": [{"text": {"content": str(value)}}]}
        elif field_type == "url":
            properties[name] = {"url": str(value)}
        elif field_type == "phone_number":
            properties[name] = {"phone_number": str(value)}
    kpi_j0 = kpi_j0 or {}
    created = []
    try:
        client = _create_page(CLIENTS_DATA_SOURCE_ID, properties)
        client_id = client["id"]
        created.append(client_id)
        fiches_creees = 0
        for master_id, schema in _fiche_master_items_sorted():
            fiche = _create_page(FICHES_CLIENT_DATA_SOURCE_ID, {"Nom": {"title": [{"text": {"content": f"{nom} - {schema['nom']}"}}]}, "⁠[DB] Clients⁠": {"relation": [{"id": client_id}]}, "⁠[DB] Fiches Master": {"relation": [{"id": _add_dashes(master_id)}]}, "Ordre": {"number": int(_leading_number(schema["nom"]) or 0)}, "État": {"status": {"name": "Pas commencé"}}, "✅ Valider cette fiche": {"checkbox": False}})
            created.append(fiche["id"])
            fiches_creees += 1
        kpi_crees = 0
        missing = []
        for kpi in _KPI_ONBOARDING_DEFAULTS:
            value = kpi_j0.get(kpi["cle"])
            has_value = value not in (None, "")
            kp = {"Nom": {"title": [{"text": {"content": kpi["nom"]}}]}, "Client": {"relation": [{"id": client_id}]}, "Catégorie": {"select": {"name": kpi["categorie"]}}, "Phase": {"select": {"name": "J0 · Diagnostic"}}, "État": {"status": {"name": "En cours" if has_value else "Pas commencé"}}}
            if has_value:
                kp["Valeur J0"] = {"number": float(value)}
            else:
                missing.append(kpi["nom"])
            created.append(_create_page(KPI_DATA_SOURCE_ID, kp)["id"])
            kpi_crees += 1
    except RuntimeError as error:
        remaining = _rollback_pages(created)
        raise RuntimeError(f"Onboarding de {nom} echoue ({error}). Rollback restant: {remaining}") from error
    invite_envoyee = False
    invite_erreur = None
    try:
        send_portal_invite(email, client_id, nom)
        invite_envoyee = True
    except RuntimeError as error:
        invite_erreur = str(error)
    return {"client_id": client_id, "nom": nom, "email": email, "fiches_creees": fiches_creees, "kpi_crees": kpi_crees, "kpi_a_completer": missing, "invite_envoyee": invite_envoyee, "invite_erreur": invite_erreur}