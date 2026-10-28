# Tests du 28/10/2026 : un RDV pose par Rony dans l'Espace Coach apparait dans
# l'espace de l'eleve (meme hors rythme, ex. formule Autonome) et l'eleve est
# prevenu par notification. Entierement mockes : ni Google, ni Notion, ni reseau.
# Lancer : python test_rdv_eleve.py

import json
import os
import sys
from unittest.mock import patch

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"type": "service_account", "client_email": "portail@projet.iam.gserviceaccount.com"})
os.environ["GOOGLE_CALENDAR_ID"] = "rony@gmail.com"

import portal_main
from backend.services import agenda_service, eleves_service, push_service, rythme_service

passed = 0
failed = 0
CLE = "cle-coach-test"
MAINTENANT = "2026-10-28T08:00"


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
    return {"id": id_, "titre": "RDV", "debut": debut, "fin": fin, "type": type_, "eleve_id": eleve_id, "parcours": parcours,
            "lieu": "Meet", "lien": "https://cal/x", "portail": True, "journee": False}


def points_eleve(parcours, demarrage, evenements):
    props = {"Date de demarrage": demarrage, "Parcours": parcours}
    with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "test"}), \
         patch.object(portal_main.notion_service, "_get_page", return_value={"properties": {}}), \
         patch.object(portal_main.notion_service, "_prop_value", side_effect=lambda v: v), \
         patch.object(portal_main.notion_service, "_prop", side_effect=lambda p, nom: props.get(nom)), \
         patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT), \
         patch.object(rythme_service, "lire", return_value=rythme_service.valider({})), \
         patch.object(agenda_service, "evenements_portail", return_value=evenements) as lecture:
        code, rep = statut(portal_main.portal_points, authorization="Bearer x")
    return code, rep, lecture


print("\n1. Le RDV pose par Rony s'affiche dans l'espace de l'eleve")
rdv = evt("g9", "2026-10-28T11:00", "2026-10-28T12:00", eleve_id="test")
code, rep, _ = points_eleve("Autonome", "2026-09-21", [rdv])
planifies = [p for p in rep["points"] if p["statut"] == "planifie"]
check("Autonome (pas de points individuels au rythme) : le RDV apparait quand meme",
      code == 200 and len(planifies) == 1 and planifies[0]["type"] == "individuel"
      and planifies[0]["evenement"] == {"debut": "2026-10-28T11:00", "fin": "2026-10-28T12:00", "lieu": "Meet"})
check("jour de parcours et duree calcules", planifies[0]["jour"] == 37 and planifies[0]["duree"] == 60)

code, rep, lecture = points_eleve("Coaching 90 jours", None, [rdv])
check("eleve sans date de demarrage : le RDV apparait aussi", code == 200 and [p["evenement"]["debut"] for p in rep["points"]] == ["2026-10-28T11:00"]
      and rep["points"][0]["jour"] is None and lecture.called)

code, rep, _ = points_eleve("Coaching 90 jours", "2026-10-28", [rdv, evt("g10", "2026-11-05T11:00", "2026-11-05T12:00", eleve_id="test")])
evts = [p for p in rep["points"] if p["evenement"]]
check("Coaching : RDV rattaches aux points du rythme, sans doublon", len(evts) == 2 and evts[0]["numero"] == 1 and evts[1]["numero"] == 2)

autres = [
    evt("x", "2026-10-29T11:00", "2026-10-29T12:00", eleve_id="autre"),
    evt("passe", "2026-10-20T11:00", "2026-10-20T12:00", eleve_id="test", type_="autre"),
    evt("suivi", "2026-10-30T11:00", "2026-10-30T11:15", eleve_id="test", type_="suivi"),
    evt("k", "2026-11-02T18:00", "2026-11-02T19:00", type_="collectif", parcours="Atelier"),
    evt("k2", "2026-11-03T18:00", "2026-11-03T19:00", type_="collectif", parcours="Autonome"),
]
code, rep, _ = points_eleve("Autonome", "2026-09-21", autres)
planifies = [p for p in rep["points"] if p["statut"] == "planifie"]
check("seuls ses RDV a venir et les collectifs de sa formule (pas les autres eleves, ni ses suivis, ni le passe)",
      [p["evenement"]["debut"] for p in planifies] == ["2026-11-03T18:00"])

print("\n2. Notification de l'eleve")
envois = []


def prevenir(avant, apres, eleves=None):
    envois.clear()
    with patch.object(push_service, "enabled", return_value=True), \
         patch.object(push_service, "envoyer", side_effect=lambda eid, titre, texte, url="/": envois.append((eid, titre, texte)) or 1), \
         patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT), \
         patch.object(eleves_service, "calendrier", return_value=eleves or []):
        portal_main._prevenir_rdv(avant, apres)
    return list(envois)


check("format de date en francais", push_service.quand("2026-10-28T11:00") == "mercredi 28 octobre à 11h00")
check("nouveau RDV -> l'eleve est prevenu", prevenir(None, rdv) == [("test", "Nouveau rendez-vous avec Rony", "Mercredi 28 octobre à 11h00. Tu le retrouves dans ton espace.")])
deplace = dict(rdv, debut="2026-10-30T09:30", fin="2026-10-30T10:30")
check("RDV deplace -> nouvelle date", prevenir(rdv, deplace) == [("test", "Rendez-vous déplacé", "Nouvelle date : vendredi 30 octobre à 9h30.")])
check("lieu change seulement -> pas de notification", prevenir(rdv, dict(rdv, lieu="Zoom")) == [])
check("RDV supprime -> annulation", prevenir(rdv, None) == [("test", "Rendez-vous annulé", "Le rendez-vous du mercredi 28 octobre à 11h00 est annulé.")])
change = prevenir(rdv, dict(rdv, eleve_id="marie"))
check("RDV passe a un autre eleve -> annule pour l'un, nouveau pour l'autre",
      sorted((e[0], e[1]) for e in change) == [("marie", "Nouveau rendez-vous avec Rony"), ("test", "Rendez-vous annulé")])
check("RDV deja passe -> rien", prevenir(None, evt("p", "2026-10-27T11:00", "2026-10-27T12:00", eleve_id="test")) == [])
check("suivi (rappel pour Rony) -> rien", prevenir(None, evt("s", "2026-10-29T11:00", "2026-10-29T11:15", type_="suivi", eleve_id="test")) == [])
eleves = [{"client_page_id": "a", "parcours": "Autonome"}, {"client_page_id": "b", "parcours": "Autonome"}, {"client_page_id": "c", "parcours": "Atelier"}]
coll = prevenir(None, evt("k", "2026-11-03T18:00", "2026-11-03T19:00", type_="collectif", parcours="Autonome"), eleves)
check("point collectif -> tous les eleves de la formule", sorted(e[0] for e in coll) == ["a", "b"] and coll[0][1] == "Nouveau point collectif")

with patch.object(push_service, "enabled", return_value=False), patch.object(push_service, "envoyer") as envoi:
    portal_main._prevenir_rdv(None, rdv)
check("notifications push non configurees -> rien, sans erreur", not envoi.called)
with patch.object(push_service, "enabled", return_value=True), patch.object(push_service, "envoyer", side_effect=RuntimeError("Notion")), \
     patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT):
    portal_main._prevenir_rdv(None, rdv)
check("panne d'envoi -> jamais d'erreur pour le coach", True)

print("\n3. Routes coach : la notification part apres l'enregistrement")
with patch.object(agenda_service, "creer", return_value=rdv), patch.object(portal_main, "_prevenir_rdv") as prev:
    code, rep = statut(portal_main.coach_agenda_creer, portal_main.AgendaEvenement(type="rdv", debut="2026-10-28T11:00", fin="2026-10-28T12:00", eleve_id="test", eleve_nom="TEST"), x_coach_key=CLE)
check("creation -> prevenir(None, RDV cree)", code == 200 and prev.call_args.args == (None, rdv))
with patch.object(agenda_service, "lire", return_value=rdv), patch.object(agenda_service, "modifier", return_value=deplace), patch.object(portal_main, "_prevenir_rdv") as prev:
    code, rep = statut(portal_main.coach_agenda_modifier, "g9", portal_main.AgendaModification(debut="2026-10-30T09:30", fin="2026-10-30T10:30"), x_coach_key=CLE)
check("modification -> prevenir(avant, apres)", code == 200 and prev.call_args.args == (rdv, deplace))
with patch.object(agenda_service, "lire", return_value=rdv), patch.object(agenda_service, "supprimer"), patch.object(portal_main, "_prevenir_rdv") as prev:
    code, rep = statut(portal_main.coach_agenda_supprimer, "g9", x_coach_key=CLE)
check("suppression -> prevenir(avant, None)", code == 200 and prev.call_args.args == (rdv, None))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
