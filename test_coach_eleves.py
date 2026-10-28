# Tests du 28/10/2026 : onglet « Élèves » de l'Espace Coach, qui remonte ce
# que chaque élève fait dans son espace client (fiches, saisies, carnet,
# retours d'Idris, connexions), lu dans Notion comme le portail.
#
# Entierement mockes (ni Notion, ni reseau), meme style que test_carnet_canaux.py.
#
# Lancer : python test_coach_eleves.py

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"

import portal_main
from backend.services import eleves_service, notion_service as ns, prospects_service

passed = 0
failed = 0


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


MAINTENANT = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
MASTER_TERMINE = next(iter(ns.FICHE_SCHEMAS))
MASTER_EN_COURS = list(ns.FICHE_SCHEMAS)[1]


def titre(texte):
    return {"type": "title", "title": [{"plain_text": texte}]}


def texte(valeur):
    return {"type": "rich_text", "rich_text": [{"plain_text": valeur}]}


def client(cid, nom, etat="En cours", email=None):
    return {"id": cid, "properties": {
        "Nom": titre(nom),
        "État": {"type": "status", "status": {"name": etat}},
        "Parcours": {"type": "select", "select": {"name": "Autonome"}},
        "E-mail": {"type": "email", "email": email},
        "Date de demarrage": {"type": "date", "date": {"start": "2026-10-01"}},
        "Nb relances": {"type": "number", "number": 2},
    }}


def fiche(master_id, etat):
    return {"id": f"fiche-{master_id[:6]}-{etat}", "properties": {
        "Nom": titre("X - " + ns.FICHE_SCHEMAS[master_id]["nom"]),
        "État": {"type": "status", "status": {"name": etat}},
    }}


CARNET = {"id": "carnet", "last_edited_time": "2026-10-27T10:00:00.000Z", "properties": {
    "Nom": titre("Marie — " + prospects_service.NOM_CARNET),
    "Données (JSON)": texte(json.dumps({"prospects": [
        {"id": "p1", "nom": "Boulangerie", "statut": "RDV"},
        {"id": "p2", "nom": "Garage", "statut": "Client"},
    ]})),
}}
SAISIE = {"id": "s1", "last_edited_time": "2026-10-25T10:00:00.000Z", "properties": {
    "Nom": titre("Marie - fiche"),
    "Retour IA statut": {"type": "select", "select": {"name": "À relire"}},
}}

CLIENTS = [
    client("c-marie", "Marie Test", email="marie@test.com"),
    client("c-paul", "Paul Test"),
    client("c-archive", "Ancien", etat="Terminé"),
]


def faux_query(data_source_id, filter_=None, sorts=None):
    if data_source_id == ns.CLIENTS_DATA_SOURCE_ID:
        return CLIENTS
    cible = json.dumps(filter_)
    if data_source_id == ns.FICHES_CLIENT_DATA_SOURCE_ID:
        if "c-marie" in cible:
            return [fiche(MASTER_TERMINE, "Terminé"), fiche(MASTER_EN_COURS, "En cours")]
        if "c-paul" in cible:
            raise RuntimeError("Notion en panne")
        return []
    if data_source_id == ns.ENTREES_PORTAIL_DATA_SOURCE_ID:
        return [CARNET, SAISIE] if "c-marie" in cible else []
    if data_source_id == ns.CONNEXIONS_DATA_SOURCE_ID:
        return [{"properties": {"Date de connexion": {"type": "date", "date": {"start": "2026-10-26T08:00:00+00:00"}}}}]
    return []


print("\n[1] Liste des eleves")
with patch.object(ns, "_query_data_source", side_effect=faux_query):
    eleves = eleves_service.liste(MAINTENANT)

par_id = {e["client_page_id"]: e for e in eleves}
marie = par_id.get("c-marie", {})
check("l'eleve archive (Terminé) n'apparait pas", "c-archive" not in par_id)
check("fiches terminees / total comptees", (marie.get("fiches_terminees"), marie.get("fiches_total")) == (1, 2))
check("derniere saisie = entree la plus recente", marie.get("derniere_saisie") == "2026-10-27T10:00:00.000Z")
check("jours sans saisie", marie.get("jours_sans_saisie") == 1)
check("carnet lu : 2 prospects dont 1 client", marie.get("nb_prospects") == 2 and marie["prospects_par_statut"]["Client"] == 1)
check("retour d'Idris a relire compte", marie.get("retours_ia_a_relire") == 1)
check("derniere connexion lue", marie.get("derniere_connexion", "").startswith("2026-10-26"))
check("nb relances lu", marie.get("nb_relances") == 2)
check("parcours et jour", marie.get("parcours") and marie.get("jour") is not None)
check("un eleve illisible ne vide pas la liste", par_id.get("c-paul", {}).get("illisible") is True)

print("\n[2] Detail : meme tableau de bord que l'espace client")
DASHBOARD = {"nom": "Marie Test", "fiches": [{"id": "fb", "master_id": ns._BILAN_HEBDO_MASTER_ID}], "kpi": []}
with patch.object(ns, "get_client_dashboard", return_value=DASHBOARD) as dash, \
        patch.object(prospects_service, "lire", return_value={"prospects": [], "importe": False}), \
        patch.object(ns, "_historique_bilans", return_value=[{"semaine_du": "2026-10-20", "rdv": 2.0}]), \
        patch.object(ns, "_cache_clear") as vider:
    detail = eleves_service.detail("c-marie", frais=True)

check("detail = get_client_dashboard (source du portail)", detail["dashboard"] is DASHBOARD and dash.call_args.args == ("c-marie",))
check("bilans hebdomadaires joints", detail["bilans"][0]["rdv"] == 2.0)
check("carnet joint", detail["carnet"]["prospects"] == [])
check("actualiser vide le cache de cet eleve", any("dashboard:c-marie" in str(c) for c in vider.call_args_list))

print("\n[3] Endpoints proteges par la cle coach")
code, _ = statut(portal_main.coach_eleves, x_coach_key="mauvaise")
check("/coach/eleves refuse sans cle", code == 401)
code, _ = statut(portal_main.coach_eleve_detail, "c-marie", x_coach_key="")
check("/coach/eleves/{id} refuse sans cle", code == 401)
with patch.object(eleves_service, "liste", return_value=[{"nom": "Marie"}]):
    code, corps = statut(portal_main.coach_eleves, x_coach_key="cle-coach-test")
check("/coach/eleves repond avec la cle", code == 200 and corps["eleves"][0]["nom"] == "Marie")
with patch.object(eleves_service, "liste", side_effect=RuntimeError("Erreur Notion (query) : secret")):
    code, corps = statut(portal_main.coach_eleves, x_coach_key="cle-coach-test")
check("panne Notion -> 503 sans detail technique", code == 503 and "secret" not in str(corps))

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
