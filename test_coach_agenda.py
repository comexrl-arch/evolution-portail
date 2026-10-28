# Tests du 28/10/2026 : onglet « Agenda » de l'Espace Coach, branche sur le
# Google Agenda de Rony (agenda_service). Entierement mockes : ni Google, ni
# reseau. Lancer : python test_coach_agenda.py

import json
import os
import sys

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"
for variable in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
                 "GOOGLE_OAUTH_REFRESH_TOKEN", "GOOGLE_CALENDAR_ID", "AGENDA_FUSEAU"):
    os.environ.pop(variable, None)

import portal_main
from backend.services import agenda_service

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


class Reponse:
    def __init__(self, code, data=None):
        self.status_code = code
        self._data = data or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


class FausseSession:
    """Faux Google Agenda : garde les evenements en memoire."""

    def __init__(self):
        self.evenements = {
            "perso": {
                "id": "perso", "summary": "Dentiste", "htmlLink": "https://cal/perso",
                "start": {"dateTime": "2026-10-29T09:00:00-04:00"}, "end": {"dateTime": "2026-10-29T10:00:00-04:00"},
            },
            "conge": {
                "id": "conge", "summary": "Toussaint", "start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"},
            },
            "annule": {"id": "annule", "status": "cancelled", "start": {"dateTime": "2026-10-29T11:00:00-04:00"}, "end": {"dateTime": "2026-10-29T12:00:00-04:00"}},
        }
        self.appels = []
        self.compteur = 0

    def _id(self, url):
        return url.rsplit("/events/", 1)[1] if "/events/" in url else None

    def get(self, url, params=None):
        self.appels.append(("GET", url, params))
        eid = self._id(url)
        if eid:
            return Reponse(200, self.evenements[eid]) if eid in self.evenements else Reponse(404)
        items = list(self.evenements.values())
        if params and params.get("privateExtendedProperty") == "source=portail":
            items = [e for e in items if (e.get("extendedProperties") or {}).get("private", {}).get("source") == "portail"]
        items.sort(key=lambda e: e["start"].get("dateTime") or e["start"].get("date"))
        return Reponse(200, {"items": items})

    def post(self, url, json=None):
        self.appels.append(("POST", url, json))
        self.compteur += 1
        evt = dict(json, id=f"p{self.compteur}", htmlLink="https://cal/p")
        evt["start"] = {"dateTime": json["start"]["dateTime"] + "-04:00"}
        evt["end"] = {"dateTime": json["end"]["dateTime"] + "-04:00"}
        self.evenements[evt["id"]] = evt
        return Reponse(200, evt)

    def patch(self, url, json=None):
        self.appels.append(("PATCH", url, json))
        eid = self._id(url)
        evt = dict(self.evenements[eid], **json)
        evt["start"] = {"dateTime": json["start"]["dateTime"] + "-04:00"}
        evt["end"] = {"dateTime": json["end"]["dateTime"] + "-04:00"}
        self.evenements[eid] = evt
        return Reponse(200, evt)

    def delete(self, url):
        self.appels.append(("DELETE", url, None))
        self.evenements.pop(self._id(url), None)
        return Reponse(204)


print("\n1. Sans configuration : l'onglet repond sans planter")
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("200 et configure=False", code == 200 and rep["configure"] is False and rep["evenements"] == [])
code, _ = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(debut="2026-10-30T10:00", fin="2026-10-30T11:00"), x_coach_key=CLE)
check("creation refusee proprement (503)", code == 503)
code, _ = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key="mauvaise")
check("mauvais code d'acces -> 401", code == 401)
code, _ = statut(portal_main.coach_agenda, "26/10/2026", "2026-11-02", x_coach_key=CLE)
check("periode invalide -> 422", code == 422)

print("\n2. Compte de service + agenda partage")
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"type": "service_account", "client_email": "portail@projet.iam.gserviceaccount.com"})
check("sans GOOGLE_CALENDAR_ID, l'agenda reste desactive", agenda_service.enabled() is False)
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("la marche a suivre donne l'adresse du compte de service", rep.get("compte_de_service") == "portail@projet.iam.gserviceaccount.com")
os.environ["GOOGLE_CALENDAR_ID"] = "rony@gmail.com"
check("avec GOOGLE_CALENDAR_ID, l'agenda est actif", agenda_service.enabled() is True)

session = FausseSession()
agenda_service._session = session

code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
evts = {e["id"]: e for e in rep["evenements"]}
check("lecture OK", code == 200 and rep["configure"] is True and rep["fuseau"] == "America/Guadeloupe")
check("l'agenda est vise par son identifiant encode", "rony%40gmail.com" in session.appels[-1][1])
check("evenement perso en heure locale, non modifiable", evts["perso"]["debut"] == "2026-10-29T09:00" and evts["perso"]["portail"] is False)
check("evenement sur la journee reconnu", evts["conge"]["journee"] is True and evts["conge"]["debut"] == "2026-11-01")
check("evenement annule ignore", "annule" not in evts)

print("\n3. Creer, deplacer, supprimer un RDV d'eleve")
code, cree = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(
    type="rdv", eleve_id="eleve-1", eleve_nom="Marie Laurent", debut="2026-10-30T10:00", fin="2026-10-30T11:00",
), x_coach_key=CLE)
envoye = session.appels[-1][2]
check("creation OK", code == 200 and cree["portail"] is True and cree["eleve_nom"] == "Marie Laurent")
check("titre automatique", envoye["summary"] == "RDV coaching · Marie Laurent")
check("fuseau envoye a Google", envoye["start"] == {"dateTime": "2026-10-30T10:00:00", "timeZone": "America/Guadeloupe"})
check("proprietes privees posees", envoye["extendedProperties"]["private"]["eleve_id"] == "eleve-1")

code, rep = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(debut="2026-10-30T10:00", fin="2026-10-30T09:00"), x_coach_key=CLE)
check("fin avant debut -> 422", code == 422)
code, rep = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(type="fete", debut="2026-10-30T10:00", fin="2026-10-30T11:00"), x_coach_key=CLE)
check("type inconnu -> 422", code == 422)

code, deplace = statut(portal_main.coach_agenda_modifier, cree["id"], portal_main.AgendaModification(
    debut="2026-10-31T14:00", fin="2026-10-31T15:00",
), x_coach_key=CLE)
envoye = session.appels[-1][2]
check("deplacement OK", code == 200 and deplace["debut"] == "2026-10-31T14:00")
check("le deplacement garde l'eleve et le titre", envoye["summary"] == "RDV coaching · Marie Laurent" and envoye["extendedProperties"]["private"]["eleve_nom"] == "Marie Laurent")

code, change = statut(portal_main.coach_agenda_modifier, cree["id"], portal_main.AgendaModification(
    type="suivi", eleve_id="eleve-2", eleve_nom="Jean-Marc",
), x_coach_key=CLE)
envoye = session.appels[-1][2]
check("changer d'eleve et de type refait le titre", envoye["summary"] == "Suivi · Jean-Marc")
check("le suivi a un rappel 1 h avant", envoye["reminders"]["overrides"][0]["minutes"] == 60)

code, rep = statut(portal_main.coach_agenda_prochains, "2026-10-28T08:00", x_coach_key=CLE)
check("prochain RDV par eleve", code == 200 and rep["prochains"]["eleve-2"]["debut"] == "2026-10-31T14:00")

code, rep = statut(portal_main.coach_agenda_modifier, "perso", portal_main.AgendaModification(debut="2026-10-29T15:00", fin="2026-10-29T16:00"), x_coach_key=CLE)
check("un evenement personnel ne se deplace pas depuis le portail (403)", code == 403)
code, rep = statut(portal_main.coach_agenda_supprimer, "perso", x_coach_key=CLE)
check("ni ne se supprime (403)", code == 403 and "perso" in session.evenements)
code, rep = statut(portal_main.coach_agenda_supprimer, "inconnu", x_coach_key=CLE)
check("evenement inconnu -> 404", code == 404)

code, rep = statut(portal_main.coach_agenda_supprimer, cree["id"], x_coach_key=CLE)
check("suppression OK", code == 200 and cree["id"] not in session.evenements)

print("\n4. Panne Google : message generique")
class Panne(FausseSession):
    def get(self, url, params=None):
        return Reponse(500, {"error": "boom"})
agenda_service._session = Panne()
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("503 sans detail technique", code == 503 and "boom" not in str(rep))

print("\n5. Reglage pas fini : etat clair, jamais d'exception brute (28/10/2026)")
from google.auth.exceptions import RefreshError

class Refus(FausseSession):
    def __init__(self, code):
        super().__init__()
        self.code = code
    def get(self, url, params=None):
        return Reponse(self.code, {"error": "refus"})

for code_google in (403, 404):
    agenda_service._session = Refus(code_google)
    code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
    check(f"Google {code_google} sur la liste -> 200, a brancher, acces refuse", code == 200 and rep["configure"] is False and rep["raison"] == "acces_refuse")
    check(f"Google {code_google} : compte de service et agenda vise renvoyes", rep["acces"] == "compte_de_service" and rep["calendrier"] == "rony@gmail.com" and rep["compte_de_service"])
    code, rep = statut(portal_main.coach_agenda_prochains, "2026-10-28T08:00", x_coach_key=CLE)
    check(f"Google {code_google} : prochains reste vide sans erreur", code == 200 and rep["prochains"] == {})

class JetonRefuse(FausseSession):
    def get(self, url, params=None):
        raise RefreshError("invalid_scope")
    post = patch = lambda self, url, json=None: (_ for _ in ()).throw(RefreshError("invalid_scope"))

agenda_service._session = JetonRefuse()
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("jeton Google sans droit agenda -> 200, acces refuse (plus de 500)", code == 200 and rep["raison"] == "acces_refuse")
code, rep = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(debut="2026-10-30T10:00", fin="2026-10-30T11:00"), x_coach_key=CLE)
check("creation avec jeton refuse -> 403 avec phrase claire", code == 403 and "réglage" in rep)

class Coupure(FausseSession):
    def get(self, url, params=None):
        raise ConnectionError("reset")

agenda_service._session = Coupure()
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("coupure reseau vers Google -> 503 generique (pas d'exception brute)", code == 503)

print("\n6. Acces OAuth seul (celui du cockpit), sans GOOGLE_CALENDAR_ID")
os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON")
os.environ.pop("GOOGLE_CALENDAR_ID")
os.environ.update(GOOGLE_OAUTH_CLIENT_ID="id", GOOGLE_OAUTH_CLIENT_SECRET="s", GOOGLE_OAUTH_REFRESH_TOKEN="r")
agenda_service._session = JetonRefuse()
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("OAuth sans droit agenda -> a brancher, acces oauth, pas de compte de service",
      code == 200 and rep["raison"] == "acces_refuse" and rep["acces"] == "oauth" and rep["compte_de_service"] is None)

print("\n7. Tous ses agendas : liste, cases a cocher, secondaires en lecture seule")
os.environ["GOOGLE_CALENDAR_ID"] = "rony@gmail.com"


class PlusieursAgendas(FausseSession):
    def __init__(self, liste=True, casse=()):
        super().__init__()
        self.liste = liste
        self.casse = set(casse)
        self.secondaires = {
            "perso@group": [{"id": "foot", "summary": "Foot", "start": {"dateTime": "2026-10-28T18:00:00-04:00"}, "end": {"dateTime": "2026-10-28T19:00:00-04:00"},
                             "extendedProperties": {"private": {"source": "portail", "type": "rdv"}}}],
            "calendly@group": [{"id": "perso", "summary": "Copie", "start": {"dateTime": "2026-10-29T09:00:00-04:00"}, "end": {"dateTime": "2026-10-29T10:00:00-04:00"}}],
        }

    def get(self, url, params=None):
        if url.endswith("/users/me/calendarList"):
            self.appels.append(("GET", url, params))
            if not self.liste:
                return Reponse(403)
            return Reponse(200, {"items": [
                {"id": "zz@group", "summary": "Anniversaires", "backgroundColor": "#92e1c0"},
                {"id": "rony@gmail.com", "summary": "Rony Lepitre", "primary": True, "selected": True, "backgroundColor": "#9fe1e7"},
                {"id": "perso@group", "summary": "Perso", "summaryOverride": "Perso famille", "selected": True},
                {"id": "cache@group", "summary": "Cache", "hidden": True},
            ]})
        for cal, items in self.secondaires.items():
            if f"/calendars/{cal.replace('@', '%40')}/events" in url:
                self.appels.append(("GET", url, params))
                return Reponse(404) if cal in self.casse else Reponse(200, {"items": items})
        return super().get(url, params)


agenda_service._session = PlusieursAgendas()
code, rep = statut(portal_main.coach_agenda_agendas, x_coach_key=CLE)
noms = [a["nom"] for a in rep["agendas"]]
check("liste des agendas : principal en tete, masques exclus, nom personnalise",
      code == 200 and rep["liste"] is True and noms == ["Rony Lepitre", "Anniversaires", "Perso famille"])
check("cases cochees par defaut = celles de Google + le principal",
      [a["coche"] for a in rep["agendas"]] == [True, False, True] and rep["agendas"][0]["principal"])

code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", agendas="perso@group,calendly@group", x_coach_key=CLE)
par_id = {e["id"]: e for e in rep["evenements"]}
check("evenements des agendas secondaires ajoutes", code == 200 and "foot" in par_id and par_id["foot"]["agenda"] == "perso@group")
check("secondaire jamais modifiable, meme avec une propriete portail", par_id["foot"]["portail"] is False and par_id["foot"]["type"] is None)
check("doublon (meme evenement dans deux agendas) : la version principale gagne",
      par_id["perso"]["agenda"] is None and par_id["perso"]["titre"] == "Dentiste")

agenda_service._session = PlusieursAgendas(casse={"perso@group"})
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", agendas="perso@group,calendly@group", x_coach_key=CLE)
check("un agenda secondaire illisible est ignore, le reste s'affiche",
      code == 200 and "foot" not in {e["id"] for e in rep["evenements"]} and "perso" in {e["id"] for e in rep["evenements"]})

session = PlusieursAgendas()
agenda_service._session = session
statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", agendas="rony@gmail.com,primary", x_coach_key=CLE)
check("l'agenda principal n'est jamais lu deux fois", sum(1 for a in session.appels if "/events" in a[1]) == 1)

agenda_service._session = PlusieursAgendas(liste=False)
code, rep = statut(portal_main.coach_agenda_agendas, x_coach_key=CLE)
check("jeton sans droit sur la liste -> liste=False, pas d'erreur", code == 200 and rep == {"liste": False, "agendas": []})
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("... et l'agenda principal s'affiche quand meme", code == 200 and rep["configure"] is True and rep["evenements"])

print("\n8. Creneaux de RDV : plages hebdomadaires dans l'agenda principal")
from datetime import datetime as _dt


class AvecCreneaux(FausseSession):
    def get(self, url, params=None):
        if params and params.get("privateExtendedProperty") == "type=creneau":
            self.appels.append(("GET", url, params))
            items = [e for e in self.evenements.values()
                     if ((e.get("extendedProperties") or {}).get("private") or {}).get("type") == "creneau"]
            return Reponse(200, {"items": items})
        return super().get(url, params)


session = AvecCreneaux()
agenda_service._session = session
code, rep = statut(portal_main.coach_agenda_creneaux, x_coach_key=CLE)
check("aucune plage au depart", code == 200 and rep == {"plages": [], "duree": 60})

regles = portal_main.AgendaReglesCreneaux(duree=45, plages=[
    portal_main.AgendaPlage(jour=3, debut="14:00", fin="17:00"),
    portal_main.AgendaPlage(jour=1, debut="09:00", fin="12:00"),
])
code, rep = statut(agenda_service.enregistrer_regles, [p.model_dump() for p in regles.plages], 45, _dt(2026, 10, 28))
crees = [a[2] for a in session.appels if a[0] == "POST"]
check("une serie hebdomadaire par plage", code == 200 and [c["recurrence"] for c in crees] == [["RRULE:FREQ=WEEKLY;BYDAY=TU"], ["RRULE:FREQ=WEEKLY;BYDAY=TH"]])
check("premiere occurrence = prochain jour concerne",
      crees[0]["start"]["dateTime"] == "2026-11-03T09:00:00" and crees[1]["start"]["dateTime"] == "2026-10-29T14:00:00")
check("plages disponibles (ne bloquent rien) et sans rappel",
      all(c["transparency"] == "transparent" and c["reminders"] == {"useDefault": False, "overrides": []} for c in crees))
check("type creneau + duree en propriete privee",
      crees[0]["extendedProperties"]["private"] == {"source": "portail", "type": "creneau", "duree": "45"})

code, rep = statut(portal_main.coach_agenda_creneaux, x_coach_key=CLE)
check("relecture des plages (lundi=0) et de la duree",
      rep == {"duree": 45, "plages": [{"jour": 1, "debut": "09:00", "fin": "12:00"}, {"jour": 3, "debut": "14:00", "fin": "17:00"}]})

session.appels.clear()
code, rep = statut(portal_main.coach_agenda_creneaux_enregistrer,
                   portal_main.AgendaReglesCreneaux(duree=60, plages=[portal_main.AgendaPlage(jour=0, debut="08:00", fin="10:00")]), x_coach_key=CLE)
types = [a[0] for a in session.appels]
check("enregistrer remplace : anciennes series supprimees puis nouvelles creees",
      code == 200 and types.count("DELETE") == 2 and types.count("POST") == 1)

for libelle, plages, duree in [
    ("fin avant debut", [portal_main.AgendaPlage(jour=0, debut="10:00", fin="09:00")], 60),
    ("chevauchement", [portal_main.AgendaPlage(jour=0, debut="09:00", fin="11:00"), portal_main.AgendaPlage(jour=0, debut="10:00", fin="12:00")], 60),
    ("jour hors bornes", [portal_main.AgendaPlage(jour=7, debut="09:00", fin="10:00")], 60),
    ("heure mal formee", [portal_main.AgendaPlage(jour=0, debut="9h", fin="10:00")], 60),
    ("duree exotique", [], 50),
]:
    avant = len(session.appels)
    code, rep = statut(portal_main.coach_agenda_creneaux_enregistrer, portal_main.AgendaReglesCreneaux(duree=duree, plages=plages), x_coach_key=CLE)
    check(f"refus ({libelle}) -> 422 sans rien toucher", code == 422 and len(session.appels) == avant)

serie = next(e for e in session.evenements.values() if (e.get("extendedProperties") or {}).get("private", {}).get("type") == "creneau")
serie["start"] = {"dateTime": "2026-10-26T08:00:00-04:00"}
serie["end"] = {"dateTime": "2026-10-26T10:00:00-04:00"}
code, rep = statut(portal_main.coach_agenda, "2026-10-26", "2026-11-02", x_coach_key=CLE)
check("la vue renvoie les plages a part, pas comme des evenements",
      code == 200 and rep["creneaux"] == [{"debut": "2026-10-26T08:00", "fin": "2026-10-26T10:00"}]
      and all(e["type"] != "creneau" for e in rep["evenements"]))
code, rep = statut(portal_main.coach_agenda_supprimer, serie["id"], x_coach_key=CLE)
check("une serie de creneaux ne se modifie pas comme un RDV (403)", code == 403)
code, rep = statut(portal_main.coach_agenda_prochains, "2026-10-26T00:00", x_coach_key=CLE)
check("les creneaux n'apparaissent pas comme prochain RDV d'un eleve", code == 200 and rep["prochains"] == {})

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
