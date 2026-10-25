# Tests du report des bilans hebdomadaires dans les KPI (RDV, Nouveaux
# clients) et de l'analyse IA du bilan qui compare les semaines.
#
# Entierement mockes (aucun appel reseau reel vers Notion), meme style que
# test_kpi_saisie.py (script simple, pas de framework de test).
#
# Lancer : python test_kpi_bilans.py

import json
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


CLIENT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FICHE_BILAN = "f17f17f1-7f17-f17f-17f1-7f17f17f17f1"
BILAN = ns._BILAN_HEBDO_MASTER_ID
LIBELLES = {champ["cle"]: champ["libelle"] for champ in ns.FICHE_SCHEMAS[BILAN]["champs"]}


def entree(semaine, contacts, rdv, ventes, cree, propositions=0):
    donnees = {
        LIBELLES["semaine_du"]: semaine,
        LIBELLES["nb_contacts_tentes"]: str(contacts),
        LIBELLES["nb_rdv_obtenus"]: str(rdv),
        LIBELLES["nb_propositions_envoyees"]: str(propositions),
        LIBELLES["nb_ventes_conclues"]: str(ventes),
        LIBELLES["difficulte_principale"]: "Les relances",
    }
    return {
        "id": f"e-{semaine}-{cree}",
        "created_time": cree,
        "properties": {
            "Nom": {"type": "title", "title": [{"plain_text": "Client — bilan"}]},
            "Date": {"type": "date", "date": {"start": semaine}},
            "Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": json.dumps(donnees, ensure_ascii=False)}]},
        },
    }


PAGES = [
    entree("2026-09-07", 10, 2, 0, "2026-09-11T10:00:00Z"),   # J6  -> J30
    entree("2026-09-14", 12, 3, 1, "2026-09-18T10:00:00Z"),   # J13 -> J30
    entree("2026-09-14", 15, 4, 1, "2026-09-19T10:00:00Z"),   # meme semaine, ressaisie : l'emporte
    entree("2026-10-12", 20, 5, 2, "2026-10-16T10:00:00Z"),   # J41 -> J60
    entree("2026-12-28", 9, 9, 9, "2027-01-01T10:00:00Z"),    # J113 -> ignore
]

print("Historique des bilans")
with patch.object(ns, "_query_data_source", return_value=list(reversed(PAGES))):
    historique = ns._historique_bilans(FICHE_BILAN)
check("une ligne par semaine", [s["semaine_du"] for s in historique] == ["2026-09-07", "2026-09-14", "2026-10-12", "2026-12-28"])
check("la derniere saisie de la semaine l'emporte", historique[1]["rdv"] == 4.0 and historique[1]["contacts"] == 15.0)

print("Totaux par periode")
totaux = ns.totaux_bilans_par_periode(historique, "2026-09-01")
check("J30 = 2 bilans additionnes", totaux.get("valeur_j30") == {"nb_rdv_obtenus": 6.0, "nb_ventes_conclues": 1.0})
check("J60 = 1 bilan", totaux.get("valeur_j60") == {"nb_rdv_obtenus": 5.0, "nb_ventes_conclues": 2.0})
check("J90 absent (aucun bilan, apres J97 ignore)", "valeur_j90" not in totaux)
check("sans date de demarrage : rien", ns.totaux_bilans_par_periode(historique, None) == {})
check("semaine avant J0 comptee dans J30", ns.totaux_bilans_par_periode(historique[:1], "2026-09-10") == {"valeur_j30": {"nb_rdv_obtenus": 2.0, "nb_ventes_conclues": 0.0}})


def reporter(kpis, master=BILAN, demarrage="2026-09-01"):
    client_props = {"Date de démarrage": {"type": "date", "date": {"start": demarrage}}} if demarrage else {}
    with patch.object(ns, "_fiche_schema_for", return_value=({}, "16. BILAN", master)), \
         patch.object(ns, "_get_page", return_value={"properties": client_props}), \
         patch.object(ns, "_query_data_source", return_value=PAGES), \
         patch.object(ns, "_client_kpi", return_value=kpis), \
         patch.object(ns, "_update_page") as update, \
         patch.object(ns, "_create_page") as create:
        resultat = ns.reporter_bilans_dans_kpi(CLIENT, FICHE_BILAN)
    return resultat, update, create


print("Report dans les KPI existants")
KPIS = [
    {"id": "k-rdv", "nom": "RDV", "etat": "Pas commencé", "valeur_j30": None, "valeur_j60": None, "valeur_j90": 7},
    {"id": "k-clients", "nom": "Nouveaux clients", "etat": "En cours", "valeur_j30": 1, "valeur_j60": None},
    {"id": "k-leads", "nom": "Leads", "etat": "En cours"},
]
resultat, update, create = reporter(KPIS)
ecrits = {appel[0][0]: appel[0][1] for appel in update.call_args_list}
check("renvoie True", resultat is True)
check("RDV J30 et J60 ecrits", ecrits.get("k-rdv", {}).get("Valeur J30") == {"number": 6.0} and ecrits["k-rdv"].get("Valeur J60") == {"number": 5.0})
check("RDV J90 saisi a la main garde", "Valeur J90" not in ecrits.get("k-rdv", {}))
check("RDV passe En cours", ecrits.get("k-rdv", {}).get("État") == {"status": {"name": "En cours"}})
check("Nouveaux clients : J30 deja juste non reecrit", "Valeur J30" not in ecrits.get("k-clients", {}))
check("Nouveaux clients J60 ecrit", ecrits.get("k-clients", {}).get("Valeur J60") == {"number": 2.0})
check("Leads jamais touche", "k-leads" not in ecrits)
check("aucune creation", not create.called)

print("KPI absents : crees")
resultat, update, create = reporter([])
noms = [appel[0][1]["Nom"]["title"][0]["text"]["content"] for appel in create.call_args_list]
check("RDV et Nouveaux clients crees", sorted(noms) == ["Nouveaux clients", "RDV"])
check("relies au client", all(appel[0][1]["Client"] == {"relation": [{"id": CLIENT}]} for appel in create.call_args_list))

print("Cas sans report")
resultat, update, create = reporter(KPIS, master="autre-fiche")
check("autre fiche : False, rien ecrit", resultat is False and not update.called and not create.called)
resultat, update, create = reporter(KPIS, demarrage=None)
check("sans date de demarrage : False, rien ecrit", resultat is False and not update.called and not create.called)

print("Analyse IA du bilan hebdomadaire")
lignes = ns._lignes_historique_bilans(historique[:3])
check("une ligne par semaine", len(lignes) == 4)
check("taux calcules", "contacts → RDV 27%" in lignes[2] and "RDV → ventes 25%" in lignes[2])
check("pas de division par zero", "n/a" in ns._lignes_historique_bilans([{**historique[0], "contacts": 0, "rdv": 0}])[1])

DASHBOARD = {
    "nom": "Marie Test",
    "parcours": "Autonome",
    "fiches": [{"id": FICHE_BILAN, "master_id": BILAN, "nom": "Marie Test - 16. BILAN HEBDOMADAIRE : PROSPECTION"}],
}
ENTREE_IA = {"id": "e-ia", "properties": {
    "Client": {"type": "relation", "relation": [{"id": CLIENT}]},
    "Fiche Client": {"type": "relation", "relation": [{"id": FICHE_BILAN}]},
    "Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": json.dumps({"Nombre de rendez-vous obtenus": "5"})}]},
}}
with patch.object(ns, "get_client_dashboard", return_value=DASHBOARD), \
     patch.object(ns, "_query_data_source", return_value=PAGES):
    prompt = ns._prompt_retour_ia(ENTREE_IA)
check("prompt specifique au bilan", prompt["systeme"] == ns._RETOUR_IA_BILAN_SYSTEME)
check("historique dans le message", "Semaine du 2026-09-07" in prompt["message"] and "Semaine du 2026-10-12" in prompt["message"])

DASHBOARD_AUTRE = {**DASHBOARD, "fiches": [{"id": FICHE_BILAN, "master_id": "autre", "nom": "Marie Test - 10. POSITIONNEMENT"}]}
with patch.object(ns, "get_client_dashboard", return_value=DASHBOARD_AUTRE), \
     patch.object(ns, "_query_data_source") as requete:
    prompt = ns._prompt_retour_ia(ENTREE_IA)
check("autre fiche : prompt habituel", prompt["systeme"] == ns._RETOUR_IA_SYSTEME)
check("autre fiche : pas de lecture des bilans", not requete.called)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
