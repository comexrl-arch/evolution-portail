# Tests des retours IA sur les fiches (22/10/2026), entierement mockes :
# mise en file apres enregistrement, prompt construit avec le diagnostic,
# publication immediate en Autonome, relecture de 12 h en Coaching.
#
# Lancer : python test_retours_ia.py

import json
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


def props(statut=None, texte="", date=None):
    return {
        "Retour IA statut": {"type": "select", "select": {"name": statut} if statut else None},
        "Retour IA": {"type": "rich_text", "rich_text": [{"plain_text": texte}] if texte else []},
        "Retour IA date": {"type": "date", "date": {"start": date} if date else None},
    }


num = ns._NUMERO_TO_MASTER_ID
maintenant = datetime.now(timezone.utc)

print("Visibilite")
check("rien sans statut", ns._retour_ia_visible(props()) is None)
check("en cours", ns._retour_ia_visible(props("À générer")) == {"statut": "en_cours"})
check("publie", ns._retour_ia_visible(props("Publié", "Bravo", "2026-10-22T12:00:00+00:00"))["texte"] == "Bravo")
check("bloque jamais montre", ns._retour_ia_visible(props("Bloqué", "Bravo", "2026-10-22T12:00:00+00:00")) is None)
recent = (maintenant - timedelta(hours=1)).isoformat()
ancien = (maintenant - timedelta(hours=13)).isoformat()
check("coaching : en relecture 12 h", ns._retour_ia_visible(props("À relire", "Bravo", recent)) == {"statut": "relecture"})
check("coaching : visible apres 12 h", ns._retour_ia_visible(props("À relire", "Bravo", ancien))["statut"] == "publie")

print("Mise en file")
for numero, attendu in (("14", True), ("5", False), ("8", False)):
    ecrit = []
    with patch.object(ns, "_fiche_schema_for", return_value=({}, "x", num[numero])), \
            patch.object(ns, "_update_page", side_effect=lambda pid, p: ecrit.append(p)):
        check(f"fiche interne {numero} -> {attendu}", ns.demander_retour_ia("f", "e") is attendu and bool(ecrit) is attendu)

print("Prompt")
dash = {
    "nom": "Marie Test", "parcours": "Autonome", "objectif_90j": "10 clients",
    "fiches": [{"id": "fiche-1", "nom": "Marie - 11. MON TABLEAU DE PROSPECTION",
                "priorite": {"type": "prioritaire", "zone": "Prospection"}}],
    "personnalisation": {"scores": {"Offre": 3, "Prospection": 0}, "total": 3,
                         "zones_prioritaires": [{"zone": "Prospection"}]},
}
entree = {"id": "e1", "properties": {
    "Client": {"type": "relation", "relation": [{"id": "c1"}]},
    "Fiche Client": {"type": "relation", "relation": [{"id": "fiche-1"}]},
    "Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": json.dumps({"Canal :": "WhatsApp", "Vide :": "", "__x": 1})}]},
}}
with patch.object(ns, "get_client_dashboard", return_value=dash):
    prompt = ns._prompt_retour_ia(entree)
check("prenom seul", "Prénom : Marie" in prompt["message"] and "Test" not in prompt["message"])
check("scores dans le prompt", "Prospection 0/3" in prompt["message"])
check("pourquoi de la zone", ns._POURQUOI_PAR_ZONE["Prospection"] in prompt["message"])
check("reponses remplies seulement", "- Canal : WhatsApp" in prompt["message"] and "Vide" not in prompt["message"] and "__x" not in prompt["message"])
check("autonome", prompt["autonome"] is True)

print("Enregistrement")
ecrit = []
with patch.object(ns, "_update_page", side_effect=lambda pid, p: ecrit.append(p)):
    check("autonome publie", ns.enregistrer_retour_ia("e1", " Super ", True) == "Publié")
    check("coaching a relire", ns.enregistrer_retour_ia("e1", "Super", False) == "À relire")
check("texte nettoye", ecrit[0]["Retour IA"]["rich_text"][0]["text"]["content"] == "Super")
try:
    ns.enregistrer_retour_ia("e1", "  ", True)
    check("texte vide refuse", False)
except ValueError:
    check("texte vide refuse", True)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
