# Tests des brouillons pre-remplis par l'IA (22/10/2026), Gemini et Notion mockes.
#
# Lancer : python test_brouillons.py

import sys
from unittest.mock import patch

from backend.services import brouillon_service as bs
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


POSITIONNEMENT = ns._NUMERO_TO_MASTER_ID["11"]
SCRIPT = ns._NUMERO_TO_MASTER_ID["15"]
OFFRE = ns._NUMERO_TO_MASTER_ID["9"]

champs_positionnement = [
    {"cle": "q1", "libelle": "Ma phrase officielle :"},
    {"cle": "q2", "libelle": "Ma présentation flash (à l'oral, 10 secondes) :"},
    {"cle": "q3", "libelle": "Ma bio de profil (à l'écrit : WhatsApp, Facebook, LinkedIn, site) :"},
]
sources = [{"nom": "9. MON OFFRE ACTUELLE", "reponses": [("Mon offre :", "Repas créoles livrés aux entreprises")]}]
page = {"properties": {"Activité": {"type": "rich_text", "rich_text": [{"plain_text": "Traiteur"}]}}}
appels = []


def faux_gemini(reponse):
    def _f(systeme, echanges, **kwargs):
        appels.append((systeme, echanges))
        return reponse
    return _f


print("Brouillons")
with patch.object(bs.ia_service, "enabled", return_value=True):
    check("disponible sur positionnement", bs.disponible(POSITIONNEMENT))
    check("disponible sur script", bs.disponible(SCRIPT))
    check("pas sur l'offre", not bs.disponible(OFFRE))

with patch.object(bs.ia_service, "enabled", return_value=False):
    check("indisponible sans cle Gemini", not bs.disponible(POSITIONNEMENT))

json_ia = '```json\n{"Ma phrase officielle": "J\'aide les entreprises...", "ma présentation flash": "Je livre...", "ma bio de profil": "Traiteur créole"}\n```'

with patch.object(bs.ia_service, "generer", side_effect=faux_gemini(json_ia)), \
        patch.object(bs.notion_service, "reponses_des_fiches", return_value=sources) as lecture, \
        patch.object(bs.notion_service, "_get_page", return_value=page):
    r = bs.proposer("c1", [], POSITIONNEMENT, champs_positionnement)
    check("les 3 champs remplis", set(r["valeurs"]) == {"q1", "q2", "q3"})
    check("balises ```json retirees", r["valeurs"]["q1"].startswith("J'aide"))
    check("reponses des fiches precedentes envoyees", "Repas créoles" in appels[-1][1][0]["texte"])
    check("activite du client envoyee", "Traiteur" in appels[-1][1][0]["texte"])
    check("sources = offre et cible", lecture.call_args[0][2] == [OFFRE, ns._NUMERO_TO_MASTER_ID["10"]])

    try:
        bs.proposer("c1", [], OFFRE, champs_positionnement)
        check("LookupError hors fiches de redaction", False)
    except LookupError:
        check("LookupError hors fiches de redaction", True)

with patch.object(bs.ia_service, "generer", side_effect=faux_gemini("Désolé, je ne peux pas.")), \
        patch.object(bs.notion_service, "reponses_des_fiches", return_value=[]), \
        patch.object(bs.notion_service, "_get_page", return_value=page):
    try:
        bs.proposer("c1", [], POSITIONNEMENT, champs_positionnement)
        check("RuntimeError si reponse non JSON", False)
    except RuntimeError:
        check("RuntimeError si reponse non JSON", True)

bs._compteurs.clear()
with patch.object(bs.ia_service, "generer", side_effect=faux_gemini('{"ma phrase officielle": "x"}')), \
        patch.object(bs.notion_service, "reponses_des_fiches", return_value=[]), \
        patch.object(bs.notion_service, "_get_page", return_value=page):
    for _ in range(bs._MAX_APPELS_JOUR):
        bs.proposer("c2", [], POSITIONNEMENT, champs_positionnement)
    try:
        bs.proposer("c2", [], POSITIONNEMENT, champs_positionnement)
        check("quota journalier", False)
    except PermissionError:
        check("quota journalier", True)

print("Lecture des fiches precedentes")
fiches = [{"id": "f9", "master_id": OFFRE, "nom": "9. MON OFFRE ACTUELLE"}]
entree = {"id": "e1", "date": "2026-10-20", "donnees": {"a": "Repas créoles", "b": "", "c": True}, "retour_ia": None}
champs_offre = [{"cle": "a", "libelle": "Mon offre :"}, {"cle": "b", "libelle": "Prix :"}, {"cle": "c", "libelle": "Case"}]
with patch.object(ns, "_query_data_source", return_value=[{}]), \
        patch.object(ns, "_parse_entry", return_value=entree), \
        patch.object(ns, "_champs_for", return_value=champs_offre):
    r = ns.reponses_des_fiches("c1", fiches, [OFFRE, SCRIPT])
    check("seules les reponses texte non vides", r == [{"nom": "9. MON OFFRE ACTUELLE", "reponses": [("Mon offre :", "Repas créoles")]}])

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
