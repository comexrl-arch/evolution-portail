# Tests de l'entrainement aux objections (22/10/2026), Gemini mocke.
#
# Lancer : python test_entrainement.py

import sys
from unittest.mock import patch

from backend.services import entrainement_service as es

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


appels = []


def faux_gemini(systeme, echanges, **kwargs):
    appels.append((systeme, echanges))
    return "réponse"


page = {"properties": {"Activité": {"type": "rich_text", "rich_text": [{"plain_text": "Traiteur"}]}}}

print("Entrainement")
with patch.object(es.ia_service, "generer", side_effect=faux_gemini), \
        patch.object(es.notion_service, "_get_page", return_value=page):
    r = es.repondre("c1", "trop_cher", [])
    check("ouverture par le prospect", r == {"role": "prospect", "texte": "réponse"})
    check("activite du client dans le role", "Traiteur" in appels[-1][0])
    check("le prospect est le modele", appels[-1][1][0]["role"] == "user")

    historique = [{"role": "prospect", "texte": "Trop cher"}, {"role": "client", "texte": "Pourquoi ?"}]
    es.repondre("c1", "trop_cher", historique)
    check("roles convertis", [e["role"] for e in appels[-1][1]] == ["user", "model", "user"])

    r = es.repondre("c1", "trop_cher", historique, terminer=True)
    check("retour du coach", r["role"] == "coach" and "Utilisateur : Pourquoi ?" in appels[-1][1][0]["texte"])

    long = [{"role": "client" if i % 2 else "prospect", "texte": "x"} for i in range(12)]
    check("6 reponses : retour automatique", es.repondre("c1", "trop_cher", long)["role"] == "coach")

    for erreur, args in ((ValueError, ("c1", "inconnu", [])), (ValueError, ("c1", "trop_cher", [{"role": "client", "texte": "x" * 900}]))):
        try:
            es.repondre(*args)
            check(f"{erreur.__name__} attendu", False)
        except erreur:
            check(f"{erreur.__name__} attendu", True)

    es._compteurs.clear()
    for _ in range(es._MAX_APPELS_JOUR):
        es.repondre("c2", "trop_cher", [])
    try:
        es.repondre("c2", "trop_cher", [])
        check("quota journalier", False)
    except PermissionError:
        check("quota journalier", True)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
