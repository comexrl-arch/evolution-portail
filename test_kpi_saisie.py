# Tests de POST /portal/kpi/{id} : saisie des valeurs et objectifs KPI par le
# client depuis le tableau de bord.
#
# Entierement mockes (aucun appel reseau reel vers Notion), meme style que
# test_portal_authz.py (script simple, pas de framework de test).
#
# Lancer : python test_kpi_saisie.py

import sys
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-kpi"

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


def bearer(client_page_id):
    return "Bearer " + portal_auth_service.create_session_token("client@test.com", client_page_id)


CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
KPI_A = "a9a9a9a9-a9a9-a9a9-a9a9-a9a9a9a9a9a9"
KPI_B = "b9b9b9b9-b9b9-b9b9-b9b9-b9b9b9b9b9b9"

DASHBOARDS = {
    CLIENT_A: {"kpi": [{"id": KPI_A, "nom": "Leads", "etat": "Pas commencé"}]},
    CLIENT_B: {"kpi": [{"id": KPI_B, "nom": "Leads", "etat": "En cours"}]},
}


def requete(valeurs):
    return portal_main.PortalKpiRequest(valeurs=valeurs)


def appeler(client, kpi_id, valeurs):
    with patch.object(ns, "get_client_dashboard", side_effect=lambda cid: DASHBOARDS[cid]), \
         patch.object(ns, "_update_page") as update:
        code, resultat = statut(
            portal_main.portal_update_kpi, kpi_id, requete(valeurs), authorization=bearer(client)
        )
    return code, resultat, update


print("Saisie d'un KPI par son client")
code, resultat, update = appeler(CLIENT_A, KPI_A, {"valeur_j0": 12, "objectif_j30": 20})
check("repond 200", code == 200)
check("renvoie le tableau de bord", resultat.get("dashboard") == DASHBOARDS[CLIENT_A])
proprietes = update.call_args[0][1] if update.called else {}
check("ecrit Valeur J0", proprietes.get("Valeur J0") == {"number": 12.0})
check("ecrit Objectif J30", proprietes.get("Objectif J30") == {"number": 20.0})
check("passe l'indicateur En cours", proprietes.get("État") == {"status": {"name": "En cours"}})

print("Effacement d'une valeur")
code, _, update = appeler(CLIENT_A, KPI_A, {"valeur_j30": None})
proprietes = update.call_args[0][1] if update.called else {}
check("repond 200", code == 200)
check("efface Valeur J30", proprietes.get("Valeur J30") == {"number": None})
check("ne change pas l'etat sans valeur", "État" not in proprietes)

print("Indicateur deja en cours : etat inchange")
code, _, update = appeler(CLIENT_B, KPI_B, {"valeur_j60": 3})
check("repond 200", code == 200)
check("pas d'ecriture de l'etat", "État" not in update.call_args[0][1])

print("Autorisation")
code, _, update = appeler(CLIENT_A, KPI_B, {"valeur_j0": 5})
check("KPI d'un autre client -> 404", code == 404)
check("aucune ecriture Notion", not update.called)
with patch.object(ns, "_update_page") as update:
    code, _ = statut(portal_main.portal_update_kpi, KPI_A, requete({"valeur_j0": 1}), authorization="")
check("sans session -> 401", code == 401)
check("aucune ecriture sans session", not update.called)

print("Validation des valeurs")
for label, valeurs in [
    ("champ inconnu", {"Nom": 3}),
    ("aucun champ", {}),
    ("texte", {"valeur_j0": "douze"}),
    ("negatif", {"valeur_j0": -1}),
    ("infini", {"valeur_j0": float("inf")}),
    ("booleen", {"valeur_j0": True}),
]:
    code, _, update = appeler(CLIENT_A, KPI_A, valeurs)
    check(f"{label} -> 400", code == 400)
    check(f"{label} : aucune ecriture", not update.called)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
