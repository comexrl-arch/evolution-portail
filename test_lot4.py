# Tests du lot 4 : bibliotheque de modeles par metier, objectif saisi a
# l'accueil guide, lien de partage, avis J90, recap hebdomadaire, lien du
# groupe de la communaute.
#
# Entierement mockes (ni Notion ni Gemini), meme style que test_idris.py.
#
# Lancer : python test_lot4.py

import json
import sys
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import bibliotheque_service as biblio
from backend.services import fidelite_service as fidelite
from backend.services import ia_service, idris_service, notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-lot4"

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


CLIENT = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
BEARER = "Bearer " + portal_auth_service.create_session_token("client@test.com", CLIENT)
J = lambda jours: (date.today() - timedelta(days=jours)).isoformat()
DASHBOARD = {
    "nom": "Marie Test",
    "parcours": "Autonome",
    "date_demarrage": J(20),
    "identite": {"secteur": "Plomberie", "activite": "Artisan plombier", "email": "client@test.com", "telephone": "0690000000"},
    "fiches": [
        {"id": "f1", "master_id": "m1", "nom": "Marie Test - 9. MON OFFRE ACTUELLE", "etat": "Terminé", "module": "Clarifier · Module 1"},
        {"id": "f2", "master_id": "m2", "nom": "Marie Test - 10. MA PHRASE", "etat": "En cours", "module": "Clarifier · Module 1"},
    ],
    "kpi": [{"id": "k", "nom": "RDV", "valeur_j0": 1, "valeur_j30": 4, "objectif_j30": 6}],
    "personnalisation": {"scores_diagnostic": {"Offre": 1}, "scores": {"Offre": 2}, "total": 7, "total_actuel": 9, "chiffres": True, "zones_prioritaires": []},
    "regularite": {"serie": 2, "semaines": 3, "derniere": J(5)},
}
POSITIONNEMENT = [{"nom": "Marie Test - 10. MA PHRASE", "reponses": [
    ("Ta phrase de positionnement officielle", "J'aide les familles de Baie-Mahault à réparer leurs fuites sans attendre trois semaines grâce à mon astreinte."),
    ("Quel est le problème urgent et douloureux que vous résolvez pour votre client ?", "x" * 300),
]}]
CHAMPS_POSITIONNEMENT = {ns._NUMERO_TO_MASTER_ID["11"]: {"champs": [{"cle": "phrase_positionnement_officielle", "libelle": "Ta phrase de positionnement officielle"}]}}

print("Metier")
check("plomberie -> btp", biblio.detecter_metier(DASHBOARD["identite"]) == "btp")
check("coiffure -> beaute", biblio.detecter_metier({"activite": "Coiffeuse à domicile"}) == "beaute")
check("rien -> metier par defaut", biblio.detecter_metier({}) == biblio.METIER_PAR_DEFAUT)
check("chaque metier a ses valeurs", all({"libelle", "cible", "resultat", "probleme"} <= set(m) for m in biblio.METIERS.values()))
check("tous les modeles ont une categorie connue", all(m["categorie"] in biblio.CATEGORIES for m in biblio.MODELES))

print("Bibliotheque")
with patch.object(ns, "reponses_des_fiches", return_value=[]):
    contenu = biblio.bibliotheque(CLIENT, DASHBOARD)
textes = " ".join(m["texte"] for m in contenu["modeles"])
check("metier detecte par defaut", contenu["metier"] == "btp" and contenu["metier_detecte"] == "btp")
check("valeurs du metier sans mots du client", biblio.METIERS["btp"]["cible"] in textes and contenu["personnalise_avec"] == [])
check("aucune accolade restante", "{" not in textes and "}" not in textes)
check("prenom du client", "je m'appelle Marie" in textes)
check("[Prénom] du destinataire garde", "[Prénom]" in textes)

with patch.dict(ns.FICHE_SCHEMAS, CHAMPS_POSITIONNEMENT), patch.object(ns, "reponses_des_fiches", return_value=POSITIONNEMENT):
    contenu = biblio.bibliotheque(CLIENT, DASHBOARD, metier="beaute")
textes = " ".join(m["texte"] for m in contenu["modeles"])
check("metier choisi par le client", contenu["metier"] == "beaute" and contenu["metier_detecte"] == "btp")
check("phrase de positionnement reprise", "J'aide les familles de Baie-Mahault à réparer leurs fuites, sans attendre trois semaines" in textes)
check("reponse trop longue ignoree", "x" * 50 not in textes)
check("champs personnalises listes", contenu["personnalise_avec"] == ["cible", "probleme", "resultat"])
with patch.object(ns, "reponses_des_fiches", return_value=[]):
    check("metier inconnu -> detecte", biblio.bibliotheque(CLIENT, DASHBOARD, metier="pirate")["metier"] == "btp")

print("Routes de la bibliotheque")
with patch.object(ns, "get_client_dashboard", return_value=DASHBOARD), patch.object(ns, "reponses_des_fiches", return_value=[]):
    code, contenu = statut(portal_main.portal_bibliotheque, metier=None, authorization=BEARER)
check("GET 200 avec 11 modeles", code == 200 and len(contenu["modeles"]) == len(biblio.MODELES))
code, _ = statut(portal_main.portal_bibliotheque, metier=None, authorization="")
check("sans session -> 401", code == 401)


def personnaliser(modele, reponse="Bonjour [Prénom], version Idris."):
    idris_service._compteurs.clear()
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
         patch.object(ns, "get_client_dashboard", return_value=DASHBOARD), \
         patch.object(ns, "reponses_des_fiches", return_value=[]), \
         patch.object(idris_service, "_contexte", return_value="Contexte de Marie"), \
         patch.object(ia_service, "generer", return_value=reponse) as generer:
        code, resultat = statut(portal_main.portal_bibliotheque_personnaliser, portal_main.PersonnaliserModeleRequest(modele=modele), authorization=BEARER)
    return code, resultat, generer


code, resultat, generer = personnaliser("relance_j3")
check("personnalisation : texte d'Idris", code == 200 and resultat["texte"] == "Bonjour [Prénom], version Idris.")
demande = generer.call_args[0][1][0]["texte"] if generer.called else ""
check("modele et contexte transmis", "Contexte de Marie" in demande and "Relance à J+3" in demande)
code, _, generer = personnaliser("inconnu")
check("modele inconnu -> 422 sans appel IA", code == 422 and not generer.called)
code, _, _ = personnaliser("relance_j3", reponse="   ")
check("reponse vide -> 503", code == 503)
idris_service._compteurs.clear()
with patch.object(idris_service, "_MAX_REDACTIONS_JOUR", 0), patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
     patch.object(ns, "get_client_dashboard", return_value=DASHBOARD), patch.object(ns, "reponses_des_fiches", return_value=[]), \
     patch.object(ia_service, "generer") as generer:
    code, _ = statut(portal_main.portal_bibliotheque_personnaliser, portal_main.PersonnaliserModeleRequest(modele="relance_j3"), authorization=BEARER)
check("limite du jour -> 429", code == 429 and not generer.called)

print("Objectif 90 jours (accueil guide)")
with patch.object(ns, "_update_page") as update:
    code, resultat = statut(portal_main.portal_objectif, portal_main.ObjectifRequest(objectif="  5 nouveaux   clients  "), authorization=BEARER)
check("objectif enregistre et nettoye", code == 200 and resultat["objectif_90j"] == "5 nouveaux clients")
check("propriete Objectif 90j ecrite", update.call_args[0] == (CLIENT, {"Objectif 90j": {"rich_text": [{"text": {"content": "5 nouveaux clients"}}]}}))
for label, texte in [("vide", "  "), ("trop long", "x" * 301)]:
    with patch.object(ns, "_update_page") as update:
        code, _ = statut(portal_main.portal_objectif, portal_main.ObjectifRequest(objectif=texte), authorization=BEARER)
    check(f"objectif {label} -> 422", code == 422 and not update.called)

print("Lien de partage")
code, lien = statut(portal_main.portal_creer_partage, authorization=BEARER)
check("lien cree", code == 200 and lien["url"].endswith(f"/?partage={lien['jeton']}") and lien["jours"] == 30)
with patch.object(ns, "get_client_dashboard", return_value=DASHBOARD) as lecture:
    code, public = statut(portal_main.public_partage, jeton=lien["jeton"])
check("progression publique lue pour le bon client", code == 200 and lecture.call_args[0][0] == CLIENT)
check("prenom seul", public["prenom"] == "Marie" and "Test" not in json.dumps(public))
check("ni email ni telephone ni identite", "identite" not in public and "client@test.com" not in json.dumps(public) and "0690" not in json.dumps(public))
check("ni id ni nom de fiche", all(set(f) == {"etat", "module"} for f in public["fiches"]))
check("avant / maintenant et KPI", public["personnalisation"]["total_actuel"] == 9 and public["kpi"][0] == {"nom": "RDV", "valeur_j0": 1, "valeur_j30": 4, "valeur_j60": None, "valeur_j90": None})
code, _ = statut(portal_main.public_partage, jeton=lien["jeton"] + "x")
check("jeton modifie -> 404", code == 404)
code, _ = statut(portal_main.public_partage, jeton=BEARER.removeprefix("Bearer "))
check("jeton de session refuse -> 404", code == 404)
with patch.object(fidelite, "PARTAGE_JOURS", -1):
    code, _ = statut(portal_main.public_partage, jeton=lien["jeton"])
check("lien expire -> 404", code == 404)

print("Avis J90")


def avis(dashboard, **champs):
    requete = portal_main.AvisJ90Request(**{"note": 9, "avis": "J'ai enfin une routine.", **champs})
    with patch.object(ns, "get_client_dashboard", return_value=dashboard), patch.object(ns, "_create_page") as creation:
        code, resultat = statut(portal_main.portal_avis_j90, requete, authorization=BEARER)
    return code, creation


code, creation = avis(DASHBOARD)
check("avant J80 -> 403", code == 403 and not creation.called)
FIN = {**DASHBOARD, "date_demarrage": J(85)}
code, creation = avis(FIN, accord_publication=True, signature="Marie, plombière à Baie-Mahault")
proprietes = creation.call_args[0][1] if creation.called else {}
contenu = json.loads("".join(t["text"]["content"] for t in proprietes.get("Données (JSON)", {}).get("rich_text", [])) or "{}")
check("avis enregistre", code == 200 and "Avis J90" in proprietes["Nom"]["title"][0]["text"]["content"])
check("note, avis, accord et signature", contenu == {"note_sur_10": 9, "avis": "J'ai enfin une routine.", "accord_publication": True, "signature_souhaitee": "Marie, plombière à Baie-Mahault"})
code, creation = avis(FIN, signature="Marie")
contenu = json.loads("".join(t["text"]["content"] for t in creation.call_args[0][1]["Données (JSON)"]["rich_text"]))
check("sans accord : pas de signature gardee", contenu["accord_publication"] is False and contenu["signature_souhaitee"] == "")
for label, champs in [("note 11", {"note": 11}), ("note negative", {"note": -1}), ("avis vide", {"avis": " "}), ("avis trop long", {"avis": "x" * 1501})]:
    code, creation = avis(FIN, **champs)
    check(f"{label} -> 422", code == 422 and not creation.called)

print("Recap hebdomadaire")


def client_notion(cid, etat="En cours", email="a@test.com", desactive=None):
    props = {
        "État": {"type": "status", "status": {"name": etat}},
        "E-mail": {"type": "email", "email": email},
    }
    if desactive is not None:
        props["Récap hebdo désactivé"] = {"type": "checkbox", "checkbox": desactive}
    return {"id": cid, "properties": props}


CLIENTS = [client_notion("c1"), client_notion("c2", etat="Terminé"), client_notion("c3", email=None), client_notion("c4", desactive=True), client_notion("c5")]
BILAN = {"id": "fb", "master_id": ns._BILAN_HEBDO_MASTER_ID, "nom": "X - 16. BILAN", "etat": "En cours"}
DASH_RECAP = {**DASHBOARD, "fiches": [*DASHBOARD["fiches"], BILAN]}
HISTORIQUE = [{"semaine_du": J(14), "contacts": 5.0, "rdv": 1.0, "ventes": 0.0}, {"semaine_du": J(7), "contacts": 12.0, "rdv": 3.0, "ventes": 1.0}]


def dashboards(cid):
    return {**DASH_RECAP, "date_demarrage": J(3)} if cid == "c5" else DASH_RECAP


with patch.dict("os.environ", {"GEMINI_API_KEY": "", "COACH_DIAGNOSTIC_API_KEY": "cle-auto"}), \
     patch.object(ns, "_query_data_source", return_value=CLIENTS), \
     patch.object(ns, "get_client_dashboard", side_effect=dashboards), \
     patch.object(ns, "_historique_bilans", return_value=HISTORIQUE):
    code, resultat = statut(portal_main.automation_recap_hebdo, authorization="Bearer cle-auto")
    code_sans_cle, _ = statut(portal_main.automation_recap_hebdo, authorization="Bearer mauvaise")
recaps = resultat["recaps"] if code == 200 else []
check("seulement les clients en cours, avec email, non desactives, apres J7", [r["client_page_id"] for r in recaps] == ["c1"])
recap = recaps[0] if recaps else {}
check("3 chiffres de la derniere semaine", recap.get("chiffres") == {"semaine_du": J(7), "contacts": 12.0, "rdv": 3.0, "ventes": 1.0})
check("texte pret a envoyer", "Contacts : 12" in recap.get("texte", "") and "Rendez-vous : 3" in recap.get("texte", "") and "Ventes : 1" in recap.get("texte", ""))
check("phrase de secours sans Gemini", "2 semaines de bilan d'affilée" in recap.get("texte", ""))
check("prochaine etape = premiere fiche non terminee", recap.get("prochaine_etape") == "10. MA PHRASE")
check("objet", recap.get("objet") == "Marie, ta semaine en 3 chiffres")
check("mauvaise cle -> 401", code_sans_cle == 401)

with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
     patch.object(ns, "get_client_dashboard", return_value=DASH_RECAP), \
     patch.object(ns, "_historique_bilans", return_value=[]), \
     patch.object(ia_service, "generer") as generer:
    recap = fidelite.recap_du_client("c1", "a@test.com")
check("sans bilan : invitation a en remplir un, sans IA", recap["chiffres"] is None and "Pas encore de bilan" in recap["texte"] and not generer.called)

with patch.dict("os.environ", {"GEMINI_API_KEY": "test"}), \
     patch.object(ns, "get_client_dashboard", return_value=DASH_RECAP), \
     patch.object(ns, "_historique_bilans", return_value=HISTORIQUE), \
     patch.object(ia_service, "generer", return_value="Belle semaine, Marie : 3 rendez-vous !") as generer:
    recap = fidelite.recap_du_client("c1", "a@test.com")
check("phrase d'Idris avec les chiffres", "Belle semaine, Marie" in recap["texte"] and "12 contacts" in generer.call_args[0][1][0]["texte"])

print("Communaute : lien du groupe")
with patch.dict("os.environ", {"COMMUNAUTE_LIEN_GROUPE": "https://chat.whatsapp.com/commun"}):
    check("lien de la cohorte prioritaire", ns._lien_groupe({"lien_groupe": "https://chat.whatsapp.com/cohorte"}) == "https://chat.whatsapp.com/cohorte")
    check("sinon lien commun", ns._lien_groupe(None) == "https://chat.whatsapp.com/commun")
    check("lien non https ignore", ns._lien_groupe({"lien_groupe": "javascript:alert(1)"}) is None)
with patch.dict("os.environ", {"COMMUNAUTE_LIEN_GROUPE": ""}):
    check("aucun lien -> None", ns._lien_groupe({}) is None)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
