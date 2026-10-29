# Tests du 28/10/2026 : rythme des points individuels et collectifs (dates
# suggerees selon le jour de parcours, rapprochement avec les RDV de l'agenda,
# reglages de Rony). Entierement mockes : ni Google, ni Notion, ni reseau.
# Lancer : python test_rythme_points.py

import json
import os
import sys
from unittest.mock import patch

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"type": "service_account", "client_email": "portail@projet.iam.gserviceaccount.com"})
os.environ["GOOGLE_CALENDAR_ID"] = "rony@gmail.com"

import portal_main
from backend.services import agenda_service, eleves_service, rythme_service

passed = 0
failed = 0
CLE = "cle-coach-test"


def check(label, condition):
    global passed, failed

    if condition:
        passed += 1
        print(f"  PASS - {label}")
    else:
        failed += 1
        print(f"  FAIL - {label}")


def statut(fonction, *args, **kwargs):
    try:
        return 200, fonction(*args, **kwargs)
    except HTTPException as error:
        return error.status_code, error.detail


def evt(id_, debut, fin, type_="rdv", eleve_id=None, parcours=None):
    return {"id": id_, "debut": debut, "fin": fin, "type": type_, "eleve_id": eleve_id, "parcours": parcours,
            "lieu": "Meet", "lien": "https://cal/x", "portail": True, "journee": False}


print("\n1. Dates suggerees par formule (valeurs par defaut des offres)")
defaut = rythme_service.valider({})
coaching = rythme_service.dates_suggerees("Coaching 90 jours", "2026-10-01", defaut)
check("Coaching : 9 points individuels, un tous les 10 jours",
      [p["jour"] for p in coaching] == [0, 10, 20, 30, 40, 50, 60, 70, 80] and {p["type"] for p in coaching} == {"individuel"})
check("Coaching : dates calculees depuis le demarrage", coaching[1]["date"] == "2026-10-11" and coaching[0]["duree"] == 60)
atelier = rythme_service.dates_suggerees("Atelier", "2026-10-05", defaut)
check("Atelier : 4 collectifs hebdo + 1 individuel de 20 min a J21",
      [(p["type"], p["jour"]) for p in atelier] == [("collectif", 0), ("collectif", 7), ("collectif", 14), ("collectif", 21), ("individuel", 21)]
      and atelier[-1]["duree"] == 20)
autonome = rythme_service.dates_suggerees("Autonome", "2026-10-01", defaut)
check("Autonome : un point collectif par mois (J30, J60, J90)", [(p["type"], p["jour"]) for p in autonome] == [("collectif", 30), ("collectif", 60), ("collectif", 90)])
check("sans date de demarrage : aucun point", rythme_service.dates_suggerees("Coaching 90 jours", None, defaut) == [])

print("\n2. Rapprochement avec l'agenda")
evenements = [
    evt("a", "2026-10-01T10:00", "2026-10-01T11:00", eleve_id="marie"),
    evt("b", "2026-10-12T10:00", "2026-10-12T11:00", eleve_id="marie"),
    evt("c", "2026-10-30T10:00", "2026-10-30T11:00", eleve_id="marie"),
    evt("x", "2026-10-15T10:00", "2026-10-15T11:00", eleve_id="autre"),
    evt("s", "2026-10-13T09:00", "2026-10-13T09:30", type_="suivi", eleve_id="marie"),
]
points = rythme_service.rapprocher(coaching, "marie", "Coaching 90 jours", evenements, "2026-10-28T12:00")
check("n-ieme RDV de l'eleve = n-ieme point (les suivis et les autres eleves ne comptent pas)",
      [p["statut"] for p in points[:4]] == ["fait", "fait", "planifie", "a_planifier"] and points[2]["evenement"]["id"] == "c")

collectifs = [
    evt("k1", "2026-10-05T18:00", "2026-10-05T20:00", type_="collectif", parcours="Atelier"),
    evt("k2", "2026-10-14T18:00", "2026-10-14T20:00", type_="collectif", parcours="Atelier"),
    evt("k3", "2026-10-19T18:00", "2026-10-19T20:00", type_="collectif", parcours="Autonome"),
]
points = rythme_service.rapprocher(atelier, "paul", "Atelier", collectifs, "2026-10-10T12:00")
check("collectif de la meme formule, a 3 jours pres", [p["statut"] for p in points] == ["fait", "planifie", "a_planifier", "a_planifier", "a_planifier"])
check("un collectif d'une autre formule n'est pas compte", all(p["evenement"] is None or p["evenement"]["id"] != "k3" for p in points))

print("\n3. Reglages : validation et stockage dans l'agenda")
for libelle, regle in [
    ("ecart nul", {"Atelier": {"collectif": {"actif": True, "debut": 0, "tous_les": 0, "nombre": 4, "duree": 120}}}),
    ("duree exotique", {"Atelier": {"collectif": {"actif": True, "debut": 0, "tous_les": 7, "nombre": 4, "duree": 50}}}),
    ("nombre absurde", {"Atelier": {"collectif": {"actif": True, "debut": 0, "tous_les": 7, "nombre": 99, "duree": 120}}}),
    ("texte", {"Atelier": {"collectif": {"actif": True, "debut": "x", "tous_les": 7, "nombre": 4, "duree": 120}}}),
]:
    code, rep = statut(portal_main.coach_points_regles, portal_main.RythmePoints(regles=regle), x_coach_key=CLE)
    check(f"refus ({libelle}) -> 422", code == 422)


class Reponse:
    def __init__(self, code, data=None):
        self.status_code = code
        self._data = data or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


class FausseSession:
    def __init__(self):
        self.evenements = {}
        self.appels = []

    def get(self, url, params=None):
        self.appels.append(("GET", url, params))
        filtre = (params or {}).get("privateExtendedProperty")
        items = list(self.evenements.values())
        if filtre:
            cle, valeur = filtre.split("=", 1)
            items = [e for e in items if e["extendedProperties"]["private"].get(cle) == valeur]
        return Reponse(200, {"items": items})

    def post(self, url, json=None):
        self.appels.append(("POST", url, json))
        nouveau = dict(json, id=f"e{len(self.evenements) + 1}")
        self.evenements[nouveau["id"]] = nouveau
        return Reponse(200, nouveau)

    def put(self, url, json=None):
        self.appels.append(("PUT", url, json))
        eid = url.rsplit("/", 1)[1]
        self.evenements[eid] = dict(json, id=eid)
        return Reponse(200, self.evenements[eid])


session = FausseSession()
agenda_service._session = session
check("sans reglage enregistre : valeurs par defaut", rythme_service.lire() == defaut)

nouveau = rythme_service.valider({})
nouveau["Coaching 90 jours"]["individuel"].update(tous_les=14, nombre=6)
nouveau["Coaching 90 jours"]["collectif"]["actif"] = True
code, rep = statut(portal_main.coach_points_regles, portal_main.RythmePoints(regles=nouveau), x_coach_key=CLE)
cree = [a[2] for a in session.appels if a[0] == "POST"]
check("enregistrement : un evenement de reglages cache, disponible, sans rappel",
      code == 200 and len(cree) == 1 and cree[0]["start"] == {"date": "2000-01-01"}
      and cree[0]["transparency"] == "transparent" and cree[0]["reminders"] == {"useDefault": False, "overrides": []})
check("relecture du rythme enregistre", rythme_service.lire()["Coaching 90 jours"]["individuel"]["tous_les"] == 14)

nouveau["Atelier"]["individuel"]["duree"] = 30
statut(portal_main.coach_points_regles, portal_main.RythmePoints(regles=nouveau), x_coach_key=CLE)
check("second enregistrement : le meme evenement est mis a jour (pas de doublon)",
      sum(1 for a in session.appels if a[0] == "POST") == 1 and any(a[0] == "PUT" for a in session.appels)
      and rythme_service.lire()["Atelier"]["individuel"]["duree"] == 30)

grand = {"cle": "x" * 2500}
agenda_service.ecrire_reglage("essai", grand)
check("valeur longue decoupee (proprietes Google de 1024 caracteres max) puis relue", agenda_service.lire_reglage("essai") == grand
      and all(len(v) <= 1024 for e in session.evenements.values() for v in e["extendedProperties"]["private"].values()))
check("les autres reglages sont gardes", rythme_service.lire()["Atelier"]["individuel"]["duree"] == 30)

code, rep = statut(portal_main.coach_agenda_supprimer, next(iter(session.evenements)), x_coach_key=CLE)
check("l'evenement de reglages ne se supprime pas depuis l'agenda (403)", code == 403)

print("\n4. Routes coach et eleve")
session.evenements.clear()
session.evenements["r1"] = {"id": "r1", "summary": "RDV", "start": {"dateTime": "2026-10-01T10:00:00-04:00"}, "end": {"dateTime": "2026-10-01T11:00:00-04:00"},
                            "htmlLink": "https://cal/r1", "location": "Meet",
                            "extendedProperties": {"private": {"source": "portail", "type": "rdv", "eleve_id": "marie", "eleve_nom": "Marie"}}}
eleves = [
    {"client_page_id": "marie", "nom": "Marie", "parcours": "Coaching 90 jours", "date_demarrage": "2026-10-01", "jour": 27},
    {"client_page_id": "sans", "nom": "Sans date", "parcours": "Atelier", "date_demarrage": None, "jour": None},
]
with patch.object(eleves_service, "calendrier", return_value=eleves):
    code, rep = statut(portal_main.coach_points, x_coach_key=CLE)
check("coach : points par eleve avec statut", code == 200 and rep["eleves"][0]["points"][0]["statut"] == "fait"
      and rep["eleves"][0]["points"][1]["statut"] == "a_planifier")
check("coach : eleve sans date de demarrage ignore", [e["client_page_id"] for e in rep["eleves"]] == ["marie"])
code, rep = statut(portal_main.coach_points, x_coach_key="faux")
check("coach : mauvaise cle -> 401", code == 401)

page = {"properties": {}}
with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "marie"}), \
     patch.object(portal_main.notion_service, "_get_page", return_value=page), \
     patch.object(portal_main.notion_service, "_prop_value", side_effect=lambda v: v), \
     patch.object(portal_main.notion_service, "_prop", side_effect=lambda props, nom: {"Date de demarrage": "2026-10-01", "Parcours": "Coaching 90 jours"}.get(nom)):
    code, rep = statut(portal_main.portal_points, authorization="Bearer x")
premier = rep["points"][0]
check("eleve : ses points, avec date et lieu du RDV", code == 200 and premier["statut"] == "fait" and premier["evenement"]["lieu"] == "Meet")
check("eleve : jamais le lien de l'agenda de Rony ni d'identifiant (RDV non annulable)", set(premier["evenement"]) == {"debut", "fin", "lieu", "annulable"} and premier["evenement"]["annulable"] is False)

agenda_service._session = None
with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "marie"}), \
     patch.object(portal_main.notion_service, "_get_page", side_effect=RuntimeError("Notion")):
    code, rep = statut(portal_main.portal_points, authorization="Bearer x")
check("eleve : panne -> liste vide, jamais d'erreur", code == 200 and rep == {"points": []})

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
