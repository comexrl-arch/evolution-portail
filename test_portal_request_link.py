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
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from pydantic import ValidationError
from fastapi import HTTPException

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service

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


def appeler(email=SAISI):
    # Renvoie (code HTTP, corps ou detail).
    try:
        return 200, portal_main.portal_request_link(portal_main.PortalLoginRequest(email=email))
    except HTTPException as error:
        return error.status_code, error.detail


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


def verifier_echec(libelle, code, detail, debut, contexte):
    t = texte(logs_depuis(debut))
    ecrits = erreurs(logs_depuis(debut))
    check(f"{libelle} : 503", code == 503)
    check(f"{libelle} : detail exactement egal au message generique", detail == MESSAGE_503)
    check(f"{libelle} : aucune fuite dans la reponse HTTP ({', '.join(fuites_reponse(detail)) or 'aucune'})", not fuites_reponse(detail))
    check(f"{libelle} : un log error, contexte={contexte}", len(ecrits) == 1 and f"contexte={contexte}" in ecrits[0].getMessage())
    check(f"{libelle} : le log contient ref_email masquee et la classe de l'erreur",
          "ref_email=m***@exemple.test#" in t and "RuntimeError" in t)
    check(f"{libelle} : aucune fuite dans les logs ({', '.join(fuites_logs(t)) or 'aucune'})", not fuites_logs(t))
    check(f"{libelle} : aucune trace d'exception (exc_info)", all(r.exc_info is None for r in logs_depuis(debut)))


# --- Tests ---------------------------------------------------------------------------

print("=" * 80)
print("TEST 1/8 : client connu, envoi reussi - comportement actuel preserve")
print("=" * 80)

with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT) as recherche, \
     patch.object(ns, "send_portal_invite", return_value=None) as envoi:
    debut = repere()
    code, corps = appeler()
    check("[A] reponse 200 identique a l'actuelle", code == 200 and corps == GENERIQUE)
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
    check("[A] duree de validite inchangee (15 minutes)", portal_auth_service.MAGIC_LINK_MAX_AGE == 15 * 60)
    check("[A] aucun log warning/error", not any(r.levelno >= logging.WARNING for r in logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 2/8 : email inconnu - 200 generique, aucun envoi, aucun log error")
print("=" * 80)

with environnement(), patch.object(ns, "find_client_by_email", return_value=None), \
     patch.object(ns, "send_portal_invite") as envoi:
    debut = repere()
    code, corps = appeler("inconnu@exemple.test")
    check("[B] reponse 200 generique identique", code == 200 and corps == GENERIQUE)
    check("[B] aucun envoi", envoi.call_count == 0)
    check("[B] aucun log error inutile", not erreurs(logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 3/8 : echec de la recherche client (RuntimeError) - 503 generique, log nettoye")
print("=" * 80)

for libelle, message in VARIANTES_RECHERCHE.items():
    with environnement(), patch.object(ns, "find_client_by_email", side_effect=RuntimeError(message)), \
         patch.object(ns, "send_portal_invite") as envoi:
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[C] recherche, {libelle}", code, detail, debut, "recherche_client")
        check(f"[C] recherche, {libelle} : aucun envoi tente", envoi.call_count == 0)


print("\n" + "=" * 80)
print("TEST 4/8 : echec de l'envoi du lien (RuntimeError) - 503 generique, log nettoye")
print("=" * 80)

for libelle, message in VARIANTES_ENVOI.items():
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
         patch.object(ns, "send_portal_invite", side_effect=RuntimeError(message)):
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[D] envoi, {libelle}", code, detail, debut, "envoi_lien")

# De bout en bout : vrai send_portal_invite, requests.post leve une vraie exception requests
for libelle, exception in (("HTTPError", erreur_http_requests()), ("ConnectionError", ERREUR_CONNEXION), ("Timeout", ERREUR_TIMEOUT)):
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT), \
         patch.object(requests, "post", side_effect=exception):
        debut = repere()
        code, detail = appeler()
        verifier_echec(f"[D] de bout en bout, {libelle} reel via send_portal_invite", code, detail, debut, "envoi_lien")

# De bout en bout cote recherche : vrai find_client_by_email, client HTTP de Notion en echec
with environnement(), patch.object(ns._http, "post", side_effect=ERREUR_CONNEXION):
    debut = repere()
    code, detail = appeler()
    verifier_echec("[C] de bout en bout, ConnectionError reel via find_client_by_email", code, detail, debut, "recherche_client")


print("\n" + "=" * 80)
print("TEST 5/8 : configuration absente - 503 generique, aucun nom de variable dans la reponse")
print("=" * 80)

with environnement(webhook=None), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
    debut = repere()
    code, detail = appeler()
    t = texte(logs_depuis(debut))
    check("[E] webhook n8n non configure : 503", code == 503)
    check("[E] detail exactement egal au message generique", detail == MESSAGE_503)
    check("[E] aucun nom de variable d'environnement dans la reponse", not fuites_reponse(detail))
    check("[E] le log reste utile (indique la configuration manquante)", "manquant" in t and "contexte=envoi_lien" in t)
    check("[E] le log ne contient aucune fuite", not fuites_logs(t))

cle_precedente = portal_auth_service.SECRET_KEY
portal_auth_service.SECRET_KEY = None

try:
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
        debut = repere()
        code, detail = appeler()
        check("[E] cle de signature absente : 503 generique", code == 503 and detail == MESSAGE_503)
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
print("TEST 6/8 : le helper de journalisation echoue - la reponse 503 generique est preservee")
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
        check(f"[G] {libelle}, echec de {chemin} : 503 et message generique inchanges", code == 503 and detail == MESSAGE_503)

try:
    retour = portal_main._journaliser_echec_lien("envoi_lien", RuntimeError("x"), None, None)
    helper_sur = retour is None
except Exception:
    helper_sur = False

check("[G] le helper accepte aussi des arguments inattendus (None) sans lever", helper_sur)


print("\n" + "=" * 80)
print("TEST 7/8 : exceptions autres que RuntimeError - comportement inchange, validation 422 inchangee")
print("=" * 80)

for chemin, cible, exception in (
    ("recherche", "find_client_by_email", KeyError("bug interne")),
    ("envoi", "send_portal_invite", ValueError("bug interne")),
):
    with environnement(), patch.object(ns, "find_client_by_email", return_value=PAGE_CLIENT):
        with patch.object(ns, cible, side_effect=exception):
            debut = repere()

            try:
                appeler()
                resultat = "aucune exception"
            except HTTPException as error:
                resultat = f"HTTP {error.status_code}"
            except Exception as error:
                resultat = f"{type(error).__name__} propagee"

        check(f"[H] {chemin} : {type(exception).__name__} propagee telle quelle (ni 503 ni message generique)",
              resultat == f"{type(exception).__name__} propagee")
        check(f"[H] {chemin} : aucun log du helper pour cette exception", not erreurs(logs_depuis(debut)))

try:
    portal_main.PortalLoginRequest()
    validation = "aucune erreur"
except ValidationError:
    validation = "ValidationError"

check("[H] la validation d'entree (email obligatoire) est inchangee : erreur de validation (422 cote FastAPI)",
      validation == "ValidationError")


print("\n" + "=" * 80)
print("TEST 8/8 : confidentialite globale des logs et format")
print("=" * 80)

tout = texte(capture.records)
check("[F] aucun log ne contient de donnee sensible",
      not fuites_logs(tout) and "[request-link]" in tout)
check("[F] aucune trace d'exception ni exc_info dans l'ensemble des logs", all(r.exc_info is None for r in capture.records))
check("[F] seule la reference email masquee apparait (ref_email=m***@exemple.test#xxxxxxxx)",
      "ref_email=m***@exemple.test#" in tout)
lignes = [r.getMessage() for r in capture.records if "[request-link]" in r.getMessage()]
check("[F] chaque log a le format [request-link] echec contexte=... ref_email=... erreur=...: ...",
      bool(lignes) and all(l.startswith("[request-link] echec contexte=") and " ref_email=" in l and " erreur=" in l for l in lignes))
check("[F] contextes limites a recherche_client / envoi_lien",
      all(any(f"contexte={c} " in l for c in ("recherche_client", "envoi_lien")) for l in lignes))
check("[F] chaque detail nettoye est limite a 300 caracteres", all(len(l.split(": ", 1)[-1]) <= 300 + 40 for l in lignes))


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
