# Tests du parcours adapte au diagnostic (22/10/2026), entierement mockes :
# les fiches des zones faibles de la fiche 8 sont marquees prioritaires,
# celles des zones a 3/3 "point fort", rien tant que la fiche 8 n'est pas
# terminee.
#
# Lancer : python test_parcours_adapte.py

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


def ligne(texte):
    return {"type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"plain_text": texte, "annotations": {}}]}}


def fiches(etat8="Terminé"):
    liste = [{"id": f"f-{mid}", "master_id": mid, "etat": "Pas commencé"} for mid in ns.FICHE_SCHEMAS]
    for fiche in liste:
        if fiche["master_id"] == ns._DIAGNOSTIC_FICHE8_MASTER_ID:
            fiche["etat"] = etat8
    return liste


fiche8 = [
    ligne("Score d'Offre : 3 / 3"),
    ligne("Score de Visibilité : 3 / 3"),
    ligne("Score de Prospection : 0 / 3"),
    ligne("Score de Conversion : 1 / 3"),
    ligne("Score de Suivi : 1 / 3"),
    ligne("SCORE TOTAL : 8 / 15"),
]

print("Parcours adapte")
sans_bilans = patch.object(ns, "_query_data_source", return_value=[])
sans_bilans.start()
with patch.object(ns, "_list_children", return_value=fiche8):
    liste = fiches()
    perso = ns._personnaliser_parcours(liste)
    par_mid = {f["master_id"]: f for f in liste}
    num = ns._NUMERO_TO_MASTER_ID

    check("scores lus", perso["scores"] == {"Offre": 3, "Visibilité": 3, "Prospection": 0, "Conversion": 1, "Suivi commercial": 1})
    check("zones prioritaires dans l'ordre", [z["zone"] for z in perso["zones_prioritaires"]] == ["Prospection", "Conversion", "Suivi commercial"])
    check("zones fortes", perso["zones_fortes"] == ["Offre", "Visibilité"])
    check("tableau de prospection prioritaire", par_mid[num["14"]]["priorite"] == {"type": "prioritaire", "zone": "Prospection"})
    check("bilan hebdo : la zone la plus faible gagne", par_mid[num["17"]]["priorite"]["zone"] == "Prospection")
    check("trame d'entretien prioritaire", par_mid[num["18"]]["priorite"]["zone"] == "Conversion")
    check("offre actuelle = point fort", par_mid[num["9"]]["priorite"]["type"] == "point_fort")
    check("diagnostic non marque", "priorite" not in par_mid[num["3"]])
    check("fiches cliquables renvoyees", perso["zones_prioritaires"][1]["fiches"] == [f"f-{num['18']}", f"f-{num['16']}"])

    check("fiche 8 non terminee : parcours standard", ns._personnaliser_parcours(fiches("En cours")) is None)

with patch.object(ns, "_list_children", return_value=fiche8[:2]):
    check("fiche 8 incomplete : parcours standard", ns._personnaliser_parcours(fiches()) is None)

tout3 = [ligne(f"{lib} : 3 / 3") for lib in ns._FICHE8_LIBELLE_SCORE.values()]
with patch.object(ns, "_list_children", return_value=tout3):
    perso = ns._personnaliser_parcours(fiches())
    check("15/15 : aucune zone prioritaire", perso["zones_prioritaires"] == [])

with patch.object(ns, "_list_children", side_effect=RuntimeError("Notion")):
    check("erreur Notion : parcours standard", ns._personnaliser_parcours(fiches()) is None)

sans_bilans.stop()

print("Diagnostic vivant")
from datetime import datetime, timedelta, timezone

MAINTENANT = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def bilan(jours, contacts, rdv, ventes):
    donnees = {"Semaine du (identifiant de l'entrée)": (MAINTENANT - timedelta(days=jours)).strftime("%Y-%m-%d"),
               "Nombre de contacts tentés": str(contacts), "Nombre de rendez-vous obtenus": str(rdv),
               "Nombre de ventes conclues": str(ventes)}
    return {"id": f"b{jours}", "properties": {
        "Date": {"type": "date", "date": {"start": "2026-10-01"}},
        "Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": __import__("json").dumps(donnees)}]}}}


with patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 4, 0), bilan(9, 10, 2, 0), bilan(16, 14, 2, 0), bilan(23, 8, 2, 0)]):
    reel = ns._scores_reels("fb", MAINTENANT)
check("4 bilans : prospection 11/sem -> 3", reel["scores"]["Prospection"] == 3)
check("10 RDV, 0 vente -> conversion 0", reel["scores"]["Conversion"] == 0)
check("4 bilans -> suivi 3", reel["scores"]["Suivi commercial"] == 3)
check("constat chiffre", "0 vente(s) pour 10 rendez-vous" in reel["constats"]["Conversion"])

with patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 0, 0), bilan(9, 12, 0, 0)]):
    reel = ns._scores_reels("fb", MAINTENANT)
check("2 bilans : prospection plafonnee a 2", reel["scores"]["Prospection"] == 2)
check("sans RDV : conversion du diagnostic", "Conversion" not in reel["scores"])

with patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 0, 0), bilan(40, 12, 0, 0)]):
    check("1 seul bilan recent : pas de chiffres", ns._scores_reels("fb", MAINTENANT) is None)

with patch.object(ns, "_list_children", return_value=fiche8), \
        patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 4, 0), bilan(9, 10, 2, 0), bilan(16, 14, 2, 0), bilan(23, 8, 2, 0)]):
    perso = ns._personnaliser_parcours(fiches())
check("prospection devient un point fort", "Prospection" in perso["zones_fortes"])
check("conversion prioritaire d'apres les chiffres", perso["zones_prioritaires"][0]["zone"] == "Conversion" and perso["zones_prioritaires"][0]["source"] == "chiffres")
check("score du diagnostic conserve", perso["total"] == 8 and perso["scores_diagnostic"]["Prospection"] == 0)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
