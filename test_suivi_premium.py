# Tests du 29/10/2026 : preparation des points, alertes d'intervention et
# « Question pour Rony ». Entierement mockes : ni Notion, ni reseau.
# Lancer : python test_suivi_premium.py

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"

import portal_main
from backend.services import eleves_service, notion_service, push_service
from backend.services import questions_rony_service as qrs
from backend.services import suivi_coach_service as scs

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


def texte(valeur):
    return {"type": "rich_text", "rich_text": [{"plain_text": valeur}] if valeur else []}


maintenant = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def iso(jours_avant, heures=0):
    return (maintenant - timedelta(days=jours_avant, hours=heures)).isoformat().replace("+00:00", "Z")


def entree(nom, cree, donnees=None, fiche=None, client="marie"):
    props = {
        "Nom": {"type": "title", "title": [{"plain_text": nom}]},
        "Données (JSON)": texte(json.dumps(donnees or {})),
        "Client": {"type": "relation", "relation": [{"id": client}]},
    }
    if fiche:
        props["Fiche Client"] = {"type": "relation", "relation": [{"id": fiche}]}
    return {"id": f"id-{nom}-{cree}", "created_time": cree, "last_edited_time": cree, "properties": props}


def dashboard(**autres):
    base = {
        "nom": "Marie Test", "parcours": "Coaching 90 jours", "date_demarrage": "2026-09-20",
        "fiches": [
            {"id": "f10", "nom": "10 - Ma phrase de positionnement", "etat": "Terminé", "acces": "Ouvert"},
            {"id": "f11", "nom": "11 - Mon tableau de prospection", "etat": "En cours", "acces": "Ouvert"},
        ],
        "rythme": {"en_retard": 0}, "regularite": {"derniere": "2026-10-26", "serie": 3},
        "identite": {"telephone": "+590 690 12 34 56"},
    }
    base.update(autres)
    return base


def semaine(jour, contacts, rdv=1, ventes=0):
    return {"semaine_du": jour, "contacts": contacts, "rdv": rdv, "propositions": 0, "ventes": ventes}


print("\n1. Alertes : eleve actif, rien a signaler")
entrees = [entree("Marie — fiche", iso(1), fiche="f11")]
alertes = scs._detecter(dashboard(), entrees, [semaine("2026-10-26", 10)], None, [], maintenant)
check("aucune alerte", alertes == [])

print("\n2. Alertes : decrochage")
entrees = [entree("Marie — fiche", iso(9), fiche="f11"), entree("Marie — Compte rendu de point du 28/10/2026", iso(1))]
alertes = scs._detecter(dashboard(), entrees, [], None, [], maintenant)
inactif = next((a for a in alertes if a["type"] == "inactif"), None)
check("rien saisi depuis 9 jours (le compte rendu de Rony ne compte pas)", inactif and "9 jours" in inactif["titre"])
check("message pret, au prenom, sans tiret long", inactif["message"].startswith("Salut Marie") and "—" not in inactif["message"])

print("\n3. Alertes : chiffres en baisse")
historique = [semaine("2026-10-05", 12), semaine("2026-10-12", 10), semaine("2026-10-19", 14), semaine("2026-10-26", 3)]
alertes = scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], historique, None, [], maintenant)
baisse = next((a for a in alertes if a["type"] == "baisse"), None)
check("contacts divises par plus de 2 : alerte", baisse is not None and "3 contacts" in baisse["detail"])
historique = [semaine("2026-10-12", 10), semaine("2026-10-19", 10), semaine("2026-10-26", 8)]
alertes = scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], historique, None, [], maintenant)
check("legere baisse : pas d'alerte", not any(a["type"] == "baisse" for a in alertes))

print("\n4. Alertes : engagements pas tenus")
cr = {"date_point": "2026-10-20", "engagements": [
    {"id": "a", "texte": "Appeler 5 prospects", "fait": False},
    {"id": "b", "texte": "Relancer 2 devis", "fait": False},
    {"id": "c", "texte": "Bilan dimanche", "fait": True},
]}
alertes = scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], [], cr, [], maintenant)
eng = next((a for a in alertes if a["type"] == "engagements"), None)
check("2 sur 3 pas tenus apres 9 jours : alerte", eng is not None and eng["titre"].startswith("2 engagements sur 3"))
check("le message cite le premier engagement restant", "Appeler 5 prospects" in eng["message"])
cr_recent = {**cr, "date_point": "2026-10-27"}
alertes = scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], [], cr_recent, [], maintenant)
check("point d'il y a 2 jours : on laisse le temps", not any(a["type"] == "engagements" for a in alertes))

print("\n5. Alertes : bilan oublie, fiches en retard, question sans reponse")
alertes = scs._detecter(dashboard(regularite={"derniere": "2026-10-12"}, rythme={"en_retard": 3}), [entree("x", iso(1), fiche="f11")], [], None, [], maintenant)
types = {a["type"] for a in alertes}
check("bilan de plus de 9 jours : alerte", "bilan" in types)
check("3 fiches en retard : alerte avec la prochaine fiche", "retard" in types and "Mon tableau de prospection" in next(a for a in alertes if a["type"] == "retard")["message"])
questions = [{"id": "q", "question": "Remise de 20 % ?", "posee_le": iso(2), "reponse": None, "repondu_le": None}]
alertes = scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], [], None, questions, maintenant)
check("question sans reponse depuis 2 jours : alerte sans message eleve", alertes and alertes[0]["type"] == "question" and alertes[0]["message"] is None)
questions = [{"id": "q", "question": "Remise ?", "posee_le": iso(0, 3), "reponse": None, "repondu_le": None}]
check("question d'il y a 3 h : pas encore d'alerte", not scs._detecter(dashboard(), [entree("x", iso(1), fiche="f11")], [], None, questions, maintenant))

print("\n6. Lien WhatsApp")
check("numero international : lien direct", scs._lien_whatsapp("+590 690 12 34 56", "Salut").startswith("https://wa.me/590690123456?text=Salut"))
check("00 : converti", scs._lien_whatsapp("00590690123456", "x").startswith("https://wa.me/590690123456"))
check("numero local : on ne devine pas l'indicatif", scs._lien_whatsapp("0690123456", "x").startswith("https://wa.me/?text="))
check("pas de numero : choix du contact", scs._lien_whatsapp(None, "x").startswith("https://wa.me/?text="))

print("\n7. Liste des eleves a surveiller et resume du matin")
clients = [
    {"id": "marie", "properties": {"État": {"type": "select", "select": {"name": "En cours"}}, "Parcours": {"type": "select", "select": {"name": "Coaching 90 jours"}}}},
    {"id": "paul", "properties": {"État": {"type": "select", "select": {"name": "En cours"}}, "Parcours": {"type": "select", "select": {"name": "eVolution Autonome"}}}},
    {"id": "luc", "properties": {"État": {"type": "select", "select": {"name": "Terminé"}}, "Parcours": {"type": "select", "select": {"name": "Coaching 90 jours"}}}},
]
vus = []


def fausses_alertes(client_page_id, maintenant=None):
    vus.append(client_page_id)
    return {"client_page_id": client_page_id, "nom": "Marie Test", "alertes": [{"type": "inactif", "titre": "Rien saisi depuis 9 jours", "message": "Salut"}]}


notion_service._cache_clear("alertes_coach")
with patch.object(notion_service, "_query_data_source", return_value=clients), patch.object(scs, "alertes_eleve", side_effect=fausses_alertes):
    liste = scs.alertes(frais=True)
check("seuls les eleves en cours hors Autonome", vus == ["marie"] and len(liste) == 1)
titre, corps = scs.resume_du_matin(liste)
check("resume du matin : « 1 élève à surveiller »", titre == "1 élève à surveiller" and "Marie (rien saisi depuis 9 jours)" in corps)
check("rien a signaler : pas de notification", scs.resume_du_matin([]) is None)

with patch.object(push_service, "notifications_du_jour", return_value={"actif": True, "envoyees": 0}), \
     patch.object(scs, "alertes", return_value=liste), \
     patch.object(push_service, "envoyer_coach", return_value=1) as envoi:
    os.environ["COACH_DIAGNOSTIC_API_KEY"] = "cle-n8n"
    code, r = statut(portal_main.automation_notifications_du_jour, authorization="Bearer cle-n8n")
check("passage du matin : Rony est prevenu", code == 200 and r["coach"]["eleves_a_surveiller"] and envoi.called)

print("\n8. Preparation d'un point")
entrees = [
    entree("Marie — fiche", "2026-10-27T10:00:00.000Z", fiche="f11"),
    entree("Marie — fiche", "2026-10-10T10:00:00.000Z", fiche="f10"),
    entree("Marie — Question à Idris — 2026-10-26", "2026-10-26T10:00:00.000Z", {"question": "Comment relancer un devis ?"}),
    entree("Marie — Question pour Rony — 2026-10-28", "2026-10-28T10:00:00.000Z", {"question": "Remise de 20 % ?", "posee_le": "2026-10-28T10:00:00+00:00"}),
]
with patch.object(notion_service, "get_client_dashboard", return_value=dashboard()), \
     patch.object(scs, "_entrees", return_value=entrees), \
     patch.object(scs.comptes_rendus_service, "dernier", return_value={"date_point": "2026-10-20", "engagements": [{"id": "a", "texte": "Appeler 5 prospects", "fait": True}]}), \
     patch.object(scs, "_historique", return_value=[semaine("2026-10-12", 8), semaine("2026-10-26", 10)]), \
     patch.object(scs.prospects_service, "lire", return_value={}), \
     patch.object(scs.prospects_service, "vue_client", return_value={"par_statut": {"Contacté": 4}, "a_relancer": [{}]}):
    prep = scs.preparation("marie", maintenant=maintenant)
check("periode : depuis le dernier point", prep["depuis"] == "2026-10-20" and prep["depuis_dernier_point"])
check("fiches travaillees depuis le point seulement", [f["fiche"] for f in prep["fiches_travaillees"]] == ["Mon tableau de prospection"])
check("questions a Idris et a Rony", prep["questions_idris"][0]["question"] == "Comment relancer un devis ?" and prep["questions_rony"][0]["question"] == "Remise de 20 % ?")
check("bilans de la periode", [b["semaine_du"] for b in prep["bilans"]] == ["2026-10-26"])
check("engagements et carnet", prep["engagements"][0]["fait"] and prep["carnet"]["a_relancer"] == 1)
texte_ia = scs._texte_preparation(prep)
check("texte pour Idris : objectif absent signale", "Objectif 90 jours : non écrit" in texte_ia and "Comment relancer un devis ?" in texte_ia)

with patch.object(scs.ia_service, "generer", return_value='{"synthese": "Marie avance — bien.", "questions": ["Q1", "Q2", "Q3", "Q4"], "vigilance": ""}'):
    idris = scs.preparation_idris(prep)
check("Idris : synthese humanisee + 3 questions max", idris["synthese"] == "Marie avance, bien." and idris["questions"] == ["Q1", "Q2", "Q3"])
with patch.object(scs.ia_service, "generer", return_value="rien"):
    try:
        scs.preparation_idris(prep)
        check("reponse illisible : erreur propre", False)
    except RuntimeError:
        check("reponse illisible : erreur propre", True)

print("\n9. Question pour Rony")
cree = {}
qrs_cache = notion_service._cache_clear
notion_service._cache_clear("questions_rony")
with patch.object(notion_service, "_query_data_source", return_value=[]), \
     patch.object(notion_service, "_create_page", side_effect=lambda src, p: cree.update(p) or {"id": "q1"}):
    q = qrs.poser("marie", dashboard(), "  Un prospect me demande 20 % de remise, je fais quoi ?  ")
check("question enregistree, nettoyee", q["id"] == "q1" and q["question"].startswith("Un prospect") and not q["question"].endswith(" "))
check("titre « Question pour Rony »", "Question pour Rony" in cree["Nom"]["title"][0]["text"]["content"])

for parcours in ("eVolution Autonome", "Atelier collectif"):
    try:
        qrs.poser("marie", dashboard(parcours=parcours), "Une vraie question ?")
        check(f"{parcours} : refuse", False)
    except qrs.QuestionNonAutorisee:
        check(f"{parcours} : refuse", True)

attente = [entree(f"Marie — Question pour Rony — {i}", iso(i), {"question": f"Q{i}"}) for i in range(3)]
notion_service._cache_clear("questions_rony")
with patch.object(notion_service, "_query_data_source", return_value=attente), patch.object(notion_service, "_create_page") as creation:
    try:
        qrs.poser("marie", dashboard(), "Encore une question ?")
        check("3 questions en attente : on attend la reponse de Rony", False)
    except qrs.TropDeQuestions:
        check("3 questions en attente : on attend la reponse de Rony", not creation.called)

try:
    qrs.poser("marie", dashboard(), "abc")
    check("question trop courte refusee", False)
except qrs.QuestionInvalide:
    check("question trop courte refusee", True)

notion_service._cache_clear("questions_rony")
with patch.object(notion_service, "_query_data_source", return_value=[attente[0]]), patch.object(notion_service, "_update_page") as maj:
    r = qrs.repondre("marie", attente[0]["id"], "Ne baisse pas ton prix, ajoute un bonus.")
    enregistre = json.loads(maj.call_args[0][1]["Données (JSON)"]["rich_text"][0]["text"]["content"])
check("reponse de Rony enregistree et datee", r["reponse"].startswith("Ne baisse") and enregistre["repondu_le"])
notion_service._cache_clear("questions_rony")
with patch.object(notion_service, "_query_data_source", return_value=[]):
    try:
        qrs.repondre("marie", "inconnue", "x")
        check("question d'un autre eleve : refusee", False)
    except qrs.QuestionNonAutorisee:
        check("question d'un autre eleve : refusee", True)

print("\n10. Endpoints et notifications")
with patch.object(portal_main, "_session_from_header", return_value={"client_page_id": "marie"}), \
     patch.object(notion_service, "get_client_dashboard", return_value=dashboard()):
    taches = BackgroundTasks()
    with patch.object(qrs, "poser", return_value={"id": "q1", "question": "Remise ?"}):
        code, _ = statut(portal_main.portal_poser_question_rony, portal_main.QuestionRonyRequest(question="Remise ?"), taches, authorization="Bearer t")
    check("POST /portal/questions-rony : 200 + Rony prevenu", code == 200 and len(taches.tasks) == 1)
    with patch.object(qrs, "poser", side_effect=qrs.TropDeQuestions("x")):
        code, detail = statut(portal_main.portal_poser_question_rony, portal_main.QuestionRonyRequest(question="Remise ?"), BackgroundTasks(), authorization="Bearer t")
    check("trop de questions : 422 avec phrase claire", code == 422 and "Rony" in detail)

with patch.object(push_service, "enabled", return_value=True), patch.object(push_service, "envoyer_coach") as envoi:
    portal_main._prevenir_question("marie", "Marie Test", "Q" * 200)
check("notification coach : prenom + extrait court + ouvre la fiche de l'eleve", envoi.call_args[0][0] == "Question de Marie" and len(envoi.call_args[0][1]) <= 110 and envoi.call_args[0][2].endswith("eleve=marie"))

taches = BackgroundTasks()
with patch.object(qrs, "repondre", return_value={"id": "q1", "reponse": "ok"}):
    code, _ = statut(portal_main.coach_repondre_question, "marie", "q1", portal_main.ReponseRonyRequest(reponse="ok"), taches, x_coach_key=CLE)
check("POST reponse : 200 + eleve prevenu", code == 200 and len(taches.tasks) == 1)
code, _ = statut(portal_main.coach_repondre_question, "marie", "q1", portal_main.ReponseRonyRequest(reponse="ok"), BackgroundTasks(), x_coach_key="mauvaise")
check("mauvaise cle coach : refuse", code in (401, 403))

print("\n11. Activite de l'eleve : la reponse de Rony ne compte pas")
question = entree("Marie — Question pour Rony — x", iso(10), {"question": "Q"})
question["last_edited_time"] = iso(0)
check("question : comptee a la date ou l'eleve l'a posee", eleves_service._quand_saisi(question) == iso(10))

print(f"\nRESULTAT : {passed}/{passed + failed} assertions reussies")
sys.exit(1 if failed else 0)
