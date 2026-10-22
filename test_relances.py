# Tests des relances intelligentes (22/10/2026), entierement mockes.
#
# Lancer : python test_relances.py

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.services import notion_service as ns

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


MAINTENANT = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def iso(jours):
    return (MAINTENANT - timedelta(days=jours)).isoformat()


def client(etat="En cours", parcours="Autonome", debut=20, relance=None, email="a@b.fr"):
    return {"id": "c1", "properties": {
        "État": {"type": "status", "status": {"name": etat}},
        "Parcours": {"type": "select", "select": {"name": parcours}},
        "E-mail": {"type": "email", "email": email},
        "Date de démarrage": {"type": "date", "date": {"start": iso(debut)[:10]}},
        "Dernière relance": {"type": "date", "date": {"start": iso(relance)[:10]} if relance is not None else None},
    }}


def entree(jours, fiche="fx"):
    return {"last_edited_time": iso(jours), "properties": {
        "Fiche Client": {"type": "relation", "relation": [{"id": fiche}]}}}


bilan = ns._BILAN_HEBDO_MASTER_ID
dash = {"nom": "Marie Test", "objectif_90j": "10 clients", "fiches": [
    {"id": "f-fini", "nom": "M - 9. MON OFFRE", "etat": "Terminé", "master_id": "x"},
    {"id": "f-ouv", "nom": "M - 11. MON TABLEAU DE PROSPECTION", "etat": "En cours", "master_id": "y",
     "priorite": {"type": "prioritaire", "zone": "Prospection"}},
    {"id": "fbilan", "nom": "M - 16. BILAN HEBDOMADAIRE : PROSPECTION", "etat": "En cours", "master_id": bilan},
], "personnalisation": {"zones_prioritaires": [{"zone": "Prospection"}]}}


def relance(row, entrees):
    with patch.object(ns, "_query_data_source", return_value=entrees), \
            patch.object(ns, "get_client_dashboard", return_value=dash):
        return ns._relance_du_client(row, MAINTENANT)


print("Relances")
r = relance(client(), [entree(9)])
check("inactif 9 jours -> relance", r and r["type"] == "inactif")
check("prenom et fiche prioritaire", "Prénom : Marie" in r["message"] and "MON TABLEAU DE PROSPECTION" in r["message"])
check("objet personnalise", r["objet"].startswith("Marie"))
check("actif recemment -> rien", relance(client(), [entree(2)]) is None)
check("relance il y a 3 jours -> rien", relance(client(relance=3), [entree(9)]) is None)
check("relance il y a 8 jours -> relance", relance(client(relance=8), [entree(9)]) is not None)
check("atelier exclu", relance(client(parcours="Atelier"), [entree(9)]) is None)
check("client termine exclu", relance(client(etat="Terminé"), [entree(9)]) is None)
check("sans e-mail exclu", relance(client(email=None), [entree(9)]) is None)
check("parcours fini (J100) exclu", relance(client(debut=100), [entree(9)]) is None)
check("aucune saisie depuis le debut -> inactif", relance(client(debut=10), [])["type"] == "inactif")

r = relance(client(debut=40), [entree(1), entree(9, "fbilan")])
check("J40 bilan oublie -> relance bilan", r and r["type"] == "bilan" and "BILAN HEBDOMADAIRE" in r["message"])
check("J40 bilan fait -> rien", relance(client(debut=40), [entree(1), entree(3, "fbilan")]) is None)
check("J20 actif, bilan pas encore ouvert -> rien", relance(client(debut=20), [entree(1)]) is None)

print("Marquage")
ecrit = []
with patch.object(ns, "_get_page", return_value={"properties": {"Nb relances": {"type": "number", "number": 2}}}), \
        patch.object(ns, "_update_page", side_effect=lambda pid, p: ecrit.append(p)):
    ns.marquer_relance_envoyee("c1")
check("compteur incremente", ecrit[0]["Nb relances"]["number"] == 3)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
