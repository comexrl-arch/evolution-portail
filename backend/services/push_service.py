# Notifications sur le telephone (decision de Rony du 27/10/2026) : Web Push
# standard, recu par le portail installe (Android, iPhone a partir d'iOS 16.4
# quand le portail est ajoute a l'ecran d'accueil) et par les navigateurs
# d'ordinateur.
#
# - Cles VAPID : variables VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY (Render).
#   Sans elles, le portail ne propose pas les notifications.
# - Abonnements : propriete texte « Notifications push » de [DB] Clients
#   (liste JSON, 5 appareils au plus).
# - Envois : retour d'Idris pret (Autonome), et chaque matin via n8n
#   (/automation/notifications-du-jour) : fiche qui s'ouvre, relances du carnet.

import json
import logging
import os
from datetime import date, datetime, timezone

from backend.services import notion_service, prospects_service

logger = logging.getLogger("uvicorn.error")

PROPRIETE = "Notifications push"
_MAX_APPAREILS = 5
URL_PORTAIL = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").split(",")[0].strip().rstrip("/")


def cle_publique() -> str | None:
    return os.getenv("VAPID_PUBLIC_KEY") or None


def enabled() -> bool:
    return bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY"))


# --- Abonnements -------------------------------------------------------------------

def _lire_abonnements(props: dict) -> list[dict]:
    brut = notion_service._prop_value(notion_service._prop(props, PROPRIETE)) or "[]"

    try:
        liste = json.loads(brut)
    except json.JSONDecodeError:
        return []

    return [a for a in liste if isinstance(a, dict) and a.get("endpoint")] if isinstance(liste, list) else []


def abonnements(client_page_id: str) -> list[dict]:
    return _lire_abonnements(notion_service._get_page(client_page_id).get("properties", {}))


def _ecrire(client_page_id: str, liste: list[dict]) -> None:
    contenu = json.dumps(liste, separators=(",", ":"))
    notion_service._update_page(client_page_id, {
        PROPRIETE: {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })


def abonnement_valide(abonnement: dict) -> dict:
    endpoint = str((abonnement or {}).get("endpoint") or "")
    cles = (abonnement or {}).get("keys") or {}

    if not endpoint.startswith("https://") or len(endpoint) > 1000:
        raise ValueError("Abonnement invalide")

    if not isinstance(cles, dict) or not cles.get("p256dh") or not cles.get("auth"):
        raise ValueError("Abonnement invalide")

    return {"endpoint": endpoint, "keys": {"p256dh": str(cles["p256dh"])[:200], "auth": str(cles["auth"])[:100]}}


def abonner(client_page_id: str, abonnement: dict) -> None:
    propre = abonnement_valide(abonnement)
    liste = [a for a in abonnements(client_page_id) if a["endpoint"] != propre["endpoint"]]
    _ecrire(client_page_id, (liste + [propre])[-_MAX_APPAREILS:])


def desabonner(client_page_id: str, endpoint: str) -> None:
    liste = abonnements(client_page_id)
    restants = [a for a in liste if a["endpoint"] != endpoint]

    if len(restants) != len(liste):
        _ecrire(client_page_id, restants)


# --- Envoi ---------------------------------------------------------------------------

def _envoyer_un(abonnement: dict, charge: str) -> bool:
    """True si l'abonnement est encore valable."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=abonnement,
            data=charge,
            vapid_private_key=os.getenv("VAPID_PRIVATE_KEY"),
            vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:contact@rl-evolution.fr")},
            ttl=12 * 3600,
            timeout=10,
        )
        return True

    except WebPushException as error:
        code = getattr(getattr(error, "response", None), "status_code", None)

        if code in (404, 410):
            return False
        logger.warning("Notification non envoyee (%s)", code or error)
        return True


def envoyer(client_page_id: str, titre: str, texte: str, url: str = "/", liste: list[dict] | None = None) -> int:
    """Envoie a tous les appareils du client. Retourne le nombre d'envois
    reussis. Les abonnements expires sont retires."""
    if not enabled():
        return 0

    liste = abonnements(client_page_id) if liste is None else liste

    if not liste:
        return 0

    charge = json.dumps({"titre": titre, "texte": texte, "url": url}, ensure_ascii=False)
    valables = [a for a in liste if _envoyer_un(a, charge)]

    if len(valables) != len(liste):
        try:
            _ecrire(client_page_id, valables)
        except RuntimeError as error:
            logger.warning("Abonnements expires non retires (%s)", error)

    return len(valables)


def retour_idris_pret(client_page_id: str, fiche_id: str) -> None:
    envoyer(client_page_id, "Idris t'a répondu", "Ton retour sur la fiche que tu viens d'enregistrer est prêt.", f"/?ouvrir=fiche:{fiche_id}")


# --- RDV poses par Rony dans l'Espace Coach (28/10/2026) -------------------------------

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")


def quand(debut: str) -> str:
    """'2026-10-28T11:00' -> 'mercredi 28 octobre à 11h00'"""
    d = datetime.fromisoformat(debut)
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} à {d.hour}h{d.minute:02d}"


def message_rdv(changement: str, evt: dict) -> tuple[str, str]:
    """changement : nouveau, deplace ou annule. Retourne (titre, texte)."""
    collectif = evt.get("type") == "collectif"
    nom = "Point collectif" if collectif else "Rendez-vous"
    moment = quand(evt["debut"])

    if changement == "nouveau":
        if collectif:
            return "Nouveau point collectif", f"{moment.capitalize()}. Tu le retrouves dans ton espace."
        return "Nouveau rendez-vous avec Rony", f"{moment.capitalize()}. Tu le retrouves dans ton espace."

    if changement == "deplace":
        return f"{nom} déplacé", f"Nouvelle date : {moment}."

    return f"{nom} annulé", f"Le {nom.lower()} du {moment} est annulé."


# --- Notifications du matin (n8n, chaque jour) -----------------------------------------

def _fiches_du_jour(dashboard: dict, jour: int) -> list[str]:
    atelier = notion_service._est_parcours_atelier(dashboard.get("parcours"))
    jours = notion_service._ATELIER_JOUR if atelier else notion_service._FICHE_JOUR
    noms = []

    for fiche in dashboard.get("fiches") or []:
        if jours.get(fiche.get("master_id")) == jour and fiche.get("etat") != "Terminé" and "Bloqué" not in str(fiche.get("acces") or ""):
            noms.append((fiche.get("nom") or "").split(" - ", 1)[-1])

    return noms


def message_du_jour(dashboard: dict, carnet: dict | None, aujourd_hui: date | None = None) -> dict | None:
    jour = notion_service._jour_parcours(dashboard.get("date_demarrage"))
    morceaux = []
    url = "/"

    if jour is not None:
        fiches = _fiches_du_jour(dashboard, jour)

        if len(fiches) == 1:
            morceaux.append(f"Nouvelle fiche ouverte : {fiches[0].split('. ', 1)[-1].capitalize()}.")
        elif fiches:
            morceaux.append(f"{len(fiches)} nouvelles fiches s'ouvrent aujourd'hui.")
        if fiches:
            url = "/?ouvrir=parcours"

    relances = prospects_service.a_relancer((carnet or {}).get("prospects") or [], aujourd_hui)

    if relances:
        noms = ", ".join(p["nom"] for p in relances[:2]) + ("…" if len(relances) > 2 else "")
        morceaux.append(f"{len(relances)} relance{'s' if len(relances) > 1 else ''} prévue{'s' if len(relances) > 1 else ''} aujourd'hui : {noms}.")
        url = "/?ouvrir=prospects"

    if not morceaux:
        return None

    return {"titre": "Ta journée eVolution", "texte": " ".join(morceaux), "url": url}


def notifications_du_jour() -> dict:
    if not enabled():
        return {"actif": False, "envoyees": 0, "clients": 0}

    envoyees = clients = 0

    for row in notion_service._query_data_source(notion_service.CLIENTS_DATA_SOURCE_ID):
        props = row.get("properties", {})

        if notion_service._prop_value(notion_service._prop(props, "État")) != "En cours":
            continue

        liste = _lire_abonnements(props)

        if not liste:
            continue

        try:
            dashboard = notion_service.get_client_dashboard(row["id"])
            message = message_du_jour(dashboard, prospects_service.lire(row["id"], dashboard))
        except Exception as error:
            logger.warning("Notification du jour impossible pour %s (%s)", row.get("id"), error)
            continue

        if message:
            clients += 1
            envoyees += envoyer(row["id"], message["titre"], message["texte"], message["url"], liste=liste)

    return {"actif": True, "envoyees": envoyees, "clients": clients, "le": datetime.now(timezone.utc).isoformat()}
