# Tests du lot 3 : serie de regularite des bilans hebdomadaires et bilan J90
# redige par Idris (disponibilite, contenu du prompt, route).
#
# Entierement mockes (ni Notion ni Gemini), meme style que test_kpi_saisie.py.
#
# Lancer : python test_bilan_j90_regularite.py

import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import idris_service as idris
from backend.services import ia_service, notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-lot3"

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


print("Serie de semaines")
mercredi = date(2026, 10, 28)  # semaine du lundi 26/10
check("3 semaines d'affilee jusqu'a cette semaine", ns.serie_de_semaines(["2026-10-26", "2026-10-19", "2026-10-12"], mercredi) == 3)
check("cette semaine pas encore faite : compte depuis la precedente", ns.serie_de_semaines(["2026-10-19", "2026-10-12"], mercredi) == 2)
check("un trou casse la serie", ns.serie_de_semaines(["2026-10-26", "2026-10-12", "2026-10-05"], mercredi) == 1)
check("dernier bilan il y a 2 semaines : 0", ns.serie_de_semaines(["2026-10-12"], mercredi) == 0)
check("date en milieu de semaine ramenee au lundi", ns.serie_de_semaines(["2026-10-23", "2026-10-15"], mercredi) == 2)
check("aucune semaine : 0", ns.serie_de_semaines([], mercredi) == 0)
check("date illisible ignoree", ns.serie_de_semaines(["n/a", "2026-10-26"], mercredi) == 1)

print("Regularite dans le tableau de bord")
BILAN = ns._BILAN_HEBDO_MASTER_ID
ouvert = [{"id": "fb", "master_id": BILAN, "acces": "🔓 Ouvert"}]
lundi = datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).date().weekday())
historique = [{"semaine_du": (lundi - timedelta(days=7 * k)).isoformat()} for k in (2, 1, 0)]
with patch.object(ns, "_historique_bilans", return_value=historique):
    regularite = ns._regularite_bilans(ouvert)
check("serie, total et dernier bilan", regularite == {"serie": 3, "semaines": 3, "derniere": lundi.isoformat()})
check("bilan bloque : rien", ns._regularite_bilans([{**ouvert[0], "acces": "🔒 Bloqué"}]) is None)
check("sans fiche bilan : rien", ns._regularite_bilans([]) is None)
with patch.object(ns, "_historique_bilans", side_effect=RuntimeError("Notion")):
    check("Notion en erreur : rien, sans lever", ns._regularite_bilans(ouvert) is None)

print("Disponibilite du bilan J90")
aujourd_hui = datetime.now(timezone.utc).date()
debut = lambda jours: (aujourd_hui - timedelta(days=jours)).isoformat()
fiches_en_cours = [{"etat": "Terminé"}, {"etat": "En cours"}]
check("avant J80 : ferme", not idris.bilan_final_disponible({"fiches": fiches_en_cours, "date_demarrage": debut(70)}))
check("a J80 : ouvert", idris.bilan_final_disponible({"fiches": fiches_en_cours, "date_demarrage": debut(80)}))
check("toutes les fiches terminees : ouvert", idris.bilan_final_disponible({"fiches": [{"etat": "Terminé"}], "date_demarrage": debut(20)}))
check("sans fiche : ferme", not idris.bilan_final_disponible({"fiches": [], "date_demarrage": debut(90)}))

print("Route du bilan J90")
CLIENT = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
BEARER = "Bearer " + portal_auth_service.create_session_token("client@test.com", CLIENT)
DASHBOARD = {
    "nom": "Marie Test", "parcours": None, "date_demarrage": debut(85),
    "fiches": [{"id": "f1", "nom": "Marie - 1. X", "etat": "Terminé"}, {"id": "f2", "nom": "Marie - 2. Y", "etat": "En cours"}],
    "personnalisation": {"scores": {"Offre": 2}, "scores_diagnostic": {"Offre": 1}, "total": 7, "total_actuel": 10, "zones_prioritaires": []},
    "kpi": [{"nom": "RDV", "valeur_j0": 2.0, "valeur_j30": 6.0, "valeur_j60": None}],
    "regularite": {"serie": 4, "semaines": 9, "derniere": "2026-10-19"},
}


def appeler(dashboard):
    idris._compteurs.clear()
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
         patch.object(ns, "get_client_dashboard", return_value=dashboard), \
         patch.object(ns, "_get_page", return_value={"properties": {}}), \
         patch.object(ns, "reponses_des_fiches", return_value=[{"nom": "Marie - 22. MON BILAN J90", "reponses": [("Qu'est-ce qui a le mieux fonctionné pour toi ?", "Le bouche-à-oreille")]}]), \
         patch.object(ia_service, "generer", return_value="Bravo Marie.") as generer:
        code, resultat = statut(portal_main.portal_bilan_j90, authorization=BEARER)
    return code, resultat, generer


code, resultat, generer = appeler(DASHBOARD)
check("J85 : 200 avec le texte", code == 200 and resultat == {"texte": "Bravo Marie."})
message = generer.call_args[0][1][0]["texte"] if generer.called else ""
check("prompt dedie", generer.called and generer.call_args[0][0] == idris._SYSTEME_BILAN_J90)
check("fiches validees", "Fiches validées : 1 sur 2" in message)
check("diagnostic avant / apres", "7/15 au départ, 10/15 aujourd'hui" in message)
check("KPI J0 contre derniere valeur", "RDV : 2 à J0, 6 à J30" in message)
check("regularite", "Bilans hebdomadaires remplis : 9" in message)
check("reponses au bilan J90", "Le bouche-à-oreille" in message)
code, _, generer = appeler({**DASHBOARD, "date_demarrage": debut(40)})
check("J40 : 403 sans appel IA", code == 403 and not generer.called)
code, _ = statut(portal_main.portal_bilan_j90, authorization="")
check("sans session : 401", code == 401)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
