# Tests du 29/10/2026 : l'eleve reserve lui-meme un RDV dans les creneaux
# libres de Rony, et peut annuler sa propre reservation jusqu'a 24 h avant.
# Entierement mockes : ni Google, ni Notion, ni reseau.
# Lancer : python test_reservation_eleve.py

import json
import os
from unittest.mock import patch

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"
os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"type": "service_account", "client_email": "portail@projet.iam.gserviceaccount.com"})
os.environ["GOOGLE_CALENDAR_ID"] = "rony@gmail.com"

import portal_main
from backend.services import agenda_service, reservation_service, rythme_service

passed = 0
failed = 0
MAINTENANT = "2026-10-29T08:00"


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


def evt(id_, debut, fin, type_="rdv", eleve_id=None, reserve_par=None, libre=False, portail=True):
    return {"id": id_, "titre": "RDV", "debut": debut, "fin": fin, "type": type_, "eleve_id": eleve_id, "parcours": None,
            "lieu": "", "lien": "https://cal/x", "portail": portail, "journee": False, "libre": libre, "reserve_par": reserve_par}


# Plages de Rony : jeudi 29 (trop tot, < 24 h) et vendredi 30 de 9 h a 12 h.
PLAGES = [
    {"debut": "2026-10-29T09:00", "fin": "2026-10-29T12:00"},
    {"debut": "2026-10-30T09:00", "fin": "2026-10-30T12:00"},
]


def appel(fonction, parcours="Coaching 90 jours", evenements=(), plages=PLAGES, agendas=None, **kwargs):
    props = {"Date de demarrage": "2026-10-01", "Parcours": parcours, "Nom": "Marie Test"}
    with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "eleve1"}), \
         patch.object(portal_main.notion_service, "_get_page", return_value={"properties": {}}), \
         patch.object(portal_main.notion_service, "_prop_value", side_effect=lambda v: v), \
         patch.object(portal_main.notion_service, "_prop", side_effect=lambda p, nom: props.get(nom)), \
         patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT), \
         patch.object(rythme_service, "lire", return_value=rythme_service.valider({})), \
         patch.object(agenda_service, "agendas", return_value=agendas), \
         patch.object(agenda_service, "lister_complet", return_value=(list(evenements), list(plages))) as lecture, \
         patch.object(agenda_service, "creer", side_effect=lambda d: {**d, "id": "nouveau", "lieu": "", "lien": "x"}) as creation:
        code, rep = statut(fonction, authorization="Bearer x", **kwargs)
    return code, rep, lecture, creation


print("\n1. Creneaux proposes a l'eleve")
code, rep, lecture, _ = appel(portal_main.portal_creneaux)
debuts = [c["debut"] for c in rep["creneaux"]]
check("Coaching : creneaux de 60 min dans les plages", code == 200 and rep["possible"] and rep["duree"] == 60
      and debuts == ["2026-10-30T09:00", "2026-10-30T10:00", "2026-10-30T11:00"])
check("rien a moins de 24 h", not any(d.startswith("2026-10-29") for d in debuts))

occupe = evt("perso", "2026-10-30T10:30", "2026-10-30T11:15", type_=None, portail=False)
dispo = evt("dispo", "2026-10-30T09:00", "2026-10-30T10:00", type_=None, portail=False, libre=True)
code, rep, _, _ = appel(portal_main.portal_creneaux, evenements=[occupe, dispo])
check("un evenement de Rony bloque les creneaux qu'il chevauche, pas un evenement « disponible »",
      [c["debut"] for c in rep["creneaux"]] == ["2026-10-30T09:00"])

code, rep, _, _ = appel(portal_main.portal_creneaux, parcours="Atelier")
check("Atelier : point individuel de 20 min", rep["duree"] == 20 and len(rep["creneaux"]) == 9)

code, rep, lecture, _ = appel(portal_main.portal_creneaux, parcours="Autonome")
check("Autonome : pas de reservation (pas de points individuels)", code == 200 and not rep["possible"] and rep["raison"] == "formule")
check("Autonome : l'agenda n'est meme pas lu", not lecture.called)

deja = evt("r1", "2026-11-03T10:00", "2026-11-03T11:00", eleve_id="eleve1")
code, rep, _, _ = appel(portal_main.portal_creneaux, evenements=[deja])
check("un RDV deja a venir : pas de seconde reservation", not rep["possible"] and rep["raison"] == "deja")

code, rep, _, _ = appel(portal_main.portal_creneaux, plages=[])
check("aucune plage : complet", not rep["possible"] and rep["raison"] == "complet")

secondaire = [{"id": "rony@gmail.com", "principal": True, "coche": True}, {"id": "perso", "principal": False, "coche": True},
              {"id": "calendly", "principal": False, "coche": False}]
code, rep, lecture, _ = appel(portal_main.portal_creneaux, agendas=secondaire)
check("ses autres agendas affiches dans Google comptent comme occupes", lecture.call_args.args[2] == ["perso"])

with patch.object(agenda_service, "lister_complet", side_effect=RuntimeError("Google")), \
     patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "eleve1"}), \
     patch.object(portal_main.notion_service, "_get_page", return_value={"properties": {}}), \
     patch.object(agenda_service, "agendas", return_value=None):
    code, rep = statut(portal_main.portal_creneaux, authorization="Bearer x")
check("panne Google : jamais d'erreur, rien a reserver", code == 200 and not rep["possible"])


print("\n2. Reservation")
code, rep, _, creation = appel(portal_main.portal_reserver, reservation=portal_main.ReservationRdv(debut="2026-10-30T10:00"))
donnees = creation.call_args.args[0] if creation.called else {}
check("RDV cree dans l'agenda de Rony", code == 200 and rep == {"debut": "2026-10-30T10:00", "fin": "2026-10-30T11:00", "lieu": ""})
check("RDV coaching de l'eleve, marque reserve par l'eleve", donnees.get("type") == "rdv" and donnees.get("eleve_id") == "eleve1"
      and donnees.get("eleve_nom") == "Marie Test" and donnees.get("reserve_par") == "eleve")

code, rep, _, creation = appel(portal_main.portal_reserver, evenements=[occupe], reservation=portal_main.ReservationRdv(debut="2026-10-30T11:00"))
check("creneau pris entre-temps : 409 et rien de cree", code == 409 and "pris" in rep and not creation.called)

code, rep, _, creation = appel(portal_main.portal_reserver, reservation=portal_main.ReservationRdv(debut="2026-10-29T10:00"))
check("moins de 24 h : refuse", code == 409 and not creation.called)

code, rep, _, creation = appel(portal_main.portal_reserver, reservation=portal_main.ReservationRdv(debut="2026-10-30T10:15"))
check("heure hors grille : refuse", code == 409 and not creation.called)

code, rep, _, creation = appel(portal_main.portal_reserver, parcours="Autonome", reservation=portal_main.ReservationRdv(debut="2026-10-30T10:00"))
check("Autonome : refuse avec une phrase claire", code == 409 and "formule" in rep and not creation.called)

code, rep, _, creation = appel(portal_main.portal_reserver, evenements=[deja], reservation=portal_main.ReservationRdv(debut="2026-10-30T10:00"))
check("deja un RDV a venir : refuse", code == 409 and not creation.called)

code, rep, _, creation = appel(portal_main.portal_reserver, reservation=portal_main.ReservationRdv(debut="demain"))
check("date mal formee : 422", code == 422 and not creation.called)


print("\n3. Annulation par l'eleve")


def annuler(evenement, id_="r1"):
    with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "eleve1"}), \
         patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT), \
         patch.object(agenda_service, "lire", return_value=evenement), \
         patch.object(agenda_service, "supprimer") as suppression:
        code, rep = statut(portal_main.portal_annuler_reservation, id_, authorization="Bearer x")
    return code, rep, suppression


code, _, suppression = annuler(evt("r1", "2026-11-03T10:00", "2026-11-03T11:00", eleve_id="eleve1", reserve_par="eleve"))
check("sa propre reservation, plus de 24 h avant : annulee", code == 200 and suppression.called)

code, _, suppression = annuler(evt("r1", "2026-10-29T18:00", "2026-10-29T19:00", eleve_id="eleve1", reserve_par="eleve"))
check("moins de 24 h avant : refuse", code == 409 and not suppression.called)

code, _, suppression = annuler(evt("r1", "2026-11-03T10:00", "2026-11-03T11:00", eleve_id="eleve1"))
check("RDV pose par Rony : l'eleve ne peut pas l'annuler", code == 409 and not suppression.called)

code, rep, suppression = annuler(evt("r1", "2026-11-03T10:00", "2026-11-03T11:00", eleve_id="autre", reserve_par="eleve"))
check("RDV d'un autre eleve : introuvable", code == 409 and "introuvable" in rep and not suppression.called)


print("\n4. Mes prochains points : l'eleve peut annuler sa reservation")
props = {"Date de demarrage": "2026-10-01", "Parcours": "Coaching 90 jours"}
reserve = evt("r1", "2026-11-03T10:00", "2026-11-03T11:00", eleve_id="eleve1", reserve_par="eleve")
pose = evt("r2", "2026-11-13T10:00", "2026-11-13T11:00", eleve_id="eleve1")
with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "eleve1"}), \
     patch.object(portal_main.notion_service, "_get_page", return_value={"properties": {}}), \
     patch.object(portal_main.notion_service, "_prop_value", side_effect=lambda v: v), \
     patch.object(portal_main.notion_service, "_prop", side_effect=lambda p, nom: props.get(nom)), \
     patch.object(portal_main, "_maintenant_agenda", return_value=MAINTENANT), \
     patch.object(rythme_service, "lire", return_value=rythme_service.valider({})), \
     patch.object(agenda_service, "evenements_portail", return_value=[reserve, pose]):
    code, rep = statut(portal_main.portal_points, authorization="Bearer x")
vus = {p["evenement"]["debut"]: p["evenement"] for p in rep["points"] if p["evenement"]}
check("sa reservation : annulable, avec son identifiant", vus.get("2026-11-03T10:00", {}).get("annulable") is True
      and vus["2026-11-03T10:00"].get("id") == "r1")
check("RDV pose par Rony : pas annulable, pas d'identifiant", vus.get("2026-11-13T10:00", {}).get("annulable") is False
      and "id" not in vus["2026-11-13T10:00"])


print("\n5. L'agenda garde la marque « reserve par l'eleve »")
corps = agenda_service._corps({"type": "rdv", "eleve_id": "e", "debut": "2026-10-30T10:00", "fin": "2026-10-30T11:00", "reserve_par": "eleve"})
check("propriete privee reserve_par ecrite", corps["extendedProperties"]["private"]["reserve_par"] == "eleve")
lu = agenda_service._vers_portail({"id": "x", "start": {"dateTime": "2026-10-30T10:00:00-04:00"}, "end": {"dateTime": "2026-10-30T11:00:00-04:00"},
                                    "extendedProperties": {"private": {"source": "portail", "type": "rdv", "reserve_par": "eleve"}}})
check("relue par le portail", lu["reserve_par"] == "eleve")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
