# Tests du 28/10/2026 : badges « nouveau » (retours d'Idris lisibles cote
# eleve, activite des eleves cote coach). Entierement mockes : ni Notion, ni reseau.
# Lancer : python test_badges_nouveautes.py

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"

import portal_main
from backend.services import eleves_service, notion_service

passed = 0
failed = 0
CLE = "cle-coach-test"


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


def entree(id_, statut_, texte="Bravo", date=None, fiche="fiche-1", client="marie", edite="2026-10-28T10:00:00.000Z"):
    return {
        "id": id_,
        "last_edited_time": edite,
        "properties": {
            "Retour IA statut": {"type": "select", "select": {"name": statut_} if statut_ else None},
            "Retour IA": {"type": "rich_text", "rich_text": [{"plain_text": texte}] if texte else []},
            "Retour IA date": {"type": "date", "date": {"start": date} if date else None},
            "Fiche Client": {"type": "relation", "relation": [{"id": fiche}]},
            "Client": {"type": "relation", "relation": [{"id": client}]},
        },
    }


print("\n1. Retours d'Idris lisibles par l'eleve")
vieux = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
recent = datetime.now(timezone.utc).isoformat()
notion_service._cache_clear("retours_idris")
with patch.object(notion_service, "_query_data_source", return_value=[
    entree("e1", "Publié", date=vieux),
    entree("e2", "À relire", date=vieux, fiche="fiche-2"),
    entree("e3", "À relire", date=recent),
    entree("e4", "Publié", texte=""),
]) as requete:
    retours = notion_service.retours_idris_publies("marie")
    notion_service.retours_idris_publies("marie")
check("publies et relus seulement (pas en relecture, pas vides)", [r["id"] for r in retours] == ["e1", "e2"])
check("avec la fiche concernee", [r["fiche_id"] for r in retours] == ["fiche-1", "fiche-2"])
check("une seule requete Notion, filtree sur l'eleve", requete.call_count == 1
      and requete.call_args.kwargs["filter_"]["and"][0] == {"property": "Client", "relation": {"contains": "marie"}})

with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "marie"}), \
     patch.object(notion_service, "retours_idris_publies", return_value=retours):
    code, rep = statut(portal_main.portal_nouveautes, authorization="Bearer x")
check("route eleve", code == 200 and rep == {"retours_idris": retours})
with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "marie"}), \
     patch.object(notion_service, "retours_idris_publies", side_effect=RuntimeError("Notion")):
    code, rep = statut(portal_main.portal_nouveautes, authorization="Bearer x")
check("panne Notion -> liste vide, jamais d'erreur", code == 200 and rep == {"retours_idris": []})

print("\n2. Activite des eleves (Espace Coach)")
with patch.object(notion_service, "_query_data_source", return_value=[
    entree("a", None, client="marie", edite="2026-10-28T10:00:00.000Z"),
    entree("b", None, client="marie", edite="2026-10-27T10:00:00.000Z"),
    entree("c", None, client="paul", edite="2026-10-26T08:00:00.000Z"),
]) as requete:
    activite = eleves_service.activite(maintenant=datetime(2026, 10, 28, tzinfo=timezone.utc))
check("derniere saisie par eleve", activite == {"marie": "2026-10-28T10:00:00.000Z", "paul": "2026-10-26T08:00:00.000Z"})
check("une seule requete, sur les 30 derniers jours",
      requete.call_count == 1 and requete.call_args.kwargs["filter_"]["last_edited_time"]["on_or_after"].startswith("2026-09-28"))

with patch.object(eleves_service, "activite", return_value=activite):
    code, rep = statut(portal_main.coach_eleves_activite, x_coach_key=CLE)
check("route coach", code == 200 and rep == {"activite": activite})
code, rep = statut(portal_main.coach_eleves_activite, x_coach_key="faux")
check("mauvaise cle -> 401", code == 401)
with patch.object(eleves_service, "activite", side_effect=RuntimeError("Notion")):
    code, rep = statut(portal_main.coach_eleves_activite, x_coach_key=CLE)
check("panne Notion -> vide, jamais d'erreur", code == 200 and rep == {"activite": {}})

route = next(r for r in portal_main.app.routes if getattr(r, "path", "") == "/coach/eleves/activite")
detail = next(r for r in portal_main.app.routes if getattr(r, "path", "") == "/coach/eleves/{client_page_id}")
check("la route activite passe avant la fiche eleve", portal_main.app.routes.index(route) < portal_main.app.routes.index(detail))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
