"""Rythme des points individuels et collectifs, par formule (28/10/2026).

Rony regle, pour chaque formule, quand tombent les points avec ses eleves
(jour du premier point, ecart entre deux points, nombre, duree). Le portail en
tire des dates suggerees selon le jour de parcours de chaque eleve, et les
rapproche des RDV deja poses dans son Google Agenda :
  - point individuel : le n-ieme RDV coaching de l'eleve (cree depuis le
    portail) correspond au n-ieme point du rythme ;
  - point collectif : un « Point collectif » de la meme formule, a 3 jours
    pres de la date suggeree.

Valeurs par defaut reprises des offres :
  Coaching 90 jours : 9 seances individuelles d'1 h, une tous les 10 jours.
  Atelier : 4 sessions collectives hebdomadaires + un point individuel de
            20 min en fin d'atelier.
  Autonome : 1 point collectif par mois.
Les reglages de Rony sont gardes dans son agenda (agenda_service.reglages).
"""

from datetime import date, datetime, timedelta

from backend.services import agenda_service

FORMULES = ("Coaching 90 jours", "Atelier", "Autonome")
TYPES_POINT = ("individuel", "collectif")

DEFAUT = {
    "Coaching 90 jours": {
        "individuel": {"actif": True, "debut": 0, "tous_les": 10, "nombre": 9, "duree": 60},
        "collectif": {"actif": False, "debut": 30, "tous_les": 30, "nombre": 3, "duree": 60},
    },
    "Atelier": {
        "individuel": {"actif": True, "debut": 21, "tous_les": 7, "nombre": 1, "duree": 20},
        "collectif": {"actif": True, "debut": 0, "tous_les": 7, "nombre": 4, "duree": 120},
    },
    "Autonome": {
        "individuel": {"actif": False, "debut": 0, "tous_les": 30, "nombre": 1, "duree": 60},
        "collectif": {"actif": True, "debut": 30, "tous_les": 30, "nombre": 3, "duree": 60},
    },
}

_CLE_REGLAGE = "rythme"
_TOLERANCE_COLLECTIF = 3
DUREES = (15, 20, 30, 45, 60, 90, 120, 180)


class RythmeInvalide(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _copie(regles: dict) -> dict:
    return {f: {t: dict(regles[f][t]) for t in TYPES_POINT} for f in FORMULES}


def valider(regles: dict) -> dict:
    propres = _copie(DEFAUT)

    for formule in FORMULES:
        for type_ in TYPES_POINT:
            regle = ((regles or {}).get(formule) or {}).get(type_)

            if regle is None:
                continue

            try:
                actif = bool(regle.get("actif"))
                debut = int(regle.get("debut"))
                tous_les = int(regle.get("tous_les"))
                nombre = int(regle.get("nombre"))
                duree = int(regle.get("duree"))
            except (AttributeError, TypeError, ValueError):
                raise RythmeInvalide("Rythme invalide.")

            if not 0 <= debut <= 120 or not 1 <= tous_les <= 60 or not 1 <= nombre <= 20 or duree not in DUREES:
                raise RythmeInvalide(f"Rythme invalide ({formule}, point {type_}).")

            propres[formule][type_] = {"actif": actif, "debut": debut, "tous_les": tous_les, "nombre": nombre, "duree": duree}

    return propres


def lire() -> dict:
    """Rythme regle par Rony, ou les valeurs par defaut."""
    try:
        return valider(agenda_service.lire_reglage(_CLE_REGLAGE) or {})
    except RythmeInvalide:
        return _copie(DEFAUT)


def enregistrer(regles: dict) -> dict:
    propres = valider(regles)
    agenda_service.ecrire_reglage(_CLE_REGLAGE, propres)
    return propres


def _date(valeur) -> date | None:
    try:
        return datetime.fromisoformat(str(valeur)[:10]).date()
    except (TypeError, ValueError):
        return None


def dates_suggerees(formule: str, date_demarrage, regles: dict) -> list[dict]:
    depart = _date(date_demarrage)

    if depart is None or formule not in regles:
        return []

    points = []

    for type_ in TYPES_POINT:
        regle = regles[formule][type_]

        if not regle["actif"]:
            continue

        for numero in range(regle["nombre"]):
            jour = regle["debut"] + numero * regle["tous_les"]
            points.append({
                "type": type_,
                "numero": numero + 1,
                "total": regle["nombre"],
                "jour": jour,
                "date": (depart + timedelta(days=jour)).isoformat(),
                "duree": regle["duree"],
            })

    points.sort(key=lambda p: (p["date"], p["type"]))
    return points


def _resume(evt: dict) -> dict:
    return {"id": evt["id"], "debut": evt["debut"], "fin": evt["fin"], "lieu": evt.get("lieu") or "", "lien": evt.get("lien")}


def rapprocher(points: list[dict], eleve_id: str, formule: str, evenements: list[dict], maintenant: str) -> list[dict]:
    """Ajoute a chaque point son statut : fait, planifie ou a_planifier."""
    individuels = sorted(
        (e for e in evenements if e.get("eleve_id") == eleve_id and e.get("type") == "rdv"),
        key=lambda e: e["debut"],
    )
    collectifs = [e for e in evenements if e.get("type") == "collectif" and e.get("parcours") == formule]
    rang = 0
    resultat = []

    for point in points:
        evt = None

        if point["type"] == "individuel":
            if rang < len(individuels):
                evt = individuels[rang]
                rang += 1
        else:
            cible = _date(point["date"])
            proches = [
                e for e in collectifs
                if abs((_date(e["debut"]) - cible).days) <= _TOLERANCE_COLLECTIF
            ]
            evt = min(proches, key=lambda e: abs((_date(e["debut"]) - cible).days)) if proches else None

        statut = "a_planifier" if evt is None else ("fait" if evt["fin"] < maintenant else "planifie")
        resultat.append({**point, "statut": statut, "evenement": _resume(evt) if evt else None})

    return resultat


def hors_rythme(points: list[dict], eleve_id: str, formule: str, evenements: list[dict], maintenant: str, date_demarrage=None) -> list[dict]:
    """RDV a venir de l'eleve que le rythme n'a rattache a aucun point : formule
    sans points individuels (Autonome), RDV en plus du rythme, eleve sans date
    de demarrage. L'eleve doit quand meme les voir dans son espace."""
    pris = {p["evenement"]["id"] for p in points if p.get("evenement")}
    depart = _date(date_demarrage)
    autres = []

    for evt in evenements:
        if evt["id"] in pris or evt["fin"] < maintenant:
            continue

        if evt.get("type") in ("rdv", "autre") and evt.get("eleve_id") == eleve_id:
            type_ = "individuel"
        elif evt.get("type") == "collectif" and evt.get("parcours") == formule:
            type_ = "collectif"
        else:
            continue

        jour = _date(evt["debut"])

        try:
            duree = int((datetime.fromisoformat(evt["fin"]) - datetime.fromisoformat(evt["debut"])).total_seconds() // 60)
        except ValueError:
            duree = 0

        autres.append({
            "type": type_,
            "numero": 0,
            "total": 0,
            "jour": (jour - depart).days if depart and jour else None,
            "date": jour.isoformat() if jour else str(evt["debut"])[:10],
            "duree": duree,
            "statut": "planifie",
            "evenement": _resume(evt),
        })

    return autres
