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

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
