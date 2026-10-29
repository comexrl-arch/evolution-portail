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
    reel = ns._scores_reels("fb", MAINTENANT)
check("1 bilan sur 4 semaines : les semaines vides comptent pour zero", reel["scores"]["Prospection"] == 1)
check("1 bilan sur 4 semaines : suivi 0", reel["scores"]["Suivi commercial"] == 0)

with patch.object(ns, "_query_data_source", return_value=[]):
    reel = ns._scores_reels("fb", MAINTENANT)
check("aucun bilan sur 4 semaines : prospection et suivi a 0", reel["scores"]["Prospection"] == 0 and reel["scores"]["Suivi commercial"] == 0)
check("aucun bilan : conversion du diagnostic", "Conversion" not in reel["scores"])

with patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 0, 0)]):
    check("bilan ouvert depuis 1 semaine : diagnostic garde", ns._scores_reels("fb", MAINTENANT, semaines_attendues=1) is None)
    reel = ns._scores_reels("fb", MAINTENANT, semaines_attendues=2)
check("1 bilan sur 2 semaines : suivi 1", reel["scores"]["Suivi commercial"] == 1)

with patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 0, 0), bilan(9, 12, 0, 0), bilan(16, 12, 0, 0)]):
    reel = ns._scores_reels("fb", MAINTENANT)
check("3 bilans sur 4 : suivi 2, 9 contacts/sem -> prospection 2", reel["scores"]["Suivi commercial"] == 2 and reel["scores"]["Prospection"] == 2)

print("Semaines de bilan")
check("avant l'ouverture du bilan (J31) : 0", ns._semaines_de_bilan(20, ns._FICHE_JOUR) == 0)
check("J45 : 2 semaines", ns._semaines_de_bilan(45, ns._FICHE_JOUR) == 2)
check("J80 : fenetre de 4", ns._semaines_de_bilan(80, ns._FICHE_JOUR) == 4)
check("sans date : seules les semaines remplies", ns._semaines_de_bilan(None, ns._FICHE_JOUR) == 0)
check("Atelier sans bilan : 0", ns._semaines_de_bilan(10, ns._ATELIER_JOUR) == 0)

print("Offre et Visibilite suivent les fiches")
num = ns._NUMERO_TO_MASTER_ID
diag = {"Offre": 2, "Visibilité": 1, "Prospection": 0, "Conversion": 1, "Suivi commercial": 1}


def avec_etats(etats):
    liste = fiches()
    for f in liste:
        for n, etat in etats.items():
            if f["master_id"] == num[n]:
                f["etat"] = etat
    return liste


t = ns._scores_travail(avec_etats({"9": "Terminé", "11": "Terminé"}), diag, 6, ns._FICHE_JOUR)
check("J6 : fiches 9 et 11 terminees -> offre +1, visibilite +1", t["scores"] == {"Offre": 3, "Visibilité": 2})
t = ns._scores_travail(avec_etats({"9": "En cours"}), diag, 12, ns._FICHE_JOUR)
check("J12 : fiche 9 ouverte a J4 pas finie -> offre -1", t["scores"]["Offre"] == 1)
check("constat du retard", "en retard" in t["constats"]["Offre"])
t = ns._scores_travail(avec_etats({"9": "Terminé", "11": "Terminé"}), diag, 12, ns._FICHE_JOUR)
check("J12 : fiches 10 et 12 ouvertes depuis 1 jour -> pas de changement", "Offre" not in t["scores"] and "Visibilité" not in t["scores"])
t = ns._scores_travail(avec_etats({}), {**diag, "Offre": 0}, 12, ns._FICHE_JOUR)
check("jamais sous 0", t["scores"]["Offre"] == 0)
check("sans date : diagnostic", ns._scores_travail(avec_etats({}), diag, None, ns._FICHE_JOUR)["scores"] == {})

with patch.object(ns, "_list_children", return_value=fiche8), \
        patch.object(ns, "_query_data_source", return_value=[bilan(2, 12, 4, 0), bilan(9, 10, 2, 0), bilan(16, 14, 2, 0), bilan(23, 8, 2, 0)]):
    perso = ns._personnaliser_parcours(fiches())
check("prospection devient un point fort", "Prospection" in perso["zones_fortes"])
check("conversion prioritaire d'apres les chiffres", perso["zones_prioritaires"][0]["zone"] == "Conversion" and perso["zones_prioritaires"][0]["source"] == "chiffres")
check("score du diagnostic conserve", perso["total"] == 8 and perso["scores_diagnostic"]["Prospection"] == 0)

with patch.object(ns, "_list_children", return_value=fiche8), patch.object(ns, "_query_data_source", return_value=[]):
    liste = fiches()
    for f in liste:
        if f["master_id"] in (num["9"], num["11"], num["14"], num["10"], num["12"]):
            f["etat"] = "Terminé"
    perso = ns._personnaliser_parcours(liste, 60, ns._FICHE_JOUR)
check("J60 sans aucun bilan : prospection 0, suivi 0", perso["scores"]["Prospection"] == 0 and perso["scores"]["Suivi commercial"] == 0)
check("J60 sans aucun bilan : le total baisse", perso["total_actuel"] < perso["total"] + 1 and perso["scores"]["Suivi commercial"] < perso["scores_diagnostic"]["Suivi commercial"])

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
