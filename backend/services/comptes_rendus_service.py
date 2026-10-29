# Compte rendu apres chaque point (decision de Rony du 29/10/2026, « Idris
# prepare, Rony signe ») : Rony dicte ou tape ce qui s'est dit, Idris peut le
# mettre en forme, et l'eleve retrouve ses engagements sur son tableau de bord.
# Son bilan de la semaine suivante les reprend (retour d'Idris).
#
# - Stockage : une entree « <client> — Compte rendu de point du <date> » de
#   [DB] Entrees Portail par point (JSON), rien a creer dans Notion.
# - Coaching et Atelier seulement : l'Autonome n'a pas de suivi individuel.

import json
import logging
import re
import secrets
from datetime import date, datetime, timezone

from backend.services import ia_service, notion_service

logger = logging.getLogger(__name__)

NOM_COMPTE_RENDU = "Compte rendu de point"
MAX_ENGAGEMENTS = 5
_MAX_RESUME = 3000
_MAX_ENGAGEMENT = 200
_MAX_NOTES = 6000
_TTL = 30


class CompteRenduInvalide(ValueError):
    pass


class CompteRenduNonAutorise(LookupError):
    pass


def est_compte_rendu(page: dict) -> bool:
    nom = notion_service._prop_value(notion_service._prop(page.get("properties", {}), "Nom"))
    return NOM_COMPTE_RENDU in str(nom or "")


def _texte(valeur, maximum: int) -> str:
    return re.sub(r"[ \t]+", " ", str(valeur or "")).strip()[:maximum]


def _date_iso(valeur) -> str:
    try:
        return date.fromisoformat(str(valeur or "")[:10]).isoformat()
    except ValueError:
        return date.today().isoformat()


def _lire(page: dict) -> dict:
    props = page.get("properties", {})
    brut = notion_service._prop_value(notion_service._prop(props, "Données (JSON)")) or "{}"

    try:
        donnees = json.loads(brut)
    except json.JSONDecodeError:
        donnees = {}

    if not isinstance(donnees, dict):
        donnees = {}

    engagements = [
        {"id": str(e.get("id")), "texte": str(e.get("texte") or ""), "fait": bool(e.get("fait"))}
        for e in donnees.get("engagements") or [] if isinstance(e, dict) and e.get("id")
    ]
    return {
        "id": page["id"],
        "date_point": donnees.get("date_point") or notion_service._prop_value(notion_service._prop(props, "Date")),
        "resume": str(donnees.get("resume") or ""),
        "engagements": engagements,
        "evenement_id": donnees.get("evenement_id"),
        "cree_le": page.get("created_time"),
    }


def lister(client_page_id: str) -> list[dict]:
    """Comptes rendus de l'eleve, du plus recent au plus ancien."""
    cle = f"comptes_rendus:{client_page_id}"
    en_cache = notion_service._cache_get(cle)

    if en_cache is not None:
        return en_cache

    pages = notion_service._query_data_source(
        notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"and": [
            {"property": "Client", "relation": {"contains": client_page_id}},
            {"property": "Nom", "title": {"contains": NOM_COMPTE_RENDU}},
        ]},
    )
    comptes_rendus = sorted(
        (_lire(page) for page in pages),
        key=lambda c: (c["date_point"] or "", c["cree_le"] or ""),
        reverse=True,
    )
    return notion_service._cache_set(cle, comptes_rendus, _TTL)


def dernier(client_page_id: str) -> dict | None:
    comptes_rendus = lister(client_page_id)
    return comptes_rendus[0] if comptes_rendus else None


def _verifier_formule(client_page_id: str) -> dict:
    client = notion_service._get_page(client_page_id)
    props = client.get("properties", {})

    if notion_service._est_parcours_autonome(notion_service._prop_value(notion_service._prop(props, "Parcours"))):
        raise CompteRenduNonAutorise("Formule Autonome : pas de point individuel.")

    return client


def _engagements_valides(engagements) -> list[dict]:
    propres = []

    for engagement in engagements or []:
        texte = _texte(engagement.get("texte") if isinstance(engagement, dict) else engagement, _MAX_ENGAGEMENT)

        if texte:
            propres.append({"id": secrets.token_hex(4), "texte": texte, "fait": False})

    return propres[:MAX_ENGAGEMENTS]


def _enregistrer(page_id: str, compte_rendu: dict) -> None:
    contenu = json.dumps({
        "version": 1,
        "date_point": compte_rendu["date_point"],
        "resume": compte_rendu["resume"],
        "engagements": compte_rendu["engagements"],
        "evenement_id": compte_rendu.get("evenement_id"),
    }, ensure_ascii=False)
    notion_service._update_page(page_id, {
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })


def creer(client_page_id: str, resume: str, engagements, date_point: str | None = None, evenement_id: str | None = None) -> dict:
    resume = _texte(resume, _MAX_RESUME)
    engagements = _engagements_valides(engagements)

    if not resume and not engagements:
        raise CompteRenduInvalide("Écris au moins un résumé ou un engagement.")

    client = _verifier_formule(client_page_id)
    quand = _date_iso(date_point)
    jour = date.fromisoformat(quand).strftime("%d/%m/%Y")
    compte_rendu = {"date_point": quand, "resume": resume, "engagements": engagements, "evenement_id": evenement_id}
    contenu = json.dumps({"version": 1, **compte_rendu}, ensure_ascii=False)
    page = notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{notion_service.client_display_name(client) or 'Client'} — {NOM_COMPTE_RENDU} du {jour}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Date": {"date": {"start": quand}},
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })
    notion_service._cache_clear(f"comptes_rendus:{client_page_id}")
    return {**compte_rendu, "id": page.get("id"), "cree_le": page.get("created_time")}


def cocher(client_page_id: str, compte_rendu_id: str, engagement_id: str, fait: bool) -> dict:
    """L'eleve coche un engagement qu'il a tenu (ou le decoche)."""
    compte_rendu = next((c for c in lister(client_page_id) if c["id"].replace("-", "") == compte_rendu_id.replace("-", "")), None)

    if not compte_rendu:
        raise CompteRenduNonAutorise("Compte rendu introuvable.")

    engagements = [dict(e) for e in compte_rendu["engagements"]]
    cible = next((e for e in engagements if e["id"] == engagement_id), None)

    if not cible:
        raise CompteRenduNonAutorise("Engagement introuvable.")

    cible["fait"] = bool(fait)
    compte_rendu = {**compte_rendu, "engagements": engagements}
    _enregistrer(compte_rendu["id"], compte_rendu)
    notion_service._cache_clear(f"comptes_rendus:{client_page_id}")
    return compte_rendu


# --- Mise en forme par Idris ------------------------------------------------------

_MISE_EN_FORME_SYSTEME = """Tu aides Rony, coach commercial de RL-eVolution, à mettre au propre ses notes d'un point individuel avec un élève (indépendant ou TPE des Antilles-Guyane). Les notes sont souvent dictées : phrases incomplètes, répétitions.

RÈGLES
- Garde UNIQUEMENT ce que disent les notes. N'invente aucun chiffre, aucun fait, aucune promesse.
- Le résumé s'adresse à l'élève : tutoiement, voix de Rony (« on a vu », « tu as »), 3 à 6 phrases, sans titre ni markdown.
- Les engagements sont les actions que l'élève s'engage à faire d'ici le prochain point : 1 à 5, chacune courte, concrète, avec une échéance ou un chiffre si les notes en donnent. Commence chaque engagement par un verbe à l'infinitif.

Réponds uniquement avec un objet JSON : {"resume": "...", "engagements": ["...", "..."]}"""


def mettre_en_forme(notes: str, prenom: str | None = None) -> dict:
    notes = _texte(notes, _MAX_NOTES)

    if not notes:
        raise CompteRenduInvalide("Dicte ou écris d'abord tes notes.")

    message = (f"Élève : {prenom}\n\n" if prenom else "") + f"Notes de Rony :\n{notes}"
    texte = ia_service.generer(_MISE_EN_FORME_SYSTEME, [{"role": "user", "texte": message}], temperature=0.3, max_tokens=700)
    debut, fin = texte.find("{"), texte.rfind("}")

    try:
        donnees = json.loads(texte[debut:fin + 1]) if debut >= 0 and fin > debut else {}
    except json.JSONDecodeError:
        donnees = {}

    resume = _texte(donnees.get("resume"), _MAX_RESUME) if isinstance(donnees, dict) else ""
    engagements = [
        _texte(e, _MAX_ENGAGEMENT) for e in (donnees.get("engagements") or [] if isinstance(donnees, dict) else [])
        if isinstance(e, str) and e.strip()
    ][:MAX_ENGAGEMENTS]

    if not resume and not engagements:
        raise RuntimeError("Mise en forme illisible")

    return {"resume": resume, "engagements": engagements}


def lignes_pour_bilan(client_page_id: str) -> list[str]:
    """Engagements du dernier point, pour que le retour d'Idris sur le bilan
    hebdomadaire les reprenne."""
    compte_rendu = dernier(client_page_id)

    if not compte_rendu or not compte_rendu["engagements"]:
        return []

    try:
        ecart = (datetime.now(timezone.utc).date() - date.fromisoformat(str(compte_rendu["date_point"])[:10])).days
    except ValueError:
        ecart = 0

    if ecart > 21:
        return []

    lignes = [f"Ses engagements pris avec Rony au point du {compte_rendu['date_point']} (cite-les et fais le point dessus) :"]
    lignes.extend(f"- {e['texte']} ({'coché comme fait' if e['fait'] else 'pas encore coché'})" for e in compte_rendu["engagements"])
    return lignes
