# Tests de backend/services/notion_service.py::onboard_client et
# ::_repair_missing_fiches, entierement mockes (aucun appel reseau reel vers
# Notion) : verifie l'idempotence de l'onboarding, le rollback en cas
# d'echec en cours de route, le renseignement des KPI J0 quand le coach les
# fournit, et l'auto-reparation d'un client dont la duplication de fiches
# est incomplete. Meme style que
# test_routeur.py/test_routeur_v0_2.py (script simple, pas de framework de
# test), mais entierement mocke plutot que contre un serveur live : ce
# fichier ne depend d'aucun backend demarre ni d'aucune cle API.
#
# Lancer : python test_onboarding.py

import sys
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


print("=" * 80)
print("TEST 1/4 : idempotence - un email deja onboarde bloque l'appel")
print("=" * 80)

with patch.object(ns, "find_client_by_email", return_value={"id": "existing-123"}):
    try:
        ns.onboard_client("Test Idem", "existing@test.com")
        check("leve une RuntimeError pour un email deja existant", False)
    except RuntimeError as error:
        check("leve une RuntimeError pour un email deja existant", True)
        check("le message mentionne la page Notion existante", "existing-123" in str(error))
        check("le message parle explicitement de doublon", "doublon" in str(error))


print("\n" + "=" * 80)
print("TEST 2/4 : rollback complet si une creation de page echoue en cours de route")
print("=" * 80)

created = []
archived = []


def fake_create_page(data_source_id, properties):
    if len(created) == 3:
        raise RuntimeError("Erreur Notion simulee (creation page)")

    page_id = f"page-{len(created)}"
    created.append(page_id)
    return {"id": page_id}


def fake_archive_page(page_id):
    archived.append(page_id)


with patch.object(ns, "find_client_by_email", return_value=None), \
     patch.object(ns, "_create_page", side_effect=fake_create_page), \
     patch.object(ns, "_archive_page", side_effect=fake_archive_page):
    try:
        ns.onboard_client("Test Rollback", "new@test.com")
        check("leve une RuntimeError quand une creation echoue", False)
    except RuntimeError as error:
        check("leve une RuntimeError quand une creation echoue", True)
        check("le message confirme un rollback propre (aucun residu)", "archivees automatiquement" in str(error))
        check("toutes les pages creees avant l'echec sont archivees", set(archived) == set(created) and len(archived) == 3)


print("\n" + "=" * 80)
print("TEST 3/4 : rollback partiel - signale les pages orphelines si l'archivage echoue aussi")
print("=" * 80)

created = []


def fake_create_page_2(data_source_id, properties):
    if len(created) == 2:
        raise RuntimeError("Erreur Notion simulee")

    page_id = f"page-{len(created)}"
    created.append(page_id)
    return {"id": page_id}


def fake_archive_page_2(page_id):
    if page_id == "page-0":
        raise RuntimeError("Archivage impossible (simule)")


with patch.object(ns, "find_client_by_email", return_value=None), \
     patch.object(ns, "_create_page", side_effect=fake_create_page_2), \
     patch.object(ns, "_archive_page", side_effect=fake_archive_page_2):
    try:
        ns.onboard_client("Test Partial", "partial@test.com")
        check("leve une RuntimeError quand une creation echoue", False)
    except RuntimeError as error:
        check("leve une RuntimeError quand une creation echoue", True)
        check("le message signale un rollback partiel", "Rollback partiel" in str(error))
        check("le message liste la page orpheline restante", "page-0" in str(error))


print("\n" + "=" * 80)
print("TEST 4/4 : KPI J0 - renseignes quand fournis par le coach, signales sinon")
print("=" * 80)

created_props = []


def fake_create_page_3(data_source_id, properties):
    created_props.append((data_source_id, properties))
    return {"id": f"page-{len(created_props)}"}


with patch.object(ns, "find_client_by_email", return_value=None), \
     patch.object(ns, "_create_page", side_effect=fake_create_page_3), \
     patch.object(ns, "send_portal_invite", return_value=None):
    result = ns.onboard_client(
        "Test KPI", "kpi@test.com",
        kpi_j0={"leads_j0": 12, "rdv_j0": None, "nouveaux_clients_j0": 3, "ca_j0": ""},
    )

kpi_pages = {
    p["Nom"]["title"][0]["text"]["content"]: p
    for ds, p in created_props
    if ds == ns.KPI_DATA_SOURCE_ID
}

check("4 lignes KPI creees", len(kpi_pages) == 4)
check("'Leads' recoit Valeur J0=12 et passe En cours", kpi_pages["Leads"].get("Valeur J0", {}).get("number") == 12.0 and kpi_pages["Leads"]["État"]["status"]["name"] == "En cours")
check("'Nouveaux clients' recoit Valeur J0=3", kpi_pages["Nouveaux clients"].get("Valeur J0", {}).get("number") == 3.0)
check("'RDV' reste vide (pas de valeur fournie)", "Valeur J0" not in kpi_pages["RDV"] and kpi_pages["RDV"]["État"]["status"]["name"] == "Pas commencé")
check("kpi_a_completer signale les 2 KPI sans valeur", set(result["kpi_a_completer"]) == {"RDV", "Chiffre d’affaires"})


print("\n" + "=" * 80)
print("TEST 5/5 : reparation automatique des fiches manquantes")
print("=" * 80)

premiere_master_id = ns._fiche_master_items_sorted()[0][0]
fiches_existantes = [{"master_id": premiere_master_id, "nom": "Test - 0. ..."}]
created_fiches = []


def fake_create_page_4(data_source_id, properties):
    created_fiches.append(properties)
    return {"id": f"repaired-{len(created_fiches)}"}


with patch.object(ns, "_create_page", side_effect=fake_create_page_4), \
     patch.object(ns, "_fiche_summary", side_effect=lambda page_id: {"id": page_id, "master_id": "peu-importe", "nom": "recreee"}):
    resultat = ns._repair_missing_fiches("client-x", "Test", fiches_existantes)

nb_total_master = len(ns._fiche_master_items_sorted())
master_ids_crees = {
    p["⁠[DB] Fiches Master"]["relation"][0]["id"].replace("-", "")
    for p in created_fiches
}

check("cree exactement les fiches manquantes (toutes sauf celle deja presente)", len(created_fiches) == nb_total_master - 1)
check("liste retournee = existantes + nouvelles", len(resultat) == nb_total_master)
check("ne recree pas de fiche pour le master deja present", premiere_master_id not in master_ids_crees)

created_fiches.clear()

with patch.object(ns, "_create_page", side_effect=fake_create_page_4):
    ns._repair_missing_fiches("client-x", "Test", [
        {"master_id": mid, "nom": "deja la"} for mid, _ in ns._fiche_master_items_sorted()
    ])

check("client deja complet : aucune fiche recreee (idempotent)", len(created_fiches) == 0)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
