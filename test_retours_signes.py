# Tests du 29/10/2026 : « Idris prepare, Rony signe ». Retours d'Idris signes
# par Rony (publier, corriger, bloquer, mot du coach), annonce de la fiche 8
# validee, compte rendu apres chaque point. Entierement mockes : ni Notion, ni reseau.
# Lancer : python test_retours_signes.py

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import BackgroundTasks, HTTPException

os.environ["COACH_ONBOARD_KEY"] = "cle-coach-test"

import portal_main
from backend.services import comptes_rendus_service as crs
from backend.services import eleves_service, notion_service, push_service

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


def date_prop(valeur):
    return {"type": "date", "date": {"start": valeur} if valeur else None}


def props(statut_, retour="Bravo pour ta fiche", date_retour=None, mot="", valide_le=None, client="marie", fiche="fiche-1"):
    return {
        "Retour IA statut": {"type": "select", "select": {"name": statut_} if statut_ else None},
        "Retour IA": texte(retour),
        "Retour IA date": date_prop(date_retour),
        "Mot du coach": texte(mot),
        "Retour validé le": date_prop(valide_le),
        "Fiche Client": {"type": "relation", "relation": [{"id": fiche}]},
        "Client": {"type": "relation", "relation": [{"id": client}]},
    }


def client_page(parcours="Coaching 90 jours"):
    return {"id": "marie", "properties": {
        "Parcours": {"type": "select", "select": {"name": parcours}},
        "Nom": {"type": "title", "title": [{"plain_text": "Marie Test"}]},
    }}


maintenant = datetime.now(timezone.utc)
recent = maintenant.isoformat()
vieux = (maintenant - timedelta(days=2)).isoformat()

print("\n1. Ce que l'eleve voit")
v = notion_service._retour_ia_visible(props("À relire", date_retour=recent))
check("retour en relecture : l'eleve attend, sans le texte", v == {"statut": "relecture"})
v = notion_service._retour_ia_visible(props("Publié", date_retour=vieux, mot="Super travail", valide_le=recent))
check("retour signe : texte + mot + « Validé par Rony »", v["texte"] == "Bravo pour ta fiche" and v["mot_coach"] == "Super travail" and v["valide_par_coach"])
check("retour signe : date = date de validation", v["date"] == recent)
v = notion_service._retour_ia_visible(props("À relire", date_retour=vieux))
check("relecture depassee (12 h) : publie, pas signe", v["statut"] == "publie" and not v["valide_par_coach"] and v["mot_coach"] is None)
check("retour bloque sans mot : rien", notion_service._retour_ia_visible(props("Bloqué", date_retour=vieux)) is None)
v = notion_service._retour_ia_visible(props("Bloqué", date_retour=vieux, mot="On en parle au point", valide_le=recent))
check("retour bloque avec mot : seul le mot de Rony", v["texte"] is None and v["mot_coach"] == "On en parle au point")

print("\n2. Ce que Rony voit")
c = notion_service._retour_ia_coach(props("À relire", date_retour=recent))
check("relecture : Rony lit le texte complet", c["statut"] == "a_relire" and c["texte"] == "Bravo pour ta fiche" and not c["visible_eleve"])
c = notion_service._retour_ia_coach(props("À relire", date_retour=vieux))
check("relecture depassee : signale comme deja visible", c["statut"] == "a_relire" and c["visible_eleve"])
c = notion_service._retour_ia_coach(props("Bloqué", date_retour=vieux))
check("bloque : statut bloque", c["statut"] == "bloque" and not c["visible_eleve"])
check("a generer : en cours", notion_service._retour_ia_coach(props("À générer"))["statut"] == "en_cours")

print("\n3. Signature par Rony")
entree = {"id": "e1", "properties": props("À relire", date_retour=recent)}


def pages(parcours="Coaching 90 jours"):
    return lambda page_id: client_page(parcours) if page_id == "marie" else entree


with patch.object(notion_service, "_get_page", side_effect=pages()), \
     patch.object(notion_service, "_update_page", return_value={}) as maj:
    r = notion_service.signer_retour("e1", "marie", "publier", texte="Bravo — continue", mot="Je suis fier de toi")
    envoye = maj.call_args[0][1]
    check("publier : statut Publié", envoye["Retour IA statut"]["select"]["name"] == "Publié")
    check("publier : mot du coach ecrit", envoye["Mot du coach"]["rich_text"][0]["text"]["content"] == "Je suis fier de toi")
    check("publier : date de validation posee", envoye["Retour validé le"]["date"]["start"])
    check("correction : texte humanise (sans tiret long)", envoye["Retour IA"]["rich_text"][0]["text"]["content"] == "Bravo, continue")
    check("renvoie la fiche concernee", r["fiche_id"] == "fiche-1")

    maj.reset_mock()
    notion_service.signer_retour("e1", "marie", "publier", texte="Bravo pour ta fiche")
    check("publier sans correction : texte d'Idris intact", "Retour IA" not in maj.call_args[0][1])

    maj.reset_mock()
    notion_service.signer_retour("e1", "marie", "bloquer")
    envoye = maj.call_args[0][1]
    check("bloquer sans mot : Bloqué, pas de date de validation", envoye["Retour IA statut"]["select"]["name"] == "Bloqué" and envoye["Retour validé le"] == {"date": None})

    try:
        notion_service.signer_retour("e1", "autre-eleve", "publier")
        check("entree d'un autre eleve refusee", False)
    except notion_service.RetourNonAutorise:
        check("entree d'un autre eleve refusee", True)

    try:
        notion_service.signer_retour("e1", "marie", "effacer")
        check("action inconnue refusee", False)
    except ValueError:
        check("action inconnue refusee", True)

with patch.object(notion_service, "_get_page", side_effect=pages("eVolution Autonome")), \
     patch.object(notion_service, "_update_page") as maj:
    try:
        notion_service.signer_retour("e1", "marie", "publier")
        check("Autonome : Rony ne signe pas (Idris publie seul)", False)
    except notion_service.RetourNonAutorise:
        check("Autonome : Rony ne signe pas (Idris publie seul)", not maj.called)

print("\n4. Endpoint et notification")
taches = BackgroundTasks()
with patch.object(notion_service, "signer_retour", return_value={"fiche_id": "fiche-1", "retour_ia": {"visible_eleve": True}}):
    code, _ = statut(portal_main.coach_signer_retour, "e1", portal_main.SignatureRetourRequest(client_page_id="marie", action="publier", mot="Bravo"), taches, x_coach_key=CLE)
check("POST /coach/entrees/{id}/signature : 200", code == 200)
check("une notification est programmee pour l'eleve", len(taches.tasks) == 1)
code, _ = statut(portal_main.coach_signer_retour, "e1", portal_main.SignatureRetourRequest(client_page_id="marie", action="publier"), BackgroundTasks(), x_coach_key="mauvaise")
check("mauvaise cle coach : refuse", code in (401, 403))
with patch.object(notion_service, "signer_retour", side_effect=notion_service.RetourNonAutorise("x")):
    code, _ = statut(portal_main.coach_signer_retour, "e1", portal_main.SignatureRetourRequest(client_page_id="marie", action="publier"), BackgroundTasks(), x_coach_key=CLE)
check("Autonome ou autre eleve : 403", code == 403)

with patch.object(push_service, "enabled", return_value=True), patch.object(push_service, "envoyer") as envoi:
    portal_main._prevenir_signature("marie", "fiche-1", True)
    check("notification : ouvre la fiche signee", envoi.call_args[0][3] == "/?ouvrir=fiche:fiche-1")

print("\n5. Badge « nouveau » : un retour signe apres coup redevient nouveau")
notion_service._cache_clear("retours_idris")
with patch.object(notion_service, "_query_data_source", return_value=[
    {"id": "e1", "properties": props("Publié", date_retour=vieux, mot="Bravo", valide_le=recent)},
    {"id": "e2", "properties": props("Publié", date_retour=vieux, fiche="fiche-2")},
    {"id": "e3", "properties": props("Bloqué", date_retour=vieux)},
]):
    ids = [r["id"] for r in notion_service.retours_idris_publies("marie")]
check("cle de vue = entree + date de validation", ids[0] == f"e1:{recent}")
check("retour non signe : cle = entree", ids[1] == "e2")
check("retour bloque sans mot : absent", len(ids) == 2)

print("\n6. Fiche 8 validee : l'eleve est prevenu")
with patch.object(push_service, "enabled", return_value=True), \
     patch.object(notion_service, "client_de_fiche", return_value=("marie", notion_service._DIAGNOSTIC_FICHE8_MASTER_ID)), \
     patch.object(push_service, "envoyer") as envoi:
    portal_main._prevenir_fiche_validee("fiche-8")
    check("notification « Ton diagnostic est validé »", envoi.called and envoi.call_args[0][1] == "Ton diagnostic est validé")
with patch.object(push_service, "enabled", return_value=True), \
     patch.object(notion_service, "client_de_fiche", return_value=("marie", "autre-master")), \
     patch.object(push_service, "envoyer") as envoi:
    portal_main._prevenir_fiche_validee("fiche-3")
    check("autre fiche : pas de notification", not envoi.called)
with patch.object(push_service, "enabled", return_value=True), \
     patch.object(notion_service, "client_de_fiche", side_effect=RuntimeError("Notion")):
    portal_main._prevenir_fiche_validee("fiche-8")
    check("panne Notion : aucune exception ne sort", True)
taches = BackgroundTasks()
with patch.object(notion_service, "validate_fiche"):
    code, _ = statut(portal_main.coach_valider_fiche, "fiche-8", taches, x_coach_key=CLE)
check("validation coach : notification programmee", code == 200 and len(taches.tasks) == 1)

print("\n7. Compte rendu apres un point")
cree = {}


def creer_page(source, proprietes):
    cree["props"] = proprietes
    return {"id": "cr-1", "created_time": recent}


with patch.object(notion_service, "_get_page", return_value=client_page()), \
     patch.object(notion_service, "_create_page", side_effect=creer_page):
    cr = crs.creer("marie", "On a revu ton pitch.", ["Appeler 5 prospects d'ici mercredi", "  ", "Relancer Jean"], "2026-10-28")
contenu = json.loads(cree["props"]["Données (JSON)"]["rich_text"][0]["text"]["content"])
check("titre « Compte rendu de point du 28/10/2026 »", "Compte rendu de point du 28/10/2026" in cree["props"]["Nom"]["title"][0]["text"]["content"])
check("engagements vides ignores", len(contenu["engagements"]) == 2 and not contenu["engagements"][0]["fait"])
check("relie a l'eleve", cree["props"]["Client"]["relation"][0]["id"] == "marie")
check("renvoie le compte rendu", cr["id"] == "cr-1" and cr["resume"] == "On a revu ton pitch.")

with patch.object(notion_service, "_get_page", return_value=client_page("eVolution Autonome")), \
     patch.object(notion_service, "_create_page") as creation:
    try:
        crs.creer("marie", "x", [])
        check("Autonome : pas de compte rendu", False)
    except crs.CompteRenduNonAutorise:
        check("Autonome : pas de compte rendu", not creation.called)

try:
    crs.creer("marie", "  ", ["", " "])
    check("compte rendu vide refuse", False)
except crs.CompteRenduInvalide:
    check("compte rendu vide refuse", True)


def page_cr(id_, jour, engagements, client="marie"):
    return {"id": id_, "created_time": f"{jour}T12:00:00.000Z", "properties": {
        "Nom": {"type": "title", "title": [{"plain_text": f"Marie — Compte rendu de point du {jour}"}]},
        "Date": date_prop(jour),
        "Données (JSON)": texte(json.dumps({"date_point": jour, "resume": "Résumé", "engagements": engagements})),
        "Client": {"type": "relation", "relation": [{"id": client}]},
    }}


aujourd_hui = date.today().isoformat()
avant = (date.today() - timedelta(days=12)).isoformat()
notion_service._cache_clear("comptes_rendus")
with patch.object(notion_service, "_query_data_source", return_value=[
    page_cr("cr-ancien", avant, [{"id": "a", "texte": "Vieux", "fait": True}]),
    page_cr("cr-recent", aujourd_hui, [{"id": "b", "texte": "Appeler 5 prospects", "fait": False}]),
]):
    dernier = crs.dernier("marie")
    check("dernier compte rendu = le plus recent", dernier["id"] == "cr-recent")
    lignes = crs.lignes_pour_bilan("marie")
    check("bilan hebdo : Idris reprend les engagements", any("Appeler 5 prospects (pas encore coché)" in l for l in lignes))

    with patch.object(notion_service, "_update_page") as maj:
        cr = crs.cocher("marie", "cr-recent", "b", True)
        enregistre = json.loads(maj.call_args[0][1]["Données (JSON)"]["rich_text"][0]["text"]["content"])
        check("l'eleve coche son engagement", cr["engagements"][0]["fait"] and enregistre["engagements"][0]["fait"])

    try:
        crs.cocher("marie", "cr-recent", "inconnu", True)
        check("engagement inconnu refuse", False)
    except crs.CompteRenduNonAutorise:
        check("engagement inconnu refuse", True)

notion_service._cache_clear("comptes_rendus")
loin = (date.today() - timedelta(days=40)).isoformat()
with patch.object(notion_service, "_query_data_source", return_value=[page_cr("cr-loin", loin, [{"id": "c", "texte": "Ancien", "fait": False}])]):
    check("point de plus de 3 semaines : pas repris dans le bilan", crs.lignes_pour_bilan("marie") == [])
notion_service._cache_clear("comptes_rendus")

taches = BackgroundTasks()
with patch.object(crs, "creer", return_value={"id": "cr-1", "engagements": [{"id": "a"}]}):
    code, _ = statut(portal_main.coach_creer_compte_rendu, "marie", portal_main.CompteRenduRequest(resume="ok"), taches, x_coach_key=CLE)
check("POST /coach/eleves/{id}/comptes-rendus : 200 + notification", code == 200 and len(taches.tasks) == 1)
with patch.object(crs, "creer", side_effect=crs.CompteRenduNonAutorise("x")):
    code, _ = statut(portal_main.coach_creer_compte_rendu, "marie", portal_main.CompteRenduRequest(resume="ok"), BackgroundTasks(), x_coach_key=CLE)
check("Autonome : 403", code == 403)

with patch.object(crs.ia_service, "generer", return_value='Voici : {"resume": "On a vu ton pitch.", "engagements": ["Appeler 5 prospects", ""]}'):
    forme = crs.mettre_en_forme("pitch ok, appeler 5 prospects", "Marie")
check("mise en forme par Idris : resume + engagements", forme == {"resume": "On a vu ton pitch.", "engagements": ["Appeler 5 prospects"]})
with patch.object(crs.ia_service, "generer", return_value="pas de json"):
    try:
        crs.mettre_en_forme("notes")
        check("reponse illisible : erreur propre", False)
    except RuntimeError:
        check("reponse illisible : erreur propre", True)

print("\n8. Ce que Rony ecrit n'est pas une activite de l'eleve")
entrees = [
    {**page_cr("cr-recent", aujourd_hui, []), "last_edited_time": recent},
    {"id": "e1", "last_edited_time": recent, "properties": props("Publié", valide_le=recent, client="jean")},
    {"id": "e2", "last_edited_time": vieux, "properties": props("Publié", client="paul")},
]
with patch.object(notion_service, "_query_data_source", return_value=entrees):
    activite = eleves_service.activite()
check("compte rendu et signature de Rony ignores", "marie" not in activite and "jean" not in activite)
check("vraie saisie de l'eleve gardee", "paul" in activite)

print(f"\nRESULTAT : {passed}/{passed + failed} assertions reussies")
sys.exit(1 if failed else 0)
