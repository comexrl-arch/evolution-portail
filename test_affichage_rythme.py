# Tests du rythme du parcours (affichage du 26/10/2026) : bandeau « Ton cap
# 90 jours » du tableau de bord (jour, etapes de la frise, fiches en retard).
#
# Entierement mockes (ni Notion ni Gemini), meme style que test_kpi_saisie.py.
#
# Lancer : python test_affichage_rythme.py

import sys
from datetime import datetime, timedelta, timezone

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


def il_y_a(jours):
    return (datetime.now(timezone.utc).date() - timedelta(days=jours)).isoformat()


def fiches_90j(terminees):
    # Fiches du parcours 90 jours, dans l'ordre, les `terminees` premieres faites.
    return [
        {"id": f"f{k}", "master_id": master_id, "etat": "Terminé" if k < terminees else "Pas commencé"}
        for k, master_id in enumerate(ns._FICHE_JOUR)
    ]


FICHE8 = next(iter(ns._FICHES_DEBLOCAGE_COACH))
position_fiche8 = list(ns._FICHE_JOUR).index(FICHE8)

print("Sans date de demarrage")
check("pas de rythme", ns._rythme_parcours(fiches_90j(0), None) is None)

print("Parcours 90 jours")
rythme = ns._rythme_parcours(fiches_90j(len(ns._FICHE_JOUR)), il_y_a(42))
check("jour du parcours", rythme["jour"] == 42)
check("duree 90 jours", rythme["duree"] == 90)
check("5 etapes, Prospecter a J31", [e["libelle"] for e in rythme["etapes"]] == ["Démarrage", "Clarifier", "Prospecter", "Convertir", "Stabiliser"] and rythme["etapes"][2]["debut"] == 31)
check("tout termine : aucun retard", rythme["en_retard"] == 0)

# A J42, une fiche est en retard si elle s'est ouverte au plus tard a J35.
attendues = [
    m for m, j in ns._FICHE_JOUR.items()
    if j <= 35 and m not in ns._FICHES_PERMANENTES and m not in ns._FICHES_DEBLOCAGE_COACH
]
fiches = fiches_90j(0)
for fiche in fiches:
    if fiche["master_id"] == FICHE8:
        fiche["etat"] = "Terminé"
rythme = ns._rythme_parcours(fiches, il_y_a(42))
check("rien de fait sauf la fiche 8 : toutes les fiches ouvertes depuis 7 jours sont en retard", rythme["en_retard"] == len(attendues))

rythme = ns._rythme_parcours(fiches_90j(0), il_y_a(42))
check("fiche 8 pas validee par le coach : seules les fiches d'avant comptent", rythme["en_retard"] == position_fiche8)

rythme = ns._rythme_parcours(fiches_90j(0), il_y_a(42), verrou_coach=False)
check("autonome, sans verrou coach : la fiche 8 et la suite comptent", rythme["en_retard"] == len(attendues) + 1)

rythme = ns._rythme_parcours(fiches_90j(0), il_y_a(5))
check("J5 : les fiches de J0 et J1 ne sont pas encore en retard", rythme["en_retard"] == 0)

rythme = ns._rythme_parcours(fiches_90j(0), il_y_a(8))
check("J8 : les fiches de J0 et J1 sont en retard", rythme["en_retard"] == position_fiche8)

permanentes = [{"id": "p", "master_id": m, "etat": "En cours"} for m in ns._FICHES_PERMANENTES if m in ns._FICHE_JOUR]
rythme = ns._rythme_parcours(permanentes, il_y_a(80), verrou_coach=False)
check("fiches de suivi jamais en retard", rythme["en_retard"] == 0)

print("Atelier")
atelier = [{"id": f"a{k}", "master_id": m, "etat": "Terminé"} for k, m in enumerate(ns._ATELIER_JOUR)]
rythme = ns._rythme_parcours(atelier, il_y_a(10), atelier=True)
check("duree 28 jours et 4 sessions", rythme["duree"] == 28 and [e["libelle"] for e in rythme["etapes"]] == ["Session 1", "Session 2", "Session 3", "Session 4"])
check("atelier termine : aucun retard", rythme["en_retard"] == 0)
check("jour negatif avant la session 1", ns._rythme_parcours(atelier, il_y_a(-3), atelier=True)["jour"] == -3)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
