# Tests d'Idris au quotidien (lot 2) : questions libres avec quota, messages
# prets a envoyer, preparation de RDV reservee au Coaching.
#
# Entierement mockes (ni Notion ni Gemini), meme style que test_kpi_saisie.py.
#
# Lancer : python test_idris.py

import json
import sys
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import idris_service as idris
from backend.services import ia_service, notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-idris"

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


CLIENT = "dddddddd-dddd-dddd-dddd-dddddddddddd"
BEARER = "Bearer " + portal_auth_service.create_session_token("client@test.com", CLIENT)
AUTONOME = {"nom": "Marie Test", "parcours": "Autonome", "fiches": [], "objectif_90j": "10 clients", "date_demarrage": "2026-10-01"}
COACHING = {**AUTONOME, "parcours": None}


def appeler(route, requete, dashboard, deja_posees=0, reponse_ia="Réponse d'Idris."):
    idris._compteurs.clear()
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
         patch.object(ns, "get_client_dashboard", return_value=dashboard), \
         patch.object(ns, "_query_data_source", return_value=[{}] * deja_posees) as requete_notion, \
         patch.object(ns, "_get_page", return_value={"properties": {}}), \
         patch.object(ns, "reponses_des_fiches", return_value=[{"nom": "Marie - 10. MA PHRASE", "reponses": [("Ma phrase", "J'aide les artisans")]}]), \
         patch.object(ns, "_create_page") as creation, \
         patch.object(ia_service, "generer", return_value=reponse_ia) as generer:
        code, resultat = statut(route, requete, authorization=BEARER)
    return code, resultat, generer, creation, requete_notion


def question(texte, historique=()):
    return portal_main.IdrisQuestionRequest(messages=[*historique, {"role": "client", "texte": texte}])


print("Etat")
with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
     patch.object(ns, "get_client_dashboard", return_value=AUTONOME), \
     patch.object(ns, "_query_data_source", return_value=[{}] * 3):
    code, etat = statut(portal_main.portal_idris_etat, authorization=BEARER)
check("Autonome : quota de 20 par mois", code == 200 and etat["questions_par_mois"] == 20 and etat["questions_restantes"] == 17)
check("Autonome : pas de preparation de RDV", etat["rdv_disponible"] is False)
check("5 types de messages", len(etat["types_messages"]) == 5)
with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
     patch.object(ns, "get_client_dashboard", return_value=COACHING):
    code, etat = statut(portal_main.portal_idris_etat, authorization=BEARER)
check("Coaching : illimite et RDV disponibles", etat["questions_restantes"] is None and etat["rdv_disponible"] is True)
with patch.dict("os.environ", {"GEMINI_API_KEY": ""}), patch.object(ns, "get_client_dashboard", return_value=COACHING):
    code, etat = statut(portal_main.portal_idris_etat, authorization=BEARER)
check("sans cle Gemini : indisponible", etat["disponible"] is False)

print("Question a Idris")
code, resultat, generer, creation, requete_notion = appeler(portal_main.portal_idris_question, question("Comment fixer mon prix ?"), AUTONOME, deja_posees=5)
check("repond 200 avec le texte", code == 200 and resultat["texte"] == "Réponse d'Idris.")
check("decompte les questions restantes", resultat["questions_restantes"] == 14)
systeme, echanges = generer.call_args[0][0], generer.call_args[0][1]
check("prompt cadre sur la methode et les limites", "Juridique, fiscalité" in systeme and "LA MÉTHODE eVolution 2.0" in systeme)
check("contexte du client transmis", "J'aide les artisans" in echanges[0]["texte"] and "eVolution Autonome" in echanges[0]["texte"])
check("la question est le dernier tour", echanges[-1] == {"role": "user", "texte": "Comment fixer mon prix ?"})
proprietes = creation.call_args[0][1] if creation.called else {}
check("question gardee dans Notion", "Question à Idris" in proprietes.get("Nom", {}).get("title", [{}])[0].get("text", {}).get("content", ""))
contenu = "".join(t["text"]["content"] for t in proprietes.get("Données (JSON)", {}).get("rich_text", []))
check("question et reponse enregistrees", json.loads(contenu) == {"question": "Comment fixer mon prix ?", "reponse": "Réponse d'Idris."})
filtre = requete_notion.call_args_list[0][1]["filter_"]["and"]
check("quota compte depuis le 1er du mois", {"property": "Date", "date": {"on_or_after": datetime.now(timezone.utc).strftime("%Y-%m-01")}} in filtre)

print("Historique et alternance des tours")
historique = [{"role": "idris", "texte": "Bonjour"}, {"role": "client", "texte": "Q1"}, {"role": "idris", "texte": "R1"}]
code, _, generer, _, _ = appeler(portal_main.portal_idris_question, question("Q2", historique), COACHING)
roles = [e["role"] for e in generer.call_args[0][1]]
check("tours alternes user / model", all(a != b for a, b in zip(roles, roles[1:])))
check("commence et finit par user", roles[0] == "user" and roles[-1] == "user")

print("Quota")
code, detail, generer, creation, _ = appeler(portal_main.portal_idris_question, question("Encore ?"), AUTONOME, deja_posees=20)
check("Autonome au-dela de 20 -> 429", code == 429 and not generer.called and not creation.called)
code, resultat, _, _, requete_notion = appeler(portal_main.portal_idris_question, question("Encore ?"), COACHING, deja_posees=50)
check("Coaching : pas de quota mensuel", code == 200 and resultat["questions_restantes"] is None and not requete_notion.called)
idris._compteurs.clear()
with patch.object(idris, "_MAX_QUESTIONS_JOUR_COACHING", 1):
    idris._quota_jour_ok(f"q:{CLIENT}", 1)
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
         patch.object(ns, "get_client_dashboard", return_value=COACHING), \
         patch.object(ia_service, "generer") as generer:
        code, _ = statut(portal_main.portal_idris_question, question("Q"), authorization=BEARER)
check("garde-fou du jour -> 429", code == 429 and not generer.called)

print("Questions invalides")
for label, requete in [
    ("sans message", portal_main.IdrisQuestionRequest(messages=[])),
    ("dernier message d'Idris", portal_main.IdrisQuestionRequest(messages=[{"role": "idris", "texte": "x"}])),
    ("question vide", question("   ")),
    ("question trop longue", question("x" * 801)),
]:
    code, _, generer, _, _ = appeler(portal_main.portal_idris_question, requete, COACHING)
    check(f"{label} -> 422", code == 422 and not generer.called)
code, _ = statut(portal_main.portal_idris_question, question("Q"), authorization="")
check("sans session -> 401", code == 401)

print("Messages prets a envoyer")
reponse = json.dumps({"variantes": ["Bonjour [Prénom], version 1", "Bonjour [Prénom], version 2", "trop"]})
code, resultat, generer, _, _ = appeler(portal_main.portal_idris_message, portal_main.IdrisMessageRequest(type="relance_devis", precision="Devis envoyé lundi"), AUTONOME, reponse_ia=reponse)
check("2 variantes", code == 200 and resultat["variantes"] == ["Bonjour [Prénom], version 1", "Bonjour [Prénom], version 2"])
check("consigne et precision transmises", "Devis envoyé lundi" in generer.call_args[0][1][0]["texte"] and "proposition ou un devis" in generer.call_args[0][1][0]["texte"])
code, _, generer, _, _ = appeler(portal_main.portal_idris_message, portal_main.IdrisMessageRequest(type="inconnu"), AUTONOME)
check("type inconnu -> 422", code == 422 and not generer.called)
code, _, _, _, _ = appeler(portal_main.portal_idris_message, portal_main.IdrisMessageRequest(type="relance_devis"), AUTONOME, reponse_ia="pas du json")
check("reponse IA illisible -> 503", code == 503)

print("Preparation de RDV")
reponse = json.dumps({
    "objectif": "Comprendre son besoin",
    "questions": ["Q1 ?", "Q2 ?", "Q3 ?"],
    "objections": [{"objection": "Trop cher", "reponse": "Je comprends..."}, {"objection": "", "reponse": "x"}],
    "prochaine_etape": "Proposer un devis jeudi",
})
requete = portal_main.IdrisRdvRequest(prospect="Plombier à Baie-Mahault, 2 salariés", besoin="Manque de chantiers")
code, resultat, generer, _, _ = appeler(portal_main.portal_idris_rdv, requete, COACHING, reponse_ia=reponse)
check("Coaching : preparation structuree", code == 200 and resultat["questions"] == ["Q1 ?", "Q2 ?", "Q3 ?"] and resultat["prochaine_etape"] == "Proposer un devis jeudi")
check("objections incompletes ecartees", resultat["objections"] == [{"objection": "Trop cher", "reponse": "Je comprends..."}])
check("prospect transmis", "Plombier à Baie-Mahault" in generer.call_args[0][1][0]["texte"])
code, detail, generer, _, _ = appeler(portal_main.portal_idris_rdv, requete, AUTONOME, reponse_ia=reponse)
check("Autonome -> 403 sans appel IA", code == 403 and not generer.called)
code, _, generer, _, _ = appeler(portal_main.portal_idris_rdv, portal_main.IdrisRdvRequest(prospect="  "), COACHING)
check("prospect vide -> 422", code == 422 and not generer.called)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
