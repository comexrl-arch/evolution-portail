# Tests de POST /portal/auth/request-link : aucune fuite technique vers le
# navigateur, logs serveur nettoyes, comportement metier preserve.
#
# Entierement mockes (aucun appel reseau reel vers Notion ou n8n) : la fonction
# de route est appelee directement, requests.post (et le client HTTP de Notion)
# sont remplaces par des gardes ou des faux. Toutes les valeurs (emails, noms,
# telephone, URL, secrets, jetons) sont fictives. Meme style que
# test_onboarding.py (script simple, pas de framework de test, aucune
# dependance supplementaire).
#
# Lancer : python test_portal_request_link.py

import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from pydantic import ValidationError
from fastapi import BackgroundTasks, HTTPException

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service
from backend.services import request_link_guard

portal_auth_service.SECRET_KEY = "cle-de-test-request-link"

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

SAISI = "Marie.Martin@Exemple.test"          # tel que saisi par l'utilisateur
EMAIL = SAISI.lower()
NOM = "Marie Martin"
TEL = "+590690123456"
SECRET = "secret-factice-request-link"
TOKEN = "jeton-factice-abc123"
HOTE = "n8n.exemple.test"
URL_N8N = f"https://{HOTE}/webhook/chemin-prive"
URL_NOTION = "https://api.notion.com/v1/data_sources/xyz/query"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
GENERIQUE = {"status": "sent", "message": "Si cet email est enregistre, un lien d'acces a ete envoye."}
MESSAGE_503 = "Le service est momentanément indisponible. Réessayez dans quelques minutes."
PAGE_CLIENT = {"id": CLIENT_ID, "properties": {"Nom": {"type": "title", "title": [{"plain_text": NOM}]}}}


# --- Capture des logs (tous loggers, via le logger racine) --------------------------

class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


capture = Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.DEBUG)


def repere():
    return len(capture.records)


def logs_depuis(debut):
    return capture.records[debut:]


def texte(records):
    return "\n".join(r.getMessage() for r in records)


def erreurs(records):
    return [r for r in records if r.levelno >= logging.ERROR]


# --- Outils de test ----------------------------------------------------------------

def garde_reseau(*args, **kwargs):
    raise AssertionError("appel reseau reel interdit dans ces tests")


@contextmanager
def environnement(webhook=URL_N8N, notion_key=True):
    # Variables isolees : aucune valeur reelle du poste n'est lue.
    with patch.dict(os.environ, {}, clear=False):
        for cle in ("N8N_WEBHOOK_MAGIC_LINK", "PORTAL_FRONTEND_URL"):
            os.environ.pop(cle, None)

        if webhook:
            os.environ["N8N_WEBHOOK_MAGIC_LINK"] = webhook

        os.environ["PORTAL_FRONTEND_URL"] = "https://portail.exemple.test"

        with patch.object(ns, "NOTION_API_KEY", "cle-notion-factice" if notion_key else None), \
             patch.object(requests, "post", side_effect=garde_reseau):
            yield


def executer(bt):
    # Execute les taches de fond apres la reponse, comme le fait Starlette.
    # Une exception qui s'echappe d'une tache de fond (traceback uvicorn avec URL
    # n8n) est une defaillance : elle est comptee, jamais propagee au script.
    for tache in bt.tasks:
        try:
            tache.func(*tache.args, **tache.kwargs)
        except Exception as exc:
            check(f"tache de fond : aucune exception ne s'echappe ({type(exc).__name__})", False)
            return exc

    return None


def appeler_avec_taches(email=SAISI, reinitialiser=True):
    # Renvoie (code HTTP, corps ou detail, BackgroundTasks) SANS executer les taches.
    # La garde est reinitialisee par defaut : chaque scenario part d'un etat vierge.
    if reinitialiser:
        request_link_guard._reinitialiser_pour_tests()

    bt = BackgroundTasks()

    try:
        return 200, portal_main.portal_request_link(portal_main.PortalLoginRequest(email=email), bt), bt
    except HTTPException as error:
        return error.status_code, error.detail, bt


def appeler(email=SAISI, reinitialiser=True):
    # Renvoie (code HTTP, corps ou detail) ; les taches de fond sont executees ensuite.
    code, corps, bt = appeler_avec_taches(email, reinitialiser)
    executer(bt)
    return code, corps


def fragments_interdits_reponse():
    return {
        "URL n8n": URL_N8N, "hote": HOTE, "chemin": "chemin-prive", "chemin /webhook": "/webhook",
        "URL Notion": "api.notion.com", "email saisi": SAISI, "email": EMAIL, "partie locale": "marie.martin",
        "prenom": "marie", "nom": "martin", "telephone": TEL, "chiffres telephone": TEL.lstrip("+"),
        "secret": SECRET, "jeton": TOKEN, "payload (cle magic_link)": "'magic_link'", "payload (client_name)": "client_name",
        "n8n": "n8n", "notion": "notion", "schema http": "http", "host": "host", "url:": "url:",
        "key=": "key=", "traceback": "traceback", "requests": "requests", "variable N8N": "N8N_WEBHOOK",
        "variable NOTION": "NOTION_API_KEY", "variable PORTAL": "PORTAL_SECRET_KEY", ".env": ".env",
    }


def fuites_reponse(detail):
    bas = str(detail).lower()
    return [nom for nom, v in fragments_interdits_reponse().items() if v.lower() in bas]


def fuites_logs(t):
    bas = t.lower()
    interdits = {
        "email saisi": SAISI, "email": EMAIL, "partie locale": "marie.martin", "prenom": "marie", "nom famille": "martin",
        "telephone": TEL, "chiffres telephone": TEL.lstrip("+"), "URL n8n": URL_N8N, "hote n8n": HOTE,
        "chemin": "chemin-prive", "URL Notion": "api.notion.com", "schema http": "http://", "schema https": "https://",
        "secret": SECRET, "jeton": TOKEN, "payload (cle magic_link)": "'magic_link'", "payload (cle JSON magic_link)": '"magic_link"', "payload (client_name)": "client_name",
        "traceback": "traceback", "accolade": "{", "key=": "key=",
    }
    return [nom for nom, v in interdits.items() if v.lower() in bas]


def erreur_http_requests():
    reponse = requests.Response()
    reponse.status_code = 500
    reponse.reason = "Internal Server Error"
    reponse.url = f"{URL_N8N}?key={SECRET}&tel={TEL}"

    try:
        reponse.raise_for_status()
    except requests.HTTPError as error:
        return error


ERREUR_CONNEXION = requests.ConnectionError(
    f"HTTPSConnectionPool(host='{HOTE}', port=443): Max retries exceeded with url: /webhook/chemin-prive?key={SECRET}&tel={TEL} (Caused by None)"
)
ERREUR_TIMEOUT = requests.Timeout(f"HTTPSConnectionPool(host='{HOTE}', port=443): Read timed out. (read timeout=15)")
PAYLOAD = {"to": SAISI, "client_name": NOM, "phone": TEL, "magic_link": f"https://portail.exemple.test/verify?token={TOKEN}"}

# Variantes du texte d'une erreur d'envoi (RuntimeError produite par send_portal_invite)
PREFIXE_ENVOI = "Erreur envoi invitation portail : "
VARIANTES_ENVOI = {
    "URL complete": f"{PREFIXE_ENVOI}echec sur {URL_N8N}?key={SECRET}&tel={TEL}",
    "host='...'": f"{PREFIXE_ENVOI}HTTPSConnectionPool(host='{HOTE}', port=443): echec",
    "url: /chemin": f"{PREFIXE_ENVOI}echec avec url: /webhook/chemin-prive/{SECRET}?tel={TEL}",
    "erreur HTTP requests": f"{PREFIXE_ENVOI}{erreur_http_requests()}",
    "erreur de connexion requests": f"{PREFIXE_ENVOI}{ERREUR_CONNEXION}",
    "erreur Timeout requests": f"{PREFIXE_ENVOI}{ERREUR_TIMEOUT}",
    "email, nom": f"{PREFIXE_ENVOI}echec pour {SAISI} ({NOM})",
    "payload repr": f"{PREFIXE_ENVOI}echec, payload {PAYLOAD} fin",
    "payload JSON": f"{PREFIXE_ENVOI}echec, payload {json.dumps(PAYLOAD)} fin",
    "payload tronque": f"{PREFIXE_ENVOI}echec, payload {str(PAYLOAD)[:60]}",
}
PREFIXE_RECHERCHE = "Erreur Notion (query) : "
VARIANTES_RECHERCHE = {
    "URL complete": f"{PREFIXE_RECHERCHE}500 Server Error for url: {URL_NOTION}?key={SECRET}",
    "host='...'": f"{PREFIXE_RECHERCHE}HTTPSConnectionPool(host='api.notion.com', port=443): echec",
    "url: /chemin": f"{PREFIXE_RECHERCHE}echec avec url: /v1/data_sources/xyz/query?tel={TEL}",
    "erreur de connexion requests": f"{PREFIXE_RECHERCHE}{ERREUR_CONNEXION}",
    "erreur Timeout requests": f"{PREFIXE_RECHERCHE}{ERREUR_TIMEOUT}",
    "email": f"{PREFIXE_RECHERCHE}echec pour {SAISI}",
    "payload JSON": f"{PREFIXE_RECHERCHE}echec, payload {json.dumps(PAYLOAD)} fin",
}


def verifier_echec(libelle, code, detail, debut, contexte, statut=503):
    # statut=503 : echec de la recherche Notion (reponse 503 generique).
    # statut=200 : echec d'envoi en tache de fond (reponse 200 generique identique).
    t = texte(logs_depuis(debut))
    ecrits = erreurs(logs_depuis(debut))

    if statut == 503:
        check(f"{libelle} : 503", code == 503)
        check(f"{libelle} : detail exactement egal au message generique", detail == MESSAGE_503)
    else:
        check(f"{libelle} : 200 (la reponse ne depend plus de l'envoi)", code == 200)
        check(f"{libelle} : corps exactement egal a la reponse generique", detail == GENERIQUE)

    check(f"{libelle} : aucune fuite dans la reponse HTTP ({', '.join(fuites_reponse(detail)) or 'aucune'})", not fuites_reponse(detail))
    check(f"{libelle} : un log error, contexte={contexte}", len(ecrits) == 1 and f"contexte={contexte}" in ecrits[0].getMessage())
    check(f"{libelle} : le log contient ref_email masquee et la classe de l'erreur",
          "ref_email=m***@exemple.test#" in t and "RuntimeError" in t)
    check(f"{libelle} : aucune fuite dans les logs ({', '.join(fuites_logs(t)) or 'aucune'})", not fuites_logs(t))
    check(f"{libelle} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))


# --- Tests ---------------------------------------------------------------------------

print("=" * 80)
print("TEST 1/12 : client connu, envoi reussi - comportement actuel preserve")
print("=" * 80)

with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT) as recherche, \
     patch.object(ns, "send_portal_invite", return_value=None) as envoi:
    debut = repere()
    code, corps, bt = appeler_avec_taches()
    check("[A] reponse 200 identique a l'actuelle", code == 200 and corps == GENERIQUE)
    check("[A] l'envoi n'est pas execute dans la reponse : une tache de fond est planifiee", envoi.call_count == 0 and len(bt.tasks) == 1)
    executer(bt)
    check("[A] recherche appelee avec l'email tel que saisi (comportement inchange)", recherche.call_args == ((SAISI,), {}))
    check("[A] send_portal_invite recoit les memes arguments (email saisi, id du client, nom)",
          envoi.call_args == ((SAISI, CLIENT_ID, NOM), {}))
    check("[A] aucun log warning/error", not any(r.levelno >= logging.WARNING for r in logs_depuis(debut)))

# Vrai send_portal_invite : generation du lien et appel n8n inchanges (requests.post simule)
faux_post = MagicMock(return_value=MagicMock(raise_for_status=MagicMock()))

with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
     patch.object(requests, "post", faux_post):
    debut = repere()
    code, corps = appeler()
    appel = faux_post.call_args
    envoye = appel.kwargs.get("json", {}) if appel else {}
    check("[A] envoi reel simule : reponse 200 generique", code == 200 and corps == GENERIQUE)
    check("[A] un seul appel n8n simule, vers l'URL configuree, timeout 15 s",
          faux_post.call_count == 1 and appel.args[0] == URL_N8N and appel.kwargs.get("timeout") == 15)
    check("[A] structure du payload n8n inchangee (to, client_name, magic_link)",
          set(envoye) == {"to", "client_name", "magic_link"} and envoye["to"] == SAISI and envoye["client_name"] == NOM)
    lien = envoye.get("magic_link", "")
    jeton = lien.split("token=", 1)[-1]
    donnees = portal_auth_service.verify_magic_link_token(jeton)
    check("[A] lien magique valide, du bon type, au nom du client",
          lien.startswith("https://portail.exemple.test/verify?token=") and donnees["client_page_id"] == CLIENT_ID
          and donnees["email"] == SAISI and donnees["type"] == "magic_link")
    check("[A] duree de validite du lien de creation du mot de passe (48 heures)", portal_auth_service.MAGIC_LINK_MAX_AGE == 48 * 60 * 60)
    check("[A] aucun log warning/error", not any(r.levelno >= logging.WARNING for r in logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 2/12 : email inconnu - 200 generique, aucun envoi, aucun log error")
print("=" * 80)

with environnement(), patch.object(ns, "find_client_by_email", return_value=None), \
     patch.object(ns, "send_portal_invite") as envoi:
    debut = repere()
    code, corps = appeler("inconnu@exemple.test")
    check("[B] reponse 200 generique identique", code == 200 and corps == GENERIQUE)
    check("[B] aucun envoi", envoi.call_count == 0)
    check("[B] aucun log error inutile", not erreurs(logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 3/12 : echec de la recherche client (RuntimeError) - 503 generique, log nettoye")
print("=" * 80)

for libelle, message in VARIANTES_RECHERCHE.items():
    with environnement(), patch.object(ns, "find_client_by_email", side_effect=RuntimeError(message)), \
         patch.object(ns, "send_portal_invite") as envoi:
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[C] recherche, {libelle}", code, detail, debut, "recherche_client")
        check(f"[C] recherche, {libelle} : aucun envoi tente", envoi.call_count == 0)


print("\n" + "=" * 80)
print("TEST 4/12 : echec de l'envoi du lien en tache de fond (RuntimeError) - 200 generique, log nettoye")
print("=" * 80)

for libelle, message in VARIANTES_ENVOI.items():
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
         patch.object(ns, "send_portal_invite", side_effect=RuntimeError(message)):
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[D] envoi, {libelle}", code, detail, debut, "envoi_lien", statut=200)

# De bout en bout : vrai send_portal_invite, requests.post leve une vraie exception requests
for libelle, exception in (("HTTPError", erreur_http_requests()), ("ConnectionError", ERREUR_CONNEXION), ("Timeout", ERREUR_TIMEOUT)):
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
         patch.object(requests, "post", side_effect=exception):
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[D] de bout en bout, {libelle} reel via send_portal_invite", code, detail, debut, "envoi_lien", statut=200)

# De bout en bout cote recherche : vrai find_client_by_email, client HTTP de Notion en echec
with environnement(), patch.object(ns._http, "post", side_effect=ERREUR_CONNEXION):
    debut = repere()
    code, detail = appeler()
    verifier_echec("[C] de bout en bout, ConnectionError reel via find_client_by_email", code, detail, debut, "recherche_client")


print("\n" + "=" * 80)
print("TEST 5/12 : configuration absente - 200 generique (envoi) ou 503 generique (recherche), aucun nom de variable")
print("=" * 80)

with environnement(webhook=None), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
    debut = repere()
    code, detail = appeler()
    t = texte(logs_depuis(debut))
    check("[E] webhook n8n non configure : 200 generique (echec journalise en tache de fond)", code == 200 and detail == GENERIQUE)
    check("[E] aucun nom de variable d'environnement dans la reponse", not fuites_reponse(detail))
    check("[E] le log reste utile (indique la configuration manquante)", "manquant" in t and "contexte=envoi_lien" in t)
    check("[E] le log ne contient aucune fuite", not fuites_logs(t))

cle_precedente = portal_auth_service.SECRET_KEY
portal_auth_service.SECRET_KEY = None

try:
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
        debut = repere()
        code, detail = appeler()
        check("[E] cle de signature absente : 200 generique (echec journalise en tache de fond)", code == 200 and detail == GENERIQUE)
        check("[E] aucun nom de variable dans la reponse", not fuites_reponse(detail))
        check("[E] le log indique la cause fonctionnelle", "manquant" in texte(logs_depuis(debut)))
finally:
    portal_auth_service.SECRET_KEY = cle_precedente

with environnement(notion_key=False):
    debut = repere()
    code, detail = appeler()
    check("[E] cle Notion absente (vrai find_client_by_email) : 503 generique", code == 503 and detail == MESSAGE_503)
    check("[E] aucun nom de variable dans la reponse", not fuites_reponse(detail))


print("\n" + "=" * 80)
print("TEST 6/12 : le helper de journalisation echoue - la reponse generique est preservee")
print("=" * 80)

pannes = {
    "logger en echec": lambda: patch.object(portal_main._journal_docuseal, "error", side_effect=RuntimeError(f"panne {URL_N8N}")),
    "nettoyage en echec": lambda: patch.object(portal_main, "_nettoyer_erreur", side_effect=KeyError("boom")),
    "reference en echec": lambda: patch.object(portal_main, "_reference_docuseal", side_effect=ValueError(SAISI)),
}

for libelle, creer_panne in pannes.items():
    for chemin, (nom_fn, erreur) in (
        ("recherche", ("find_client_by_email", RuntimeError(VARIANTES_RECHERCHE["URL complete"]))),
        ("envoi", ("send_portal_invite", RuntimeError(VARIANTES_ENVOI["URL complete"]))),
    ):
        with environnement(), creer_panne(), \
             patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
            with patch.object(ns, nom_fn, side_effect=erreur):
                try:
                    code, detail = appeler()
                    sortie = "reponse"
                except Exception as exc:
                    code, detail, sortie = None, None, f"exception {type(exc).__name__}"

        check(f"[G] {libelle}, echec de {chemin} : aucune exception supplementaire ne sort", sortie == "reponse")
        attendu = (503, MESSAGE_503) if chemin == "recherche" else (200, GENERIQUE)
        check(f"[G] {libelle}, echec de {chemin} : reponse generique inchangee {attendu[0]}", (code, detail) == attendu)

try:
    retour = portal_main._journaliser_echec_lien("envoi_lien", RuntimeError("x"), None, None)
    helper_sur = retour is None
except Exception:
    helper_sur = False

check("[G] le helper accepte aussi des arguments inattendus (None) sans lever", helper_sur)


print("\n" + "=" * 80)
print("TEST 7/12 : exceptions autres que RuntimeError - recherche inchangee, envoi capture en tache de fond")
print("=" * 80)

with environnement(), patch.object(ns, "find_client_by_email", side_effect=KeyError("bug interne")):
    debut = repere()

    try:
        appeler()
        resultat = "aucune exception"
    except HTTPException as error:
        resultat = f"HTTP {error.status_code}"
    except Exception as error:
        resultat = f"{type(error).__name__} propagee"

    check("[H] recherche : KeyError propagee telle quelle (ni 503 ni message generique)", resultat == "KeyError propagee")
    check("[H] recherche : aucun log du helper pour cette exception", not erreurs(logs_depuis(debut)))

# Comportement volontairement modifie par P1-E : l'envoi est une tache de fond, il n'y a plus de
# reponse HTTP a laquelle propager l'exception ; elle est donc capturee et journalisee (nettoyee).
with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
     patch.object(ns, "send_portal_invite", side_effect=ValueError(f"bug interne {URL_N8N} {SAISI}")):
    debut = repere()

    try:
        code, corps = appeler()
        resultat = "reponse"
    except Exception as error:
        code, corps, resultat = None, None, f"{type(error).__name__} propagee"

    t = texte(logs_depuis(debut))
    check("[H] envoi : ValueError capturee dans la tache de fond (aucune exception ne sort)", resultat == "reponse")
    check("[H] envoi : la reponse est la reponse generique 200", (code, corps) == (200, GENERIQUE))
    check("[H] envoi : log error avec la classe ValueError, sans URL ni email", "ValueError" in t and not fuites_logs(t))

try:
    portal_main.PortalLoginRequest()
    validation = "aucune erreur"
except ValidationError:
    validation = "ValidationError"

check("[H] la validation d'entree (email obligatoire) est inchangee : erreur de validation (422 cote FastAPI)",
      validation == "ValidationError")


print("\n" + "=" * 80)
print("TEST 8/12 : uniformite - email inconnu, envoi reussi et echec d'envoi donnent la meme reponse")
print("=" * 80)

scenarios = {
    "email inconnu": (None, None),
    "client connu, envoi reussi": (PAGE_CLIENT, None),
    "client connu, echec n8n": (PAGE_CLIENT, RuntimeError(VARIANTES_ENVOI["URL complete"])),
}
observations = {}
planifications = {}

for libelle, (page, erreur_envoi) in scenarios.items():
    with environnement(), patch.object(ns, "find_client_by_email", return_value=page) as recherche, \
         patch.object(ns, "send_portal_invite", side_effect=erreur_envoi) as envoi:
        code, corps, bt = appeler_avec_taches()
        avant_taches = (recherche.call_count, envoi.call_count)
        planifiees = [(tache.func, tache.args) for tache in bt.tasks]
        executer(bt)
        observations[libelle] = (code, corps, avant_taches, len(bt.tasks))
        planifications[libelle] = (planifiees, envoi.call_count)

for libelle, (code, corps, avant_taches, nb_taches) in observations.items():
    check(f"[U] {libelle} : 200 et corps generique identiques", (code, corps) == (200, GENERIQUE))
    check(f"[U] {libelle} : une seule recherche Notion synchrone et aucun envoi dans la reponse", avant_taches == (1, 0))

check("[U] les trois reponses (statut, corps) sont strictement identiques",
      len({(o[0], str(o[1])) for o in observations.values()}) == 1)
check("[U] seule la tache d'envoi differe : 0 tache (inconnu), 1 tache (client connu)",
      [observations[l][3] for l in scenarios] == [0, 1, 1])

# Verifications structurelles (aucune duree reelle, aucun sleep)
check("[U] le nombre d'appels synchrones a find_client_by_email est identique dans les trois cas (1)",
      {o[2][0] for o in observations.values()} == {1})
check("[U] send_portal_invite n'est jamais appele de maniere synchrone dans la reponse (0 appel avant les taches)",
      all(o[2][1] == 0 for o in observations.values()))
check("[U] email inconnu : aucune tache planifiee, aucun envoi", planifications["email inconnu"] == ([], 0))

for libelle in ("client connu, envoi reussi", "client connu, echec n8n"):
    planifiees, appels_apres = planifications[libelle]
    check(f"[U] {libelle} : l'envoi est planifie via BackgroundTasks (une tache _envoyer_lien_en_arriere_plan, args email/id/nom)",
          planifiees == [(portal_main._envoyer_lien_en_arriere_plan, (SAISI, CLIENT_ID, NOM))])
    check(f"[U] {libelle} : send_portal_invite n'est appele qu'a l'execution de la tache (1 appel)", appels_apres == 1)


print("\n" + "=" * 80)
print("TEST 9/12 : garde dans la route - filtrage silencieux, cooldown, limites (horloge simulee)")
print("=" * 80)


class Horloge:
    def __init__(self, t=5000.0):
        self.t = t

    def __call__(self):
        return self.t


def horloge_garde(h):
    return patch.object(request_link_guard.time, "monotonic", side_effect=h)


reponses_filtrees = {}

for libelle, page in (("client connu", PAGE_CLIENT), ("email inconnu", None)):
    h = Horloge()

    with environnement(), horloge_garde(h), \
         patch.object(ns, "find_client_by_email", return_value=page) as recherche, \
         patch.object(ns, "send_portal_invite", return_value=None) as envoi:
        debut = repere()
        code1, corps1, bt1 = appeler_avec_taches()
        executer(bt1)
        check(f"[V] {libelle} : 1re demande acceptee (recherche appelee)", recherche.call_count == 1 and (code1, corps1) == (200, GENERIQUE))

        code2, corps2, bt2 = appeler_avec_taches(reinitialiser=False)
        executer(bt2)
        reponses_filtrees[libelle] = (code2, str(corps2), len(bt2.tasks), recherche.call_count)
        check(f"[V] {libelle} : renvoi immediat filtre en silence (200 generique identique)", (code2, corps2) == (200, GENERIQUE))
        check(f"[V] {libelle} : aucune nouvelle recherche Notion ni tache d'envoi (Notion protege)",
              recherche.call_count == 1 and len(bt2.tasks) == 0 and envoi.call_count == (1 if page else 0))

        h.t += 59
        code3, corps3, bt3 = appeler_avec_taches(reinitialiser=False)
        check(f"[V] {libelle} : a 59 s toujours filtre", recherche.call_count == 1 and len(bt3.tasks) == 0)

        h.t += 1
        code4, corps4, bt4 = appeler_avec_taches(reinitialiser=False)
        executer(bt4)
        check(f"[V] {libelle} : reprise apres le cooldown de 60 s (recherche appelee de nouveau)", recherche.call_count == 2)
        check(f"[V] {libelle} : envoi planifie de nouveau seulement pour un client connu", envoi.call_count == (2 if page else 0))

        t = texte(logs_depuis(debut))
        check(f"[V] {libelle} : le filtrage est journalise (raison controlee + email masque)",
              "demande filtree raison=cooldown ref_email=m***@exemple.test#" in t)
        check(f"[V] {libelle} : aucune donnee brute dans les logs de filtrage", not fuites_logs(t))

check("[V] une demande filtree est indiscernable : meme reponse, meme absence de tache et de recherche pour connu et inconnu",
      reponses_filtrees["client connu"][:3] == reponses_filtrees["email inconnu"][:3])

# Limite par email : 5 demandes / 15 minutes
h = Horloge()

with environnement(), horloge_garde(h), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT) as recherche, \
     patch.object(ns, "send_portal_invite", return_value=None) as envoi:
    debut = repere()
    acceptees = []

    for i in range(5):
        code, corps, bt = appeler_avec_taches(reinitialiser=(i == 0))
        executer(bt)
        acceptees.append(len(bt.tasks) == 1)
        h.t += 60

    check("[V] limite email : les 5 premieres demandes (hors cooldown) sont traitees", all(acceptees) and recherche.call_count == 5)
    code, corps, bt = appeler_avec_taches(reinitialiser=False)
    check("[V] limite email : la 6e est filtree en silence (200 generique, aucune recherche)",
          (code, corps) == (200, GENERIQUE) and len(bt.tasks) == 0 and recherche.call_count == 5)
    check("[V] limite email : raison journalisee limite_email", "demande filtree raison=limite_email" in texte(logs_depuis(debut)))

    h.t += 900
    code, corps, bt = appeler_avec_taches(reinitialiser=False)
    check("[V] limite email : reprise apres 15 minutes", len(bt.tasks) == 1 and recherche.call_count == 6)

# Plafond global : 100 demandes / 15 minutes
h = Horloge()

with environnement(), horloge_garde(h), patch.object(ns, "find_client_by_email", return_value=None) as recherche:
    debut = repere()

    for i in range(100):
        appeler_avec_taches(f"global{i}@exemple.test", reinitialiser=(i == 0))

    check("[V] plafond global : 100 demandes traitees (100 recherches Notion)", recherche.call_count == 100)
    code, corps, bt = appeler_avec_taches("global-de-trop@exemple.test", reinitialiser=False)
    check("[V] plafond global : la 101e est filtree en silence (200 generique, aucune recherche)",
          (code, corps) == (200, GENERIQUE) and recherche.call_count == 100)
    check("[V] plafond global : raison journalisee limite_globale", "demande filtree raison=limite_globale" in texte(logs_depuis(debut)))

    h.t += 900
    appeler_avec_taches("global-de-trop@exemple.test", reinitialiser=False)
    check("[V] plafond global : reprise apres 15 minutes", recherche.call_count == 101)


print("\n" + "=" * 80)
print("TEST 10/12 : echec d'envoi en tache de fond - sans fuite, sans alerte coach, sans exception")
print("=" * 80)

for libelle, erreur in (("RuntimeError (payload JSON)", RuntimeError(VARIANTES_ENVOI["payload JSON"])),
                        ("RuntimeError (URL complete)", RuntimeError(VARIANTES_ENVOI["URL complete"])),
                        ("ValueError inattendue", ValueError(f"bug {URL_N8N} {SAISI}"))):
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
         patch.object(ns, "send_portal_invite", side_effect=erreur), \
         patch.object(ns, "alerter_coach_onboarding") as alerte:
        debut = repere()
        code, corps, bt = appeler_avec_taches()
        check(f"[T] {libelle} : la reponse 200 generique est deja partie, l'echec n'a pas encore eu lieu",
              (code, corps) == (200, GENERIQUE) and not erreurs(logs_depuis(debut)))

        sortie = "aucune exception" if executer(bt) is None else "exception"

        t = texte(logs_depuis(debut))
        check(f"[T] {libelle} : la tache de fond ne laisse sortir aucune exception", sortie == "aucune exception")
        check(f"[T] {libelle} : un seul log error, contexte=envoi_lien", len(erreurs(logs_depuis(debut))) == 1 and "contexte=envoi_lien" in t)
        check(f"[T] {libelle} : log sans fuite (URL, email, token, secret, payload)", not fuites_logs(t))
        check(f"[T] {libelle} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))
        check(f"[T] {libelle} : aucune alerte coach", alerte.call_count == 0)

check("[T] la fonction de tache de fond ne renvoie rien",
      portal_main._envoyer_lien_en_arriere_plan.__annotations__.get("return") is None)


print("\n" + "=" * 80)
print("TEST 11/12 : non-regression P1-D (503 Notion, message generique, signature de la route)")
print("=" * 80)

import inspect

check("[P1-D] message generique 503 inchange", portal_main._MESSAGE_LIEN_INDISPONIBLE == MESSAGE_503)

with environnement(), patch.object(ns, "find_client_by_email", side_effect=RuntimeError(VARIANTES_RECHERCHE["URL complete"])) as recherche:
    code, detail, bt = appeler_avec_taches()
    check("[P1-D] panne de recherche Notion : 503 generique exact", (code, detail) == (503, MESSAGE_503))
    check("[P1-D] panne de recherche : aucune tache d'envoi planifiee", len(bt.tasks) == 0)

    code2, corps2, bt2 = appeler_avec_taches(reinitialiser=False)
    check("[P1-E] comportement documente : la demande en echec est comptee, un renvoi immediat est filtre en silence",
          (code2, corps2) == (200, GENERIQUE) and recherche.call_count == 1)

parametres = list(inspect.signature(portal_main.portal_request_link).parameters)
check("[P1-D] la route recoit request et background_tasks", parametres == ["request", "background_tasks"])
check("[P1-D] background_tasks est annote BackgroundTasks (injection FastAPI)",
      inspect.signature(portal_main.portal_request_link).parameters["background_tasks"].annotation is BackgroundTasks)


print("\n" + "=" * 80)
print("TEST 12/12 : confidentialite globale des logs et format")
print("=" * 80)

tout = texte(capture.records)
check("[F] aucun log ne contient de donnee sensible",
      not fuites_logs(tout) and "[request-link]" in tout)
check("[F] aucune trace d'exception ni exc_info dans l'ensemble des logs", all(r.exc_info is None for r in capture.records))
check("[F] seule la reference email masquee apparait (ref_email=m***@exemple.test#xxxxxxxx)",
      "ref_email=m***@exemple.test#" in tout)
toutes_lignes = [r.getMessage() for r in capture.records if "[request-link]" in r.getMessage()]
lignes = [l for l in toutes_lignes if l.startswith("[request-link] echec")]
filtrees = [l for l in toutes_lignes if not l.startswith("[request-link] echec")]
check("[F] les logs de filtrage ont le format [request-link] demande filtree raison=... ref_email=... (rien d'autre)",
      bool(filtrees) and all(re.fullmatch(r"\[request-link\] demande filtree raison=(cooldown|limite_email|limite_globale) ref_email=\S+", l) for l in filtrees))
check("[F] chaque log a le format [request-link] echec contexte=... ref_email=... erreur=...: ...",
      bool(lignes) and all(l.startswith("[request-link] echec contexte=") and " ref_email=" in l and " erreur=" in l for l in lignes))
check("[F] contextes limites a recherche_client / envoi_lien",
      all(any(f"contexte={c} " in l for c in ("recherche_client", "envoi_lien")) for l in lignes))
check("[F] chaque detail nettoye est limite a 300 caracteres", all(len(l.split(": ", 1)[-1]) <= 300 + 40 for l in lignes))


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
