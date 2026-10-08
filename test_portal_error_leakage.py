# Tests P1-F : aucune erreur technique (URL Notion / systeme.io, ids, email, nom,
# payload, nom de variable d'environnement) ne sort dans une reponse HTTP des
# routes portail et coach ; le detail nettoye va uniquement dans les logs
# ([portal-error]).
#
# Entierement mockes (aucun appel reseau reel) : les fonctions de route sont
# appelees directement, les services sont remplaces et toute tentative reseau
# imprevue (requests.Session.request) leve une AssertionError comptee. Meme
# style que test_portal_authz.py (script simple, aucune dependance
# supplementaire).
#
# Lancer : python test_portal_error_leakage.py

import logging
import os
import re
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from fastapi import BackgroundTasks, HTTPException

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service
from backend.services import systeme_io_service

portal_auth_service.SECRET_KEY = "cle-de-test-error-leakage"

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


# --- Valeurs fictives ------------------------------------------------------------

EMAIL = "marie.martin@exemple.test"
NOM = "Marie Martin"
TEL = "+590690123456"
CLE_COACH = "cle-coach-factice"
CLE_DIAG = "cle-diagnostic-factice"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
FICHE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ID_SAISI = "identifiant-saisi-par-le-coach-9f3a"
PAGE_ORPHELINE = "99999999-8888-7777-6666-555555555555"
URL_NOTION = f"https://api.notion.com/v1/pages/{CLIENT_ID}"
URL_SYSTEME = f"https://api.systeme.io/api/contacts?limit=50&email={EMAIL}"
JETON = "jeton-factice-xyz789"
PAYLOAD = '{"cle": "valeur-secrete-payload", "email": "' + EMAIL + '"}'
GENERIQUE_503 = "Le service est momentanément indisponible. Réessayez dans quelques minutes."
GENERIQUE_404 = "Client introuvable."

MSG_NOTION = (
    f"Erreur Notion (page {CLIENT_ID}) : 404 Client Error: Not Found for url: {URL_NOTION} "
    f"jeton {JETON} payload {PAYLOAD} {EMAIL}"
)
MSG_SYSTEME = f"Erreur systeme.io (contacts) : 500 Server Error: Internal Server Error for url: {URL_SYSTEME}"
MSG_URL_NUE = f"Erreur Notion (query) : echec d'appel vers {URL_NOTION} (Caused by timeout)"
MSG_CONFIG = "PORTAL_SECRET_KEY manquant. Renseigne-le dans .env (voir .env.example)."
MSG_LOOKUP = f"Aucun client trouve pour l'identifiant '{ID_SAISI}'."
MSG_ONBOARD = (
    f"Onboarding de {NOM} echoue (Erreur Notion (creation page) : 500 Server Error: Internal Server Error "
    f"for url: {URL_NOTION} " + "detail-technique-intermediaire " * 14 + f"). Rollback partiel : 3/5 page(s) archivee(s), 2 page(s) restent orphelines et "
    f"doivent etre archivees a la main dans Notion : ['{PAGE_ORPHELINE}', 'autre-id-orphelin']. "
    f"Contact {EMAIL} tel {TEL}."
)

# Ce qui ne doit JAMAIS sortir dans une reponse HTTP.
INTERDITS_REPONSE = [
    "api.notion.com", "api.systeme.io", "https://", "http://", "notion", "systeme", "for url", "url:",
    CLIENT_ID, FICHE_ID, EMAIL, "marie", NOM, TEL, JETON, "valeur-secrete-payload", "cle-coach",
    "cle-diagnostic", "NOTION_API_KEY", "PORTAL_SECRET_KEY", "SYSTEME_IO_API_KEY", ".env", "Traceback",
    "HTTPSConnectionPool", "Max retries", "Erreur Notion", "Erreur systeme.io", "443", "Onboarding de",
    ID_SAISI, PAGE_ORPHELINE, "orphelines",
]

# Ce qui ne doit JAMAIS sortir dans un log (les identifiants de pages, utiles
# au diagnostic, restent autorises ; les jetons ne figurent jamais dans le texte
# d'une erreur `requests`).
INTERDITS_LOG = [
    "api.notion.com", "api.systeme.io", "https://", "http://", "valeur-secrete-payload", "{", "}",
    EMAIL, "marie.martin", "Traceback",
]


def fuites(texte, liste):
    t = str(texte).lower()
    return [f for f in liste if f.lower() in t]


# --- Capture des logs (logger racine) -------------------------------------------

class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


capture = Capture()
racine = logging.getLogger()
racine.addHandler(capture)
racine.setLevel(logging.DEBUG)


def repere():
    return len(capture.records)


def logs_depuis(debut):
    return capture.records[debut:]


def erreurs(enregistrements):
    return [r for r in enregistrements if r.levelno >= logging.ERROR]


def texte(enregistrements):
    return "\n".join(r.getMessage() for r in enregistrements)


# --- Environnement de test : cles fictives + reseau interdit ------------------------

tentatives_reseau = []


def reseau_interdit(*args, **kwargs):
    tentatives_reseau.append(1)
    raise AssertionError("appel reseau imprevu")


@contextmanager
def environnement(reseau=reseau_interdit, sans=()):
    variables = {
        "COACH_ONBOARD_KEY": CLE_COACH,
        "COACH_DIAGNOSTIC_API_KEY": CLE_DIAG,
        "NOTION_API_KEY": "cle-notion-factice",
        "SYSTEME_IO_API_KEY": "cle-systeme-factice",
    }

    with patch.dict(os.environ, variables), patch.object(requests.Session, "request", side_effect=reseau):
        for nom in sans:
            os.environ.pop(nom, None)

        ns._cache_clear()
        yield


def appeler(fonction, *args, **kwargs):
    # Renvoie (code HTTP, resultat ou detail, nom d'une exception inattendue).
    try:
        return 200, fonction(*args, **kwargs), None
    except HTTPException as error:
        return error.status_code, error.detail, None
    except Exception as error:
        return None, None, type(error).__name__


def bearer(client_page_id=CLIENT_ID):
    return "Bearer " + portal_auth_service.create_session_token(EMAIL, client_page_id)


def dashboard_ouvert():
    return {"nom": "Client", "fiches": [{"id": FICHE_ID, "master_id": "m", "acces": "🚀 En cours", "etat": "En cours"}]}


COACH = {"x_coach_key": CLE_COACH}
DIAG = {"authorization": "Bearer " + CLE_DIAG}
MAJ = portal_main.DiagnosticUpdateRequest(
    updates=[portal_main.DiagnosticUpdate(block_id="bloc", type="paragraph", label="Libelle", valeur="v")]
)
ENTREE = portal_main.PortalEntryRequest(data={"champ": "valeur"})
ONBOARD = portal_main.CoachClientOnboardRequest(nom=NOM, email=EMAIL, telephone=TEL)


def verifier_503(libelle, contexte, appel, cible, message=MSG_NOTION, patch_dashboard=False, classe=RuntimeError):
    # cible : (objet, attribut) dont l'appel leve l'erreur riche.
    objet, attribut = cible

    with environnement(), patch.object(objet, attribut, side_effect=classe(message)):
        debut = repere()
        code, detail, exception = appeler(appel)
        ecrits = erreurs(logs_depuis(debut))
        t = texte(logs_depuis(debut))

    check(f"{libelle} : aucune exception ne sort ({exception})", exception is None)
    check(f"{libelle} : 503", code == 503)
    check(f"{libelle} : detail exactement egal au message generique", detail == GENERIQUE_503)
    check(f"{libelle} : aucune fuite dans la reponse ({', '.join(fuites(detail, INTERDITS_REPONSE)) or 'aucune'})",
          not fuites(detail, INTERDITS_REPONSE))
    check(f"{libelle} : un seul log error [portal-error] contexte={contexte}",
          len(ecrits) == 1 and ecrits[0].getMessage().startswith(f"[portal-error] contexte={contexte} erreur={classe.__name__}: "))
    check(f"{libelle} : log sans fuite ({', '.join(fuites(t, INTERDITS_LOG)) or 'aucune'})", not fuites(t, INTERDITS_LOG))
    check(f"{libelle} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))


# --- Tests ---------------------------------------------------------------------------

print("=" * 80)
print("TEST 1/14 : routes client /portal/* - erreur du service -> 503 generique, log nettoye")
print("=" * 80)

fake_dash = lambda *_: dashboard_ouvert()

verifier_503("[C1] /portal/auth/verify (cle de signature absente)", "verify",
             lambda: portal_main.portal_verify(portal_main.PortalVerifyRequest(token="x")),
             (portal_auth_service, "verify_magic_link_token"), message=MSG_CONFIG)
verifier_503("[C2] session (cle de signature absente)", "session",
             lambda: portal_main.portal_me(authorization="Bearer x"),
             (portal_auth_service, "verify_session_token"), message=MSG_CONFIG)
verifier_503("[C3] /portal/me", "portal_me",
             lambda: portal_main.portal_me(authorization=bearer()), (ns, "get_client_dashboard"))
verifier_503("[C4] /portal/fiches/{id} (dashboard)", "portal_get_fiche",
             lambda: portal_main.portal_get_fiche(FICHE_ID, authorization=bearer()), (ns, "get_client_dashboard"))
verifier_503("[C5] /portal/livrables/{id} (dashboard)", "portal_get_livrable",
             lambda: portal_main.portal_get_livrable("livrable", authorization=bearer()), (ns, "get_client_dashboard"))
verifier_503("[C6] /portal/fiches/{id}/entries (dashboard)", "portal_create_entry",
             lambda: portal_main.portal_create_entry(FICHE_ID, ENTREE, authorization=bearer()),
             (ns, "get_client_dashboard"))
verifier_503("[C7] /portal/fiches/{id}/valider (dashboard)", "portal_valider_fiche",
             lambda: portal_main.portal_valider_fiche(FICHE_ID, MagicMock(), authorization=bearer()),
             (ns, "get_client_dashboard"))

# Echec sur le second appel (le dashboard est lu normalement)
with patch.object(ns, "get_client_dashboard", side_effect=fake_dash):
    verifier_503("[C8] /portal/fiches/{id} (get_fiche)", "portal_get_fiche",
                 lambda: portal_main.portal_get_fiche(FICHE_ID, authorization=bearer()), (ns, "get_fiche"))
    verifier_503("[C9] /portal/livrables/{id} (get_livrable)", "portal_get_livrable",
                 lambda: portal_main.portal_get_livrable("livrable", authorization=bearer()), (ns, "get_livrable"))
    verifier_503("[C10] /portal/fiches/{id}/entries (create_entry)", "portal_create_entry",
                 lambda: portal_main.portal_create_entry(FICHE_ID, ENTREE, authorization=bearer()), (ns, "create_entry"))
    verifier_503("[C11] /portal/fiches/{id}/valider (validate_fiche)", "portal_valider_fiche",
                 lambda: portal_main.portal_valider_fiche(FICHE_ID, MagicMock(), authorization=bearer()),
                 (ns, "validate_fiche"))


print("\n" + "=" * 80)
print("TEST 2/14 : routes coach /coach/* - erreur du service -> 503 generique, log nettoye")
print("=" * 80)

verifier_503("[K1] /coach/diagnostics", "coach_diagnostics",
             lambda: portal_main.coach_diagnostics(**COACH), (ns, "list_diagnostics_fiche8"))
verifier_503("[K1b] /coach/diagnostics (URL nue, sans « url: »)", "coach_diagnostics",
             lambda: portal_main.coach_diagnostics(**COACH), (ns, "list_diagnostics_fiche8"), message=MSG_URL_NUE)
verifier_503("[K2] /coach/diagnostic-rapport/{id}", "coach_diagnostic_rapport",
             lambda: portal_main.coach_diagnostic_rapport(ID_SAISI, **COACH), (ns, "get_diagnostic_rapport"))
verifier_503("[K3] /coach/bonus/{id}", "coach_bonus",
             lambda: portal_main.coach_bonus(ID_SAISI, **COACH), (ns, "get_bonus_resultat"))
verifier_503("[K4] /coach/diagnostic/{id}", "coach_diagnostic_bundle",
             lambda: portal_main.coach_diagnostic_bundle(ID_SAISI, **DIAG), (ns, "get_coach_diagnostic_bundle"))
verifier_503("[K5] /coach/fiches/{id}", "coach_get_fiche",
             lambda: portal_main.coach_get_fiche(FICHE_ID, CLIENT_ID, **COACH), (ns, "get_fiche"))
verifier_503("[K6] /coach/fiches/{id}/diagnostic-champs (GET)", "coach_get_diagnostic_champs",
             lambda: portal_main.coach_get_diagnostic_champs(FICHE_ID, **COACH), (ns, "get_diagnostic_fiche8"))
verifier_503("[K7] /coach/fiches/{id}/diagnostic-champs (POST)", "coach_update_diagnostic_champs",
             lambda: portal_main.coach_update_diagnostic_champs(FICHE_ID, MAJ, **COACH), (ns, "update_diagnostic_fiche8"))
verifier_503("[K8] /coach/fiches/{id}/valider", "coach_valider_fiche",
             lambda: portal_main.coach_valider_fiche(FICHE_ID, **COACH), (ns, "validate_fiche"))
verifier_503("[K9] /coach/leads/systeme-io (URL avec l'email recherche)", "coach_leads_systeme_io",
             lambda: portal_main.coach_leads_systeme_io(query=EMAIL, **COACH),
             (systeme_io_service, "search_contacts"), message=MSG_SYSTEME)


print("\n" + "=" * 80)
print("TEST 3/14 : 404 d'identifiant introuvable - « Client introuvable. », sans echo de l'identifiant")
print("=" * 80)

for libelle, contexte, appel, cible in (
    ("[N1] /coach/diagnostic-rapport/{id}", "coach_diagnostic_rapport",
     lambda: portal_main.coach_diagnostic_rapport(ID_SAISI, **COACH), (ns, "get_diagnostic_rapport")),
    ("[N2] /coach/diagnostic/{id}", "coach_diagnostic_bundle",
     lambda: portal_main.coach_diagnostic_bundle(ID_SAISI, **DIAG), (ns, "get_coach_diagnostic_bundle")),
):
    with environnement(), patch.object(cible[0], cible[1], side_effect=LookupError(MSG_LOOKUP)):
        debut = repere()
        code, detail, exception = appeler(appel)
        ecrits = erreurs(logs_depuis(debut))

    check(f"{libelle} : 404 et message exact « Client introuvable. »", (code, detail) == (404, GENERIQUE_404))
    check(f"{libelle} : l'identifiant saisi n'apparait pas dans la reponse", ID_SAISI not in str(detail))
    check(f"{libelle} : un log error [portal-error] contexte={contexte} erreur=LookupError",
          len(ecrits) == 1 and ecrits[0].getMessage().startswith(f"[portal-error] contexte={contexte} erreur=LookupError: "))


print("\n" + "=" * 80)
print("TEST 4/14 : onboarding coach - 503 generique, rollback et pages orphelines uniquement dans les logs")
print("=" * 80)

with environnement(), patch.object(ns, "onboard_client", side_effect=RuntimeError(MSG_ONBOARD)):
    debut = repere()
    code, detail, exception = appeler(portal_main.coach_onboard_client, ONBOARD, **COACH)
    ecrits = erreurs(logs_depuis(debut))
    t = texte(logs_depuis(debut))

check("[O1] 503 et message generique", (code, detail) == (503, GENERIQUE_503))
check("[O1] aucune fuite dans la reponse (nom, email, telephone, pages, rollback)",
      not fuites(detail, INTERDITS_REPONSE))
check("[O1] la liste des pages orphelines se trouve apres 300 caracteres, meme une fois le texte nettoye",
      portal_main._nettoyer_erreur(MSG_ONBOARD, None, 5000).index(PAGE_ORPHELINE) > 300)
check("[O1] un seul log error [portal-error] contexte=coach_onboard_client",
      len(ecrits) == 1 and ecrits[0].getMessage().startswith("[portal-error] contexte=coach_onboard_client erreur=RuntimeError: "))
check("[O1] le log conserve les informations de rollback utiles (pages a archiver, nombre)",
      PAGE_ORPHELINE in t and "restent orphelines" in t and "3/5" in t)
check("[O1] le log ne contient ni nom, ni email, ni telephone, ni URL",
      not fuites(t, INTERDITS_LOG + [NOM, "Marie", TEL]))
check("[O1] nom / email / telephone remplaces par un masque", t.count("<masque>") >= 3)
check("[O1] aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 5/14 : de bout en bout - vraies exceptions `requests` (reseau mocke)")
print("=" * 80)

erreur_http = requests.exceptions.HTTPError(f"404 Client Error: Not Found for url: {URL_NOTION}")
erreur_connexion = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='api.notion.com', port=443): Max retries exceeded with url: "
    f"/v1/pages/{CLIENT_ID} (Caused by NameResolutionError)"
)
erreur_timeout = requests.exceptions.Timeout(f"HTTPSConnectionPool(host='api.notion.com', port=443): Read timed out. url: {URL_NOTION}")
erreur_systeme = requests.exceptions.HTTPError(f"500 Server Error: Internal Server Error for url: {URL_SYSTEME}")

for libelle, exception, appel, contexte in (
    ("HTTPError Notion", erreur_http, lambda: portal_main.portal_me(authorization=bearer()), "portal_me"),
    ("ConnectionError Notion", erreur_connexion, lambda: portal_main.portal_me(authorization=bearer()), "portal_me"),
    ("Timeout Notion", erreur_timeout, lambda: portal_main.portal_me(authorization=bearer()), "portal_me"),
    ("HTTPError systeme.io", erreur_systeme, lambda: portal_main.coach_leads_systeme_io(query=EMAIL, **COACH),
     "coach_leads_systeme_io"),
    ("ConnectionError Notion (coach)", erreur_connexion, lambda: portal_main.coach_diagnostics(**COACH), "coach_diagnostics"),
):
    def leve(*args, _exception=exception, **kwargs):
        raise _exception

    with environnement(reseau=leve):
        debut = repere()
        code, detail, sortie = appeler(appel)
        ecrits = erreurs(logs_depuis(debut))
        t = texte(logs_depuis(debut))

    check(f"[E2E] {libelle} : 503 generique, aucune exception", (code, detail, sortie) == (503, GENERIQUE_503, None))
    check(f"[E2E] {libelle} : aucune fuite dans la reponse ({', '.join(fuites(detail, INTERDITS_REPONSE)) or 'aucune'})",
          not fuites(detail, INTERDITS_REPONSE))
    check(f"[E2E] {libelle} : un log error [portal-error] contexte={contexte}, sans fuite",
          len(ecrits) == 1 and f"contexte={contexte} " in t and not fuites(t, INTERDITS_LOG))


print("\n" + "=" * 80)
print("TEST 6/14 : la journalisation ne modifie jamais la reponse HTTP")
print("=" * 80)

pannes = {
    "le logger leve": lambda: patch.object(portal_main, "_journal_docuseal", MagicMock(error=MagicMock(side_effect=Exception("boom")))),
    "le nettoyage leve": lambda: patch.object(portal_main, "_nettoyer_erreur", side_effect=Exception("boom")),
}

for libelle, creer_panne in pannes.items():
    with environnement(), creer_panne(), patch.object(ns, "get_client_dashboard", side_effect=RuntimeError(MSG_NOTION)):
        code, detail, sortie = appeler(portal_main.portal_me, authorization=bearer())

    check(f"[L1] {libelle} (503) : reponse inchangee, aucune exception", (code, detail, sortie) == (503, GENERIQUE_503, None))

    with environnement(), creer_panne(), patch.object(ns, "get_diagnostic_rapport", side_effect=LookupError(MSG_LOOKUP)):
        code, detail, sortie = appeler(portal_main.coach_diagnostic_rapport, ID_SAISI, **COACH)

    check(f"[L2] {libelle} (404) : reponse inchangee, aucune exception", (code, detail, sortie) == (404, GENERIQUE_404, None))

    with environnement(), creer_panne(), patch.object(ns, "onboard_client", side_effect=RuntimeError(MSG_ONBOARD)):
        code, detail, sortie = appeler(portal_main.coach_onboard_client, ONBOARD, **COACH)

    check(f"[L3] {libelle} (onboarding) : reponse inchangee, aucune exception", (code, detail, sortie) == (503, GENERIQUE_503, None))


print("\n" + "=" * 80)
print("TEST 7/14 : les deux 401 restent inchanges (messages fixes)")
print("=" * 80)

with environnement(), patch.object(portal_auth_service, "verify_magic_link_token", side_effect=ValueError("Ce lien a expire.")):
    debut = repere()
    code, detail, sortie = appeler(portal_main.portal_verify, portal_main.PortalVerifyRequest(token="x"))
    check("[A1] verify : 401 et message « Ce lien a expire. » inchanges", (code, detail) == (401, "Ce lien a expire."))
    check("[A1] verify : aucun log [portal-error]", "[portal-error]" not in texte(logs_depuis(debut)))

with environnement(), patch.object(portal_auth_service, "verify_session_token", side_effect=ValueError("Lien invalide.")):
    debut = repere()
    code, detail, sortie = appeler(portal_main.portal_me, authorization="Bearer x")
    check("[A2] session : 401 et message « Lien invalide. » inchanges", (code, detail) == (401, "Lien invalide."))
    check("[A2] session : aucun log [portal-error]", "[portal-error]" not in texte(logs_depuis(debut)))

with environnement():
    code, detail, sortie = appeler(portal_main.portal_me, authorization="")
    check("[A3] Authorization manquant : 401 inchange", (code, detail) == (401, "Authorization manquant."))


print("\n" + "=" * 80)
print("TEST 8/14 : comportements inchanges (succes, 403/404 metier, autres exceptions)")
print("=" * 80)

with environnement(), patch.object(ns, "get_client_dashboard", return_value={"nom": "Client", "fiches": []}):
    check("[S1] /portal/me : donnees renvoyees telles quelles", portal_main.portal_me(authorization=bearer()) == {"nom": "Client", "fiches": []})

with environnement(), patch.object(ns, "list_diagnostics_fiche8", return_value=[{"client": "x"}]):
    check("[S2] /coach/diagnostics : donnees renvoyees telles quelles",
          portal_main.coach_diagnostics(**COACH) == {"diagnostics": [{"client": "x"}]})

with environnement(), patch.object(ns, "onboard_client", return_value={"status": "ok"}):
    check("[S3] /coach/clients/onboard : resultat renvoye tel quel", portal_main.coach_onboard_client(ONBOARD, **COACH) == {"status": "ok"})

with environnement(), patch.object(systeme_io_service, "search_contacts", return_value=[{"id": 1}]):
    check("[S4] /coach/leads/systeme-io : donnees renvoyees telles quelles",
          portal_main.coach_leads_systeme_io(query="x", **COACH) == {"leads": [{"id": 1}]})

bloquee = {"nom": "Client", "fiches": [{"id": FICHE_ID, "master_id": "m", "acces": "🔒 Bloqué"}]}

with environnement(), patch.object(ns, "get_client_dashboard", return_value=bloquee):
    debut = repere()
    code, detail, sortie = appeler(portal_main.portal_create_entry, FICHE_ID, ENTREE, authorization=bearer())
    check("[S5] fiche bloquee : 403 et message metier inchanges", (code, detail) == (403, "Cette fiche n'est pas encore ouverte."))
    code, detail, sortie = appeler(portal_main.portal_get_fiche, "fiche-inconnue", authorization=bearer())
    check("[S6] fiche inconnue du client : 404 « Fiche introuvable. » inchange", (code, detail) == (404, "Fiche introuvable."))
    check("[S5-S6] aucun log [portal-error] pour les refus metier", "[portal-error]" not in texte(logs_depuis(debut)))

with environnement(), patch.object(ns, "get_client_dashboard", return_value=dashboard_ouvert()), \
     patch.object(ns, "get_livrable", side_effect=ns.LivrableNonAutorise("x")):
    code, detail, sortie = appeler(portal_main.portal_get_livrable, "livrable", authorization=bearer())
    check("[S7] livrable non autorise : 404 « Livrable introuvable. » inchange", (code, detail) == (404, "Livrable introuvable."))

for libelle, appel, cible in (
    ("/portal/me", lambda: portal_main.portal_me(authorization=bearer()), (ns, "get_client_dashboard")),
    ("/coach/diagnostics", lambda: portal_main.coach_diagnostics(**COACH), (ns, "list_diagnostics_fiche8")),
    ("/coach/leads/systeme-io", lambda: portal_main.coach_leads_systeme_io(query="x", **COACH), (systeme_io_service, "search_contacts")),
    ("/coach/clients/onboard", lambda: portal_main.coach_onboard_client(ONBOARD, **COACH), (ns, "onboard_client")),
):
    with environnement(), patch.object(cible[0], cible[1], side_effect=ValueError("bug interne")):
        debut = repere()
        code, detail, sortie = appeler(appel)
        check(f"[X] {libelle} : ValueError inattendue propagee telle quelle (ni 503 ni message generique)",
              (code, sortie) == (None, "ValueError"))
        check(f"[X] {libelle} : aucun log [portal-error]", "[portal-error]" not in texte(logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 9/14 : variable d'environnement absente - 503 generique, nom de la variable uniquement dans les logs")
print("=" * 80)

NOMS_VARIABLES = ["COACH_ONBOARD_KEY", "COACH_DIAGNOSTIC_API_KEY", "DOCUSEAL_WEBHOOK_SECRET", "manquant"]

for libelle, contexte, variable, appel in (
    ("[G1] cle coach absente (/coach/diagnostics)", "coach_cle_manquante", "COACH_ONBOARD_KEY",
     lambda: portal_main.coach_diagnostics(**COACH)),
    ("[G2] cle diagnostic absente (/coach/diagnostic/{id})", "coach_diagnostic_cle_manquante", "COACH_DIAGNOSTIC_API_KEY",
     lambda: portal_main.coach_diagnostic_bundle(ID_SAISI, **DIAG)),
):
    with environnement(sans=(variable,)):
        debut = repere()
        code, detail, sortie = appeler(appel)
        ecrits = erreurs(logs_depuis(debut))
        t = texte(logs_depuis(debut))

    check(f"{libelle} : 503 et message generique exact, aucune exception", (code, detail, sortie) == (503, GENERIQUE_503, None))
    check(f"{libelle} : le nom de la variable n'apparait pas dans la reponse ({', '.join(fuites(detail, NOMS_VARIABLES)) or 'aucune'})",
          not fuites(detail, NOMS_VARIABLES))
    check(f"{libelle} : un seul log error [portal-error] contexte={contexte}, avec le nom de la variable",
          len(ecrits) == 1 and ecrits[0].getMessage() == f"[portal-error] contexte={contexte} erreur=RuntimeError: {variable} manquant")
    check(f"{libelle} : aucune valeur de cle dans les logs", CLE_COACH not in t and CLE_DIAG not in t)
    check(f"{libelle} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))

with environnement(sans=("DOCUSEAL_WEBHOOK_SECRET",)):
    debut = repere()
    code, detail, sortie = appeler(portal_main.webhook_docuseal, {}, BackgroundTasks(), "secret-envoye")
    t = texte(logs_depuis(debut))

check("[G3] webhook DocuSeal, secret serveur absent : 503 et message generique exact, aucune exception",
      (code, detail, sortie) == (503, GENERIQUE_503, None))
check("[G3] le nom de la variable n'apparait pas dans la reponse", not fuites(detail, NOMS_VARIABLES))
check("[G3] le log existant « secret serveur non configure » est conserve (error), sans valeur de secret",
      "[docuseal] webhook refuse : secret serveur non configure" in t and "secret-envoye" not in t)


print("\n" + "=" * 80)
print("TEST 10/14 : refus d'acces 401 inchanges quand les cles sont configurees")
print("=" * 80)

with environnement():
    code, detail, sortie = appeler(portal_main.coach_diagnostics, x_coach_key="mauvaise-cle")
    check("[H1] mauvaise cle coach : 401 « Code d'acces invalide. »", (code, detail) == (401, "Code d'acces invalide."))
    code, detail, sortie = appeler(portal_main.coach_diagnostic_bundle, ID_SAISI, authorization="Bearer mauvaise-cle")
    check("[H2] mauvaise cle diagnostic : 401 « Cle API invalide. »", (code, detail) == (401, "Cle API invalide."))

with environnement(), patch.dict(os.environ, {"DOCUSEAL_WEBHOOK_SECRET": "secret-docuseal-factice"}):
    code, detail, sortie = appeler(portal_main.webhook_docuseal, {}, BackgroundTasks(), "mauvais-secret")
    check("[H3] mauvais secret DocuSeal : 401 « Secret invalide. »", (code, detail) == (401, "Secret invalide."))


print("\n" + "=" * 80)
print("TEST 11/14 : echec d'alerte coach en tache de fond - warning nettoye, sans exception")
print("=" * 80)

for libelle, fonction, lecture, alerte, contexte, infos in (
    ("diagnostic", portal_main._alerter_si_diagnostic_termine, "diagnostic_vient_de_se_terminer",
     "alerter_coach_diagnostic", "alerte_diagnostic", {"client_nom": NOM, "client_email": EMAIL}),
    ("bonus", portal_main._alerter_si_bonus_termine, "bonus_vient_de_se_terminer",
     "alerter_coach_bonus", "alerte_bonus", {"client_nom": NOM, "resultat": "resultat"}),
):
    for etape in ("lecture Notion en echec", "envoi de l'alerte en echec"):
        lecture_en_echec = etape.startswith("lecture")

        with environnement(), \
             patch.object(ns, lecture, side_effect=RuntimeError(MSG_NOTION) if lecture_en_echec else None,
                          return_value=infos), \
             patch.object(ns, alerte, side_effect=RuntimeError(MSG_NOTION)):
            debut = repere()

            try:
                fonction(CLIENT_ID, FICHE_ID)
                sortie = "aucune exception"
            except Exception as exc:
                sortie = type(exc).__name__

            enregistrements = logs_depuis(debut)
            t = texte(enregistrements)

        check(f"[W] alerte {libelle}, {etape} : aucune exception ne sort", sortie == "aucune exception")
        check(f"[W] alerte {libelle}, {etape} : un seul log warning [portal-error] contexte={contexte}",
              len(enregistrements) == 1 and enregistrements[0].levelno == logging.WARNING
              and enregistrements[0].getMessage().startswith(f"[portal-error] contexte={contexte} erreur=RuntimeError: "))
        check(f"[W] alerte {libelle}, {etape} : log sans fuite ({', '.join(fuites(t, INTERDITS_LOG)) or 'aucune'})",
              not fuites(t, INTERDITS_LOG))
        check(f"[W] alerte {libelle}, {etape} : ancien format brut supprime", "impossible :" not in t)
        check(f"[W] alerte {libelle}, {etape} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in enregistrements))

    with environnement(), patch.object(ns, lecture, side_effect=RuntimeError(MSG_NOTION)), \
         patch.object(portal_main, "_journal_docuseal", MagicMock(warning=MagicMock(side_effect=Exception("boom")))):
        try:
            fonction(CLIENT_ID, FICHE_ID)
            sortie = "aucune exception"
        except Exception as exc:
            sortie = type(exc).__name__

    check(f"[W] alerte {libelle}, panne du logger : aucune exception ne sort", sortie == "aucune exception")


print("\n" + "=" * 80)
print("TEST 12/14 : structure du code - plus aucun detail=str(error) hors des deux 401")
print("=" * 80)

source = open("portal_main.py", encoding="utf-8").read().splitlines()
restantes = [(i + 1, l.strip()) for i, l in enumerate(source) if "detail=str(" in l]
check("[Z1] exactement 2 occurrences de detail=str(...) restent", len(restantes) == 2)
check("[Z1] ces 2 occurrences sont des reponses 401", all("status_code=401" in l for _, l in restantes))
check("[Z2] aucune f-string ni str(error) dans un detail de reponse 503 ou 404",
      not [l for l in source if re.search(r"HTTPException\(status_code=(503|404), detail=(str\(|f\")", l)])
check("[Z3] _nettoyer_erreur tronque toujours a 300 caracteres par defaut", len(portal_main._nettoyer_erreur("a" * 2000)) == 300)
check("[Z3] et a la limite demandee si elle est fournie", len(portal_main._nettoyer_erreur("a" * 2000, None, 1500)) == 1500)


print("\n" + "=" * 80)
print("TEST 13/14 : isolation - aucun appel reseau reel")
print("=" * 80)

check("[R1] aucune tentative reseau imprevue pendant tous les tests", not tentatives_reseau)


print("\n" + "=" * 80)
print("TEST 14/14 : confidentialite globale des logs [portal-error]")
print("=" * 80)

lignes = [r.getMessage() for r in capture.records if "[portal-error]" in r.getMessage()]
tout = "\n".join(lignes)
check("[F1] 35 logs [portal-error] produits (29 de P1-F + 2 cles absentes + 4 alertes en echec)", len(lignes) == 35)
check("[F2] aucun log ne contient URL, hote, payload, email ou trace", not fuites(tout, INTERDITS_LOG))
check("[F3] aucune trace d'exception ni exc_info dans l'ensemble des logs", all(r.exc_info is None for r in capture.records))
check("[F4] chaque log suit le format [portal-error] contexte=<mot> erreur=<Classe>: <texte>",
      all(re.fullmatch(r"\[portal-error\] contexte=\w+ erreur=\w+: .*", l, flags=re.DOTALL) for l in lignes))
check("[F5] chaque log est limite a 1500 caracteres de texte", all(len(l) <= 1500 + 80 for l in lignes))


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
