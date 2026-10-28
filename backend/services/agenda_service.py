"""Agenda de l'Espace Coach : le Google Agenda de Rony, lu et modifie depuis /coach.

Onglet "Agenda" (28/10/2026) : Rony voit ses vrais creneaux et cree, deplace
ou supprime les RDV de coaching et les etapes de suivi de ses eleves. Tout
reste dans SON Google Agenda : ce qui est cree ici apparait sur son telephone.

Les evenements crees par le portail portent des proprietes privees
(source=portail, type, eleve_id, eleve_nom) : seuls ceux-la sont modifiables
depuis l'Espace Coach. Ses autres evenements sont affiches en lecture seule
(creneaux occupes), pour qu'une mauvaise manipulation ne touche jamais a
un rendez-vous personnel.

Configuration (variables d'environnement, jamais dans le code) :
  GOOGLE_CALENDAR_ID : identifiant de l'agenda (en general l'adresse Gmail de
                       Rony). Avec le compte de service, cet agenda doit etre
                       partage avec l'adresse du compte de service, droit
                       "Apporter des modifications aux evenements".
  Acces Google : le meme que sheets_service (GOOGLE_SERVICE_ACCOUNT_JSON en
                 priorite, sinon l'acces OAuth GOOGLE_OAUTH_*, dont le jeton
                 doit alors couvrir l'agenda).
  AGENDA_FUSEAU : fuseau des creneaux (defaut America/Guadeloupe).

Sans configuration, l'onglet affiche la marche a suivre au lieu de planter.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

from backend.services import sheets_service

logger = logging.getLogger("uvicorn.error")

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_API = "https://www.googleapis.com/calendar/v3/calendars"

TYPES = {
    "rdv": "RDV coaching",
    "suivi": "Suivi",
    "autre": "",
}

_lock = threading.Lock()
_session = None


def fuseau() -> str:
    return os.getenv("AGENDA_FUSEAU", "").strip() or "America/Guadeloupe"


def _calendrier() -> str:
    explicite = os.getenv("GOOGLE_CALENDAR_ID", "").strip()

    if explicite:
        return explicite

    # Avec l'acces OAuth de Rony, "primary" est son agenda principal. Un compte
    # de service n'a pas d'agenda utile : l'identifiant est alors obligatoire.
    return "primary" if sheets_service._oauth_config() and not sheets_service._config() else ""


def enabled() -> bool:
    return bool(_calendrier()) and sheets_service.enabled()


def calendrier_configure() -> str | None:
    return os.getenv("GOOGLE_CALENDAR_ID", "").strip() or None


def mode_acces() -> str | None:
    # Acces Google utilise par le portail : "compte_de_service", "oauth" ou None.
    if sheets_service._config():
        return "compte_de_service"
    return "oauth" if sheets_service._oauth_config() else None


def compte_de_service() -> str | None:
    # Adresse a laquelle partager l'agenda (affichee dans la marche a suivre).
    info = sheets_service._config()
    return info.get("client_email") if info else None


def _http():
    global _session

    with _lock:
        if _session is not None:
            return _session

        from google.auth.transport.requests import AuthorizedSession

        info = sheets_service._config()

        if info:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        else:
            oauth = sheets_service._oauth_config()

            if not oauth:
                raise RuntimeError("Acces Google non configure")

            from google.oauth2.credentials import Credentials

            creds = Credentials(
                None,
                refresh_token=oauth["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=oauth["client_id"],
                client_secret=oauth["client_secret"],
                scopes=_SCOPES,
            )

        _session = AuthorizedSession(creds)
        return _session


class EvenementIntrouvable(RuntimeError):
    pass


class AgendaInaccessible(RuntimeError):
    # Google refuse l'acces a l'agenda (pas partage avec le compte de service,
    # mauvais GOOGLE_CALENDAR_ID, jeton sans le droit agenda) : c'est un
    # reglage a finir, pas une panne. L'onglet affiche alors la marche a suivre.
    pass


class EvenementProtege(RuntimeError):
    pass


class CreneauInvalide(ValueError):
    # message : phrase fixe, sure a afficher au coach.
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _appel(methode: str, suffixe: str, quoi: str, **kwargs):
    # Toute erreur Google ou reseau devient une RuntimeError connue : jamais
    # d'exception brute, qui donnerait une 500 sans en-tetes CORS (le
    # navigateur n'y voit alors qu'une "connexion impossible").
    try:
        from google.auth.exceptions import GoogleAuthError

        reponse = getattr(_http(), methode)(_url(suffixe), **kwargs)
    except GoogleAuthError as error:
        raise AgendaInaccessible(f"Google Agenda ({quoi}) identification : {type(error).__name__}") from error
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"Google Agenda ({quoi}) injoignable : {type(error).__name__}") from error

    return _check(reponse, quoi)


def _url(suffixe: str = "") -> str:
    return f"{_API}/{quote(_calendrier(), safe='')}/events{suffixe}"


def _check(response, quoi: str):
    if response.status_code in (401, 403):
        raise AgendaInaccessible(f"Google Agenda ({quoi}) {response.status_code}")

    if response.status_code == 404:
        raise EvenementIntrouvable(quoi)

    if response.status_code >= 300:
        raise RuntimeError(f"Google Agenda ({quoi}) {response.status_code} : {response.text[:300]}")

    return response


# ------------------------------------------------------------- conversions

def _local(valeur: str) -> str:
    # "2026-10-30T10:00:00-04:00" -> "2026-10-30T10:00" (heure locale du
    # fuseau demande a Google, affichee telle quelle par le portail).
    return valeur[:16]


def _vers_portail(evt: dict) -> dict:
    prive = (evt.get("extendedProperties") or {}).get("private") or {}
    debut = evt.get("start") or {}
    fin = evt.get("end") or {}
    journee = "date" in debut and "dateTime" not in debut

    return {
        "id": evt.get("id"),
        "titre": evt.get("summary") or "(Sans titre)",
        "debut": debut.get("date") if journee else _local(debut.get("dateTime", "")),
        "fin": fin.get("date") if journee else _local(fin.get("dateTime", "")),
        "journee": journee,
        "lieu": evt.get("location") or "",
        "description": evt.get("description") or "",
        "lien": evt.get("htmlLink"),
        "portail": prive.get("source") == "portail",
        "type": prive.get("type") if prive.get("source") == "portail" else None,
        "eleve_id": prive.get("eleve_id") or None,
        "eleve_nom": prive.get("eleve_nom") or None,
    }


def titre_evenement(type_: str, eleve_nom: str | None, titre: str | None) -> str:
    titre = (titre or "").strip()

    if titre:
        return titre

    libelle = TYPES.get(type_, "") or "Rendez-vous"
    return f"{libelle} · {eleve_nom}" if eleve_nom else libelle


def _corps(donnees: dict) -> dict:
    tz = fuseau()
    corps = {
        "summary": titre_evenement(donnees.get("type", "rdv"), donnees.get("eleve_nom"), donnees.get("titre")),
        "description": donnees.get("description") or "",
        "location": donnees.get("lieu") or "",
        "start": {"dateTime": f"{donnees['debut']}:00", "timeZone": tz},
        "end": {"dateTime": f"{donnees['fin']}:00", "timeZone": tz},
        "extendedProperties": {"private": {
            "source": "portail",
            "type": donnees.get("type", "rdv"),
            "eleve_id": donnees.get("eleve_id") or "",
            "eleve_nom": donnees.get("eleve_nom") or "",
        }},
    }

    if donnees.get("type") == "suivi":
        # Etape de suivi : un rappel le matin meme suffit.
        corps["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]}

    return corps


def valider_creneau(debut: str, fin: str) -> None:
    try:
        d = datetime.strptime(debut, "%Y-%m-%dT%H:%M")
        f = datetime.strptime(fin, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        raise CreneauInvalide("Créneau invalide.")

    if f <= d:
        raise CreneauInvalide("La fin doit être après le début.")

    if f - d > timedelta(hours=12):
        raise CreneauInvalide("Créneau trop long.")


# ------------------------------------------------------------- lecture

def _lire_liste(quoi: str, params: dict) -> dict:
    # Sur la liste, un 404 veut dire que l'agenda lui-meme est introuvable
    # (GOOGLE_CALENDAR_ID errone ou agenda pas partage) : reglage a finir.
    try:
        return _appel("get", "", quoi, params=params).json()
    except EvenementIntrouvable as error:
        raise AgendaInaccessible(f"Google Agenda ({quoi}) agenda introuvable") from error


def lister(debut: str, fin: str) -> list[dict]:
    """Evenements entre deux dates (AAAA-MM-JJ, fin exclue), tous agendas confondus."""
    # Marge d'un jour de chaque cote : timeMin/timeMax sont en UTC, le fuseau
    # local les decale de quelques heures. Le filtre exact se fait a la fin.
    params = {
        "timeMin": (datetime.fromisoformat(debut) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        "timeMax": (datetime.fromisoformat(fin) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "500",
        "timeZone": fuseau(),
    }

    evenements = []
    page = None

    while True:
        if page:
            params["pageToken"] = page

        data = _lire_liste("lecture", params)
        evenements.extend(
            _vers_portail(e) for e in data.get("items", []) if e.get("status") != "cancelled"
        )
        page = data.get("nextPageToken")

        if not page:
            break

    return [e for e in evenements if e["debut"][:10] < fin and (e["fin"] or e["debut"])[:10] >= debut]


def prochains(depuis: str, jours: int = 60) -> dict[str, dict]:
    """Prochain RDV ou suivi cree depuis le portail, par eleve."""
    fin = (datetime.fromisoformat(depuis[:10]) + timedelta(days=jours)).strftime("%Y-%m-%d")
    params = {
        "timeMin": (datetime.fromisoformat(depuis[:10]) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        "timeMax": f"{fin}T00:00:00Z",
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "250",
        "timeZone": fuseau(),
        "privateExtendedProperty": "source=portail",
    }
    data = _lire_liste("prochains", params)
    par_eleve: dict[str, dict] = {}

    for brut in data.get("items", []):
        if brut.get("status") == "cancelled":
            continue

        evt = _vers_portail(brut)

        if evt["eleve_id"] and evt["debut"] >= depuis and evt["eleve_id"] not in par_eleve:
            par_eleve[evt["eleve_id"]] = evt

    return par_eleve


# ------------------------------------------------------------- ecriture

def _evenement_portail(evenement_id: str) -> dict:
    brut = _appel("get", f"/{quote(evenement_id, safe='')}", "lecture evenement").json()
    prive = (brut.get("extendedProperties") or {}).get("private") or {}

    if prive.get("source") != "portail":
        raise EvenementProtege(evenement_id)

    return brut


def creer(donnees: dict) -> dict:
    valider_creneau(donnees.get("debut"), donnees.get("fin"))
    return _vers_portail(_appel("post", "", "creation", json=_corps(donnees)).json())


def modifier(evenement_id: str, donnees: dict) -> dict:
    brut = _evenement_portail(evenement_id)
    prive = brut["extendedProperties"]["private"]
    complet = {
        "type": prive.get("type", "rdv"),
        "eleve_id": prive.get("eleve_id"),
        "eleve_nom": prive.get("eleve_nom"),
        "titre": brut.get("summary"),
        "description": brut.get("description"),
        "lieu": brut.get("location"),
        "debut": _local((brut.get("start") or {}).get("dateTime", "")),
        "fin": _local((brut.get("end") or {}).get("dateTime", "")),
    }

    # Changement d'eleve ou de type sans titre saisi : le titre automatique suit.
    if ("eleve_id" in donnees or "type" in donnees) and "titre" not in donnees:
        complet["titre"] = None

    complet.update({k: v for k, v in donnees.items() if v is not None or k == "titre"})
    valider_creneau(complet["debut"], complet["fin"])
    corps = _corps(complet)
    return _vers_portail(_appel("patch", f"/{quote(evenement_id, safe='')}", "modification", json=corps).json())


def supprimer(evenement_id: str) -> None:
    _evenement_portail(evenement_id)
    _appel("delete", f"/{quote(evenement_id, safe='')}", "suppression")
