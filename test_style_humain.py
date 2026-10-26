# Tests de la charte d'ecriture d'Idris (demande de Rony du 26/10/2026) :
# style humain ajoute a tous les prompts, nettoyage des tirets longs et
# orthographe RL-eVolution.
#
# Entierement mockes (pas d'appel Gemini).
#
# Lancer : python test_style_humain.py

import sys
from unittest.mock import MagicMock, patch

from backend.services import (
    bibliotheque_service, brouillon_service, entrainement_service, fidelite_service,
    ia_service, idris_service, notion_service as ns,
)

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


print("Nettoyage du texte")
check("tiret long entre deux mots -> virgule", ia_service.humaniser("Ta semaine — belle progression") == "Ta semaine, belle progression")
check("tiret long en debut de ligne -> puce", ia_service.humaniser("— un\n– deux") == "- un\n- deux")
check("tiret long colle -> trait d'union", ia_service.humaniser("J30—J60") == "J30-J60")
check("orthographe de la marque", ia_service.humaniser("RL-Evolution, RL Evolution et RL-evolution") == "RL-eVolution, RL-eVolution et RL-eVolution")
check("texte propre inchange", ia_service.humaniser("Bonjour Marie, 3 rendez-vous.") == "Bonjour Marie, 3 rendez-vous.")

print("Charte ajoutee aux prompts")
check("ajoutee une seule fois", ia_service.avec_style(ia_service.avec_style("Tu es Idris.")).count(ia_service._MARQUE_STYLE) == 1)
for nom, prompt in {
    "retour IA (n8n)": ns._RETOUR_IA_SYSTEME,
    "analyse du bilan (n8n)": ns._RETOUR_IA_BILAN_SYSTEME,
    "relance (n8n)": ns._RELANCE_SYSTEME,
}.items():
    check(f"{nom} : charte presente", ia_service._MARQUE_STYLE in prompt)

reponse = MagicMock()
reponse.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Bien joué — continue chez RL-Evolution."}]}}]}
with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), patch.object(ia_service.requests, "post", return_value=reponse) as post:
    texte = ia_service.generer("Tu es Idris.", [{"role": "user", "texte": "Salut"}])
envoye = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
check("generer envoie la charte a Gemini", envoye.startswith("Tu es Idris.") and ia_service._MARQUE_STYLE in envoye)
check("generer nettoie la reponse", texte == "Bien joué, continue chez RL-eVolution.")

with patch.object(ns, "_update_page") as update:
    ns.enregistrer_retour_ia("e1", "Bravo — tu avances.", autonome=True)
check("retour IA venu de n8n nettoye", update.call_args[0][1]["Retour IA"]["rich_text"][0]["text"]["content"] == "Bravo, tu avances.")

print("Plus aucun RL-Evolution dans les prompts d'Idris")
prompts = [
    bibliotheque_service._SYSTEME_PERSONNALISER, entrainement_service._SYSTEME_COACH, fidelite_service._SYSTEME_RECAP,
    idris_service._SYSTEME_QUESTION, idris_service._SYSTEME_MESSAGE, idris_service._SYSTEME_RDV, idris_service._SYSTEME_BILAN_J90,
    brouillon_service._SYSTEME, ns._RETOUR_IA_SYSTEME, ns._RETOUR_IA_BILAN_SYSTEME, ns._RELANCE_SYSTEME,
]
check("orthographe RL-eVolution partout", all("RL-Evolution" not in p for p in prompts) and all("RL-eVolution" in p for p in prompts))

print("Fiche lisible dans le recap")
check("numero et casse", fidelite_service._fiche_lisible("9. MON OFFRE ACTUELLE") == "la fiche 9, « Mon offre actuelle »")
check("sans numero", fidelite_service._fiche_lisible("BONUS") == "« Bonus »")
check("date courte", fidelite_service._date_courte("2026-10-19") == "19/10")

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
