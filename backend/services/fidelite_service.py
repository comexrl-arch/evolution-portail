# Fidelite et preuves (lot 4, decision de Rony du 25/10/2026) :
# - objectif 90 jours saisi par le client a l'accueil guide ;
# - lien de partage en lecture seule de sa progression (banquier, associe...) ;
# - avis du client a J90, cite seulement avec son accord ;
# - recap hebdomadaire par email « ta semaine en 3 chiffres », envoye par n8n.

import json
import os
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.services import ia_service, notion_service, portal_auth_service

_MAX_OBJECTIF = 300
_MAX_AVIS = 1500
_NOM_AVIS = "Avis J90"
PARTAGE_JOURS = 30
_SEL_PARTAGE = "partage-progression"
URL_PORTAIL = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").split(",")[0].strip().rstrip("/")


# --- Objectif 90 jours -------------------------------------------------------

def enregistrer_objectif(client_page_id: str, objectif: str) -> str:
    texte = " ".join(str(objectif or "").split())

    if not texte or len(texte) > _MAX_OBJECTIF:
        raise ValueError("Objectif vide ou trop long")

    notion_service._update_page(client_page_id, {"Objectif 90j": {"rich_text": [{"text": {"content": texte}}]}})
    notion_service._cache_clear(f"dashboard:{client_page_id}")
    return texte


# --- Lien de partage ---------------------------------------------------------

def _serializer() -> URLSafeTimedSerializer:
    if not portal_auth_service.SECRET_KEY:
        raise RuntimeError("PORTAL_SECRET_KEY manquant.")

    return URLSafeTimedSerializer(portal_auth_service.SECRET_KEY, salt=_SEL_PARTAGE)


def creer_lien_partage(client_page_id: str) -> dict:
    jeton = _serializer().dumps({"client_page_id": client_page_id, "type": "partage"})
    return {"jeton": jeton, "url": f"{URL_PORTAIL}/?partage={jeton}", "jours": PARTAGE_JOURS}


def client_du_partage(jeton: str) -> str:
    try:
        donnees = _serializer().loads(jeton, max_age=PARTAGE_JOURS * 24 * 3600)
    except SignatureExpired as error:
        raise ValueError("Ce lien de partage a expiré.") from error
    except BadSignature as error:
        raise ValueError("Lien de partage invalide.") from error

    if donnees.get("type") != "partage" or not donnees.get("client_page_id"):
        raise ValueError("Lien de partage invalide.")

    return donnees["client_page_id"]


def progression_publique(dashboard: dict) -> dict:
    """Ce qu'un tiers voit : prenom, formule, avancement et chiffres. Jamais
    les reponses aux fiches, l'email, le telephone ni le nom de famille."""
    perso = dashboard.get("personnalisation") or {}
    kpi_champs = ("valeur_j0", "valeur_j30", "valeur_j60", "valeur_j90")

    return {
        "prenom": (dashboard.get("nom") or "").split(" ")[0],
        "parcours": dashboard.get("parcours"),
        "date_demarrage": dashboard.get("date_demarrage"),
        "fiches": [{"etat": f.get("etat"), "module": f.get("module")} for f in dashboard.get("fiches") or []],
        "kpi": [{"nom": k.get("nom"), **{c: k.get(c) for c in kpi_champs}} for k in dashboard.get("kpi") or []],
        "personnalisation": {c: perso.get(c) for c in ("scores_diagnostic", "scores", "total", "total_actuel", "chiffres")} if perso else None,
        "regularite": dashboard.get("regularite"),
    }


# --- Avis J90 ----------------------------------------------------------------

def enregistrer_avis(client_page_id: str, dashboard: dict, note: int, avis: str, accord_publication: bool, signature: str = "") -> None:
    from backend.services.idris_service import bilan_final_disponible

    if not bilan_final_disponible(dashboard):
        raise LookupError("Avis pas encore ouvert")

    avis = str(avis or "").strip()

    if not 0 <= int(note) <= 10 or not avis or len(avis) > _MAX_AVIS or len(signature or "") > 120:
        raise ValueError("Avis invalide")

    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contenu = json.dumps({
        "note_sur_10": int(note),
        "avis": avis,
        "accord_publication": bool(accord_publication),
        "signature_souhaitee": (signature or "").strip() if accord_publication else "",
    }, ensure_ascii=False)
    notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{dashboard.get('nom') or 'Client'} — {_NOM_AVIS} — {jour}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Date": {"date": {"start": jour}},
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })


# --- Recap hebdomadaire --------------------------------------------------------

_SYSTEME_RECAP = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-Evolution). Tu écris UNE phrase d'encouragement (25 mots au plus) pour le récap hebdomadaire d'un client, à partir de ses chiffres de la semaine. Tutoiement, chaleureux, concret, sans flatterie. Ne cite que les chiffres fournis, n'en invente aucun. Réponds uniquement avec la phrase."""


def _phrase_idris(prenom: str, semaine: dict | None, serie: int) -> str:
    if semaine is None:
        return f"{prenom}, cette semaine on reprend le rythme : un bilan de 5 minutes vendredi, et tes chiffres reparlent pour toi."

    secours = f"Bravo {prenom} : {serie} semaine{'s' if serie > 1 else ''} de bilan d'affilée. Garde ce rythme, c'est lui qui fait les résultats."

    if not ia_service.enabled():
        return secours

    try:
        donnees = f"Prénom : {prenom}. Semaine : {semaine['contacts']:g} contacts, {semaine['rdv']:g} rendez-vous, {semaine['ventes']:g} ventes. Semaines de bilan d'affilée : {serie}."
        phrase = ia_service.generer(_SYSTEME_RECAP, [{"role": "user", "texte": donnees}], temperature=0.7, max_tokens=120).strip()
        return phrase or secours
    except Exception as error:
        notion_service.logger.warning("Phrase du recap indisponible (%s)", error)
        return secours


def _prochaine_fiche(dashboard: dict) -> str | None:
    for fiche in dashboard.get("fiches") or []:
        if fiche.get("etat") != "Terminé" and "Bloqué" not in str(fiche.get("acces") or ""):
            return (fiche.get("nom") or "").split(" - ", 1)[-1] or None

    return None


def recap_du_client(client_page_id: str, email: str) -> dict | None:
    dashboard = notion_service.get_client_dashboard(client_page_id)
    jour = notion_service._jour_parcours(dashboard.get("date_demarrage"))

    if jour is None or jour < 7:
        return None

    prenom = (dashboard.get("nom") or "").split(" ")[0] or "Bonjour"
    bilan = next((f for f in dashboard.get("fiches") or [] if f.get("master_id") == notion_service._BILAN_HEBDO_MASTER_ID), None)
    historique = notion_service._historique_bilans(bilan["id"]) if bilan else []
    semaine = historique[-1] if historique else None
    serie = (dashboard.get("regularite") or {}).get("serie") or 0
    prochaine = _prochaine_fiche(dashboard)
    chiffres = None if semaine is None else {
        "semaine_du": semaine["semaine_du"], "contacts": semaine["contacts"], "rdv": semaine["rdv"], "ventes": semaine["ventes"],
    }
    lignes = [f"Bonjour {prenom},", "", f"Voici ta semaine en 3 chiffres (J{jour} de ton parcours eVolution 2.0) :"]

    if chiffres:
        lignes += [
            f"- Contacts : {chiffres['contacts']:g}",
            f"- Rendez-vous : {chiffres['rdv']:g}",
            f"- Ventes : {chiffres['ventes']:g}",
            f"(bilan de la semaine du {chiffres['semaine_du']})",
        ]
    else:
        lignes.append("- Pas encore de bilan hebdomadaire rempli.")

    lignes += ["", "Le mot d'Idris : " + _phrase_idris(prenom, semaine, serie)]

    if prochaine:
        lignes += ["", f"Ta prochaine étape : {prochaine}."]

    lignes += ["", f"Ouvre ton espace : {URL_PORTAIL}", "", "Rony, RL-Evolution"]

    return {
        "client_page_id": client_page_id,
        "email": email,
        "prenom": prenom,
        "jour": jour,
        "chiffres": chiffres,
        "serie": serie,
        "prochaine_etape": prochaine,
        "objet": f"{prenom}, ta semaine en 3 chiffres",
        "texte": "\n".join(lignes),
    }


def recaps_hebdo() -> list[dict]:
    """Clients en cours, avec un email, et qui n'ont pas coche « Récap hebdo
    désactivé » dans [DB] Clients (propriete facultative)."""
    recaps = []

    for row in notion_service._query_data_source(notion_service.CLIENTS_DATA_SOURCE_ID):
        props = row.get("properties", {})
        email = notion_service._prop_value(notion_service._prop(props, "E-mail"))

        if notion_service._prop_value(notion_service._prop(props, "État")) != "En cours" or not email:
            continue

        if notion_service._prop_value(notion_service._prop(props, "Récap hebdo désactivé")):
            continue

        try:
            recap = recap_du_client(row["id"], email)
        except Exception as error:
            notion_service.logger.warning("Recap %s impossible (%s)", row.get("id"), error)
            recap = None

        if recap:
            recaps.append(recap)

    return recaps
