# Carnet de prospects vivant (decision de Rony du 27/10/2026) : le tableau de
# la fiche 11 devient une liste a jour, un prospect par ligne, avec 4 statuts
# et une date de prochaine relance. Chaque changement de statut est date : le
# bilan hebdomadaire peut reprendre ses chiffres (contacts, RDV, ventes).
#
# Stockage : une seule entree « <client> — Carnet de prospects » dans
# [DB] Entrees Portail, reliee au client (pas a la fiche 11, dont l'historique
# reste tel quel). Tant que le carnet n'a jamais ete enregistre, il est
# propose pre-rempli avec les lignes de la fiche 11.

import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from backend.services import notion_service

STATUTS = ["À contacter", "Contacté", "RDV", "Client"]
# Categorie de la bibliotheque proposee par le bouton « Message prêt ».
CATEGORIE_DU_STATUT = {
    "À contacter": "Premier contact",
    "Contacté": "Relance",
    "RDV": "Rendez-vous",
    "Client": "Recommandation",
}
NOM_CARNET = "Carnet de prospects"
TABLEAU_PROSPECTION_MASTER_ID = "39ffaffd875880f7aee1e8b138416d0a"
# Statuts de la fiche 11 (Relance / RdV / Non) : « Non » ne passe pas au carnet.
_STATUT_DEPUIS_FICHE = {"relance": "Contacté", "rdv": "RDV"}

MAX_PROSPECTS = 300
_MAX_NOM = 80
_MAX_CONTACT = 80
_MAX_NOTE = 300
_MAX_EVENEMENTS = 30
_TTL = 300


class CarnetInvalide(ValueError):
    """Saisie refusee, avec un message ecrit pour le client."""

    def __init__(self, message_client: str):
        super().__init__(message_client)
        self.message_client = message_client


def _aujourd_hui() -> date:
    return datetime.now(timezone.utc).date()


def _texte(valeur, maximum: int) -> str:
    return " ".join(str(valeur or "").split())[:maximum]


def _date_iso(valeur) -> str | None:
    texte = str(valeur or "")[:10]

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texte):
        return None

    try:
        return date.fromisoformat(texte).isoformat()
    except ValueError:
        return None


# --- Lecture -------------------------------------------------------------------

def _page_carnet(client_page_id: str) -> dict | None:
    pages = notion_service._query_data_source(
        notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"and": [
            {"property": "Client", "relation": {"contains": client_page_id}},
            {"property": "Nom", "title": {"contains": NOM_CARNET}},
        ]},
    )
    pages = sorted(pages, key=lambda page: page.get("last_edited_time") or "", reverse=True)
    return pages[0] if pages else None


def _contenu(page: dict) -> dict:
    props = page.get("properties", {})
    brut = notion_service._prop_value(notion_service._prop(props, "Données (JSON)")) or "{}"

    try:
        donnees = json.loads(brut)
    except json.JSONDecodeError:
        donnees = {}

    prospects = donnees.get("prospects") if isinstance(donnees, dict) else None
    return {"prospects": [p for p in prospects or [] if isinstance(p, dict) and p.get("id")]}


def import_depuis_fiche(dashboard: dict) -> list[dict]:
    """Lignes de la fiche 11 regroupees par prospect (la plus recente l'emporte)."""
    fiche = next((f for f in dashboard.get("fiches") or [] if f.get("master_id") == TABLEAU_PROSPECTION_MASTER_ID), None)

    if not fiche:
        return []

    champs = notion_service.FICHE_SCHEMAS[TABLEAU_PROSPECTION_MASTER_ID]["champs"]
    pages = notion_service._query_data_source(
        notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Fiche Client", "relation": {"contains": fiche["id"]}},
    )
    par_nom: dict[str, dict] = {}

    for page in sorted(pages, key=lambda p: p.get("created_time") or ""):
        donnees = notion_service._parse_entry(page, champs)["donnees"]
        nom = _texte(donnees.get("nom_prospect"), _MAX_NOM)

        if not nom:
            continue

        statut_fiche = re.sub(r"[^a-z]", "", str(donnees.get("statut") or "").lower())
        quand = _date_iso(donnees.get("date_contact")) or _date_iso(page.get("created_time")) or _aujourd_hui().isoformat()
        par_nom[nom.lower()] = {
            "nom": nom,
            "statut_fiche": statut_fiche,
            "statut": _STATUT_DEPUIS_FICHE.get(statut_fiche, "À contacter"),
            "note": _texte(donnees.get("prochaine_action"), _MAX_NOTE),
            "contact": _texte(donnees.get("canal"), _MAX_CONTACT),
            "date": quand,
        }

    prospects = []

    for ligne in par_nom.values():
        if ligne["statut_fiche"] == "non":
            continue

        prospects.append({
            "id": secrets.token_hex(6),
            "nom": ligne["nom"],
            "contact": ligne["contact"],
            "statut": ligne["statut"],
            "relance": None,
            "note": ligne["note"],
            "cree_le": ligne["date"],
            "evenements": [] if ligne["statut"] == "À contacter" else [{"date": ligne["date"], "statut": ligne["statut"]}],
        })

    return prospects[:MAX_PROSPECTS]


def lire(client_page_id: str, dashboard: dict | None = None) -> dict:
    """{"prospects": [...], "page_id": str | None, "importe": bool}"""
    cle = f"carnet:{client_page_id}"
    en_cache = notion_service._cache_get(cle)

    if en_cache is not None:
        return en_cache

    page = _page_carnet(client_page_id)

    if page:
        carnet = {**_contenu(page), "page_id": page["id"], "importe": False}
    else:
        importes = import_depuis_fiche(dashboard) if dashboard else []
        carnet = {"prospects": importes, "page_id": None, "importe": bool(importes)}

    return notion_service._cache_set(cle, carnet, _TTL)


# --- Ecriture --------------------------------------------------------------------

def _enregistrer(client_page_id: str, nom_client: str, carnet: dict) -> dict:
    contenu = json.dumps({"version": 1, "prospects": carnet["prospects"]}, ensure_ascii=False)
    morceaux = [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]

    if len(morceaux) > 100:
        raise CarnetInvalide("Ton carnet est trop rempli. Supprime les prospects qui ne sont plus d'actualité.")

    proprietes = {
        "Données (JSON)": {"rich_text": morceaux},
        "Date": {"date": {"start": _aujourd_hui().isoformat()}},
    }

    if carnet.get("page_id"):
        notion_service._update_page(carnet["page_id"], proprietes)
    else:
        page = notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
            **proprietes,
            "Nom": {"title": [{"text": {"content": f"{nom_client or 'Client'} — {NOM_CARNET}"}}]},
            "Client": {"relation": [{"id": client_page_id}]},
        })
        carnet = {**carnet, "page_id": page.get("id")}

    carnet = {**carnet, "importe": False}
    return notion_service._cache_set(f"carnet:{client_page_id}", carnet, _TTL)


def _evenement(prospect: dict, statut: str, quand: str) -> None:
    prospect["evenements"] = (prospect.get("evenements") or []) + [{"date": quand, "statut": statut}]
    prospect["evenements"] = prospect["evenements"][-_MAX_EVENEMENTS:]


def _champs_valides(donnees: dict, partiel: bool) -> dict:
    propres = {}

    if "nom" in donnees or not partiel:
        nom = _texte(donnees.get("nom"), _MAX_NOM)

        if not nom:
            raise CarnetInvalide("Donne au moins un nom à ce prospect.")
        propres["nom"] = nom

    if "contact" in donnees:
        propres["contact"] = _texte(donnees.get("contact"), _MAX_CONTACT)

    if "note" in donnees:
        propres["note"] = _texte(donnees.get("note"), _MAX_NOTE)

    if "statut" in donnees or not partiel:
        statut = donnees.get("statut") or "À contacter"

        if statut not in STATUTS:
            raise CarnetInvalide("Statut inconnu.")
        propres["statut"] = statut

    if "relance" in donnees:
        valeur = donnees.get("relance")

        if valeur in (None, ""):
            propres["relance"] = None
        else:
            relance = _date_iso(valeur)

            if not relance:
                raise CarnetInvalide("Date de relance invalide.")
            propres["relance"] = relance

    return propres


def appliquer(client_page_id: str, nom_client: str, dashboard: dict, action: str, prospect_id: str | None, donnees: dict | None) -> dict:
    """Une action du client sur son carnet : ajouter, modifier, relance
    (« j'ai relance », compte comme un contact), supprimer."""
    carnet = lire(client_page_id, dashboard)
    prospects = [dict(p) for p in carnet["prospects"]]
    donnees = donnees or {}
    aujourd_hui = _aujourd_hui().isoformat()

    if action == "ajouter":
        if len(prospects) >= MAX_PROSPECTS:
            raise CarnetInvalide(f"Ton carnet est plein ({MAX_PROSPECTS} prospects). Supprime ceux qui ne sont plus d'actualité.")

        champs = _champs_valides(donnees, partiel=False)
        nouveau = {"id": secrets.token_hex(6), "contact": "", "note": "", "relance": None, **champs, "cree_le": aujourd_hui, "evenements": []}

        if nouveau["statut"] != "À contacter":
            _evenement(nouveau, nouveau["statut"], aujourd_hui)
        prospects.insert(0, nouveau)
    else:
        prospect = next((p for p in prospects if p.get("id") == prospect_id), None)

        if not prospect:
            raise LookupError("Prospect introuvable")

        if action == "supprimer":
            prospects = [p for p in prospects if p is not prospect]
        elif action == "modifier":
            champs = _champs_valides(donnees, partiel=True)

            if "statut" in champs and champs["statut"] != prospect.get("statut"):
                _evenement(prospect, champs["statut"], aujourd_hui)

            if champs.get("statut") == "Client" and "relance" not in champs:
                champs["relance"] = None
            prospect.update(champs)
        elif action == "relance":
            champs = _champs_valides({k: v for k, v in donnees.items() if k == "relance"}, partiel=True)

            if prospect.get("statut") == "À contacter":
                prospect["statut"] = "Contacté"
            _evenement(prospect, "Contacté", aujourd_hui)
            prospect["relance"] = champs.get("relance")
        else:
            raise CarnetInvalide("Action inconnue.")

    return _enregistrer(client_page_id, nom_client, {**carnet, "prospects": prospects})


# --- Resume et chiffres de la semaine --------------------------------------------

def a_relancer(prospects: list[dict], jour: date | None = None) -> list[dict]:
    """Prospects dont la relance tombe aujourd'hui ou est passee."""
    limite = (jour or _aujourd_hui()).isoformat()
    return sorted(
        (p for p in prospects if p.get("relance") and p["relance"] <= limite and p.get("statut") != "Client"),
        key=lambda p: p["relance"],
    )


def totaux_semaine(prospects: list[dict], lundi: date) -> dict:
    """Ce que le carnet a vu passer du lundi au dimanche : un contact par
    passage a « Contacté » ou relance faite, un RDV, une vente (« Client »)."""
    fin = lundi + timedelta(days=6)
    totaux = {"contacts": 0, "rdv": 0, "ventes": 0}
    cle = {"Contacté": "contacts", "RDV": "rdv", "Client": "ventes"}

    for prospect in prospects:
        for evenement in prospect.get("evenements") or []:
            quand = _date_iso(evenement.get("date"))

            if quand and lundi.isoformat() <= quand <= fin.isoformat() and evenement.get("statut") in cle:
                totaux[cle[evenement["statut"]]] += 1

    return totaux


def vue_client(carnet: dict, jour: date | None = None) -> dict:
    jour = jour or _aujourd_hui()
    prospects = carnet["prospects"]
    lundi = jour - timedelta(days=jour.weekday())

    return {
        "prospects": prospects,
        "importe": carnet.get("importe", False),
        "statuts": STATUTS,
        "categories": CATEGORIE_DU_STATUT,
        "a_relancer": [p["id"] for p in a_relancer(prospects, jour)],
        "par_statut": {s: sum(1 for p in prospects if p.get("statut") == s) for s in STATUTS},
        "semaine": {"lundi": lundi.isoformat(), **totaux_semaine(prospects, lundi)},
        "semaine_precedente": {"lundi": (lundi - timedelta(days=7)).isoformat(), **totaux_semaine(prospects, lundi - timedelta(days=7))},
    }
