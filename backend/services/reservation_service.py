"""Reservation d'un RDV par l'eleve depuis son espace (29/10/2026).

L'eleve voit les creneaux libres de Rony (ses plages "Mes creneaux", moins ce
qui est deja pris dans ses agendas) et en reserve un. Le RDV est cree dans le
Google Agenda de Rony comme un RDV coaching pose depuis l'Espace Coach, avec
en plus reserve_par=eleve : Rony le deplace ou l'annule comme les autres.

Regles (valeurs de travail, a ajuster avec Rony) :
- seules les formules dont le rythme a des points individuels actifs peuvent
  reserver (par defaut Coaching et Atelier, pas Autonome) ;
- un seul RDV individuel a venir a la fois ;
- au plus tot 24 h a l'avance, au plus tard 21 jours ;
- la duree est celle du point individuel de la formule (Coaching 60 min,
  Atelier 20 min par defaut) ;
- l'eleve peut annuler un RDV qu'il a reserve lui-meme, jusqu'a 24 h avant.
"""

import threading
from datetime import datetime, timedelta

from backend.services import agenda_service, rythme_service

DELAI_HEURES = 24
HORIZON_JOURS = 21
RESERVE_PAR_ELEVE = "eleve"

# Deux reservations en meme temps sur le meme creneau : la seconde relit
# l'agenda apres la premiere et voit le creneau pris.
_verrou = threading.Lock()


class ReservationRefusee(ValueError):
    # message : phrase fixe, sure a afficher a l'eleve.
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _decaler(date_heure: str, minutes: int) -> str:
    return (datetime.fromisoformat(date_heure) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


def duree_rdv(parcours: str, regles: dict) -> int | None:
    """Duree du point individuel de la formule, None si la formule n'en a pas."""
    individuel = (regles.get(parcours) or {}).get("individuel") or {}
    return int(individuel.get("duree") or 60) if individuel.get("actif") else None


def creneaux_libres(plages: list[dict], evenements: list[dict], duree: int, apres: str, avant: str) -> list[dict]:
    """Plages decoupees selon la duree, sans ce qui est deja pris (meme calcul
    que creneauxLibres dans CoachAgenda.jsx)."""
    occupes = [e for e in evenements if not e.get("journee") and not e.get("libre")]
    libres = []

    for plage in plages:
        debut = plage["debut"]

        while _decaler(debut, duree) <= plage["fin"]:
            fin = _decaler(debut, duree)

            if apres <= debut < avant and not any(e["debut"] < fin and e["fin"] > debut for e in occupes):
                libres.append({"debut": debut, "fin": fin})

            debut = fin

    return sorted({c["debut"]: c for c in libres}.values(), key=lambda c: c["debut"])


def _secondaires() -> list[str]:
    # Ses autres agendas affiches dans Google (Perso...) comptent comme occupes.
    liste = agenda_service.agendas() or []
    return [a["id"] for a in liste if a["coche"] and not a["principal"]]


def _rdv_a_venir(evenements: list[dict], eleve_id: str, maintenant: str) -> dict | None:
    for evt in sorted(evenements, key=lambda e: e["debut"]):
        if evt.get("portail") and evt.get("eleve_id") == eleve_id and evt.get("type") in ("rdv", "autre") and evt["fin"] > maintenant:
            return evt
    return None


def situation(eleve: dict, maintenant: str) -> dict:
    """Ce que l'eleve peut faire : reserver (avec la liste des creneaux) ou pas."""
    regles = rythme_service.lire()
    duree = duree_rdv(eleve["parcours"], regles)

    if duree is None:
        return {"possible": False, "raison": "formule", "creneaux": []}

    apres = _decaler(maintenant, DELAI_HEURES * 60)
    avant = _decaler(maintenant, HORIZON_JOURS * 24 * 60)
    evenements, plages = agenda_service.lister_complet(maintenant[:10], _decaler(avant, 24 * 60)[:10], _secondaires())
    deja = _rdv_a_venir(evenements, eleve["client_page_id"], maintenant)

    if deja:
        return {"possible": False, "raison": "deja", "creneaux": [], "duree": duree}

    libres = creneaux_libres(plages, evenements, duree, apres, avant)
    return {"possible": bool(libres), "raison": None if libres else "complet", "creneaux": libres, "duree": duree}


def reserver(eleve: dict, debut: str, maintenant: str) -> dict:
    with _verrou:
        etat = situation(eleve, maintenant)

        if etat["raison"] == "formule":
            raise ReservationRefusee("Ta formule ne comprend pas de RDV individuel avec Rony.")

        if etat["raison"] == "deja":
            raise ReservationRefusee("Tu as déjà un RDV à venir avec Rony.")

        creneau = next((c for c in etat["creneaux"] if c["debut"] == debut), None)

        if creneau is None:
            raise ReservationRefusee("Ce créneau vient d'être pris. Choisis-en un autre.")

        return agenda_service.creer({
            "type": "rdv",
            "eleve_id": eleve["client_page_id"],
            "eleve_nom": eleve.get("nom") or "",
            "description": "Réservé par l'élève depuis son espace RL-eVolution.",
            "debut": creneau["debut"],
            "fin": creneau["fin"],
            "reserve_par": RESERVE_PAR_ELEVE,
        })


def annulable(evt: dict, eleve_id: str, maintenant: str) -> bool:
    return (
        evt.get("reserve_par") == RESERVE_PAR_ELEVE
        and evt.get("eleve_id") == eleve_id
        and evt["debut"] >= _decaler(maintenant, DELAI_HEURES * 60)
    )


def annuler(evenement_id: str, eleve_id: str, maintenant: str) -> dict:
    try:
        evt = agenda_service.lire(evenement_id)
    except (agenda_service.EvenementIntrouvable, agenda_service.EvenementProtege):
        raise ReservationRefusee("Ce RDV est introuvable.")

    if evt.get("eleve_id") != eleve_id:
        raise ReservationRefusee("Ce RDV est introuvable.")

    if not annulable(evt, eleve_id, maintenant):
        raise ReservationRefusee("Ce RDV ne peut plus être annulé ici : préviens Rony directement.")

    agenda_service.supprimer(evenement_id)
    return evt
