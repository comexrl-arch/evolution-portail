# Tests de POST /webhooks/docuseal : observabilite et alertes d'onboarding.
#
# Entierement mockes (aucun appel reseau reel vers DocuSeal, Notion ou n8n) :
# la fonction de route est appelee directement avec un BackgroundTasks fabrique
# par le test, dont les taches sont executees a la main. requests.post est
# remplace par un garde qui echoue sur tout appel non prevu. Toutes les valeurs
# (secrets, emails, URL, noms, telephone) sont fictives. Meme style que
# test_onboarding.py (script simple, pas de framework de test, aucune
# dependance supplementaire).
#
# Lancer : python test_docuseal_webhook.py

import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from fastapi import BackgroundTasks, HTTPException

import portal_main
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


# --- Valeurs fictives ------------------------------------------------------------

SECRET = "secret-factice-test"
MAUVAIS_SECRET = "mauvais-secret-factice"
EMAIL = "jean.dupont@exemple.test"
EMAIL_MASQUE = "j***@exemple.test"
NOM = "Jean Dupont"
TEL = "+590690123456"
HOTE = "n8n.exemple.test"
URL_N8N = f"https://{HOTE}/webhook/abc123"
URL_NOTION = "https://api.notion.com/v1/data_sources/xyz/query"
TEMPLATE_COACHING = next(k for k, v in portal_main._DOCUSEAL_PARCOURS.items() if v == "Coaching 90 jours")
TEMPLATE_INCONNU = "999999"


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


def niveaux(records):
    return [r.levelname for r in records]


# --- Outils de test ----------------------------------------------------------------

@contextmanager
def environnement(secret=SECRET, alerte=URL_N8N):
    # Isole les variables utilisees : aucune valeur reelle du poste n'est lue.
    with patch.dict(os.environ, {}, clear=False):
        for cle in ("DOCUSEAL_WEBHOOK_SECRET", "N8N_WEBHOOK_COACH_ALERT"):
            os.environ.pop(cle, None)

        if secret:
            os.environ["DOCUSEAL_WEBHOOK_SECRET"] = secret

        if alerte:
            os.environ["N8N_WEBHOOK_COACH_ALERT"] = alerte

        yield


def garde_reseau(*args, **kwargs):
    raise AssertionError("appel reseau reel interdit dans ces tests")


def payload(event="form.completed", template=TEMPLATE_COACHING, email=EMAIL, avec_email=True, nom=NOM):
    data = {"name": nom, "phone": TEL, "template": {"id": template}, "values": []}

    if avec_email:
        data["email"] = email

    return {"event_type": event, "data": data}


def appeler(donnees, secret=SECRET):
    bt = BackgroundTasks()
    reponse = portal_main.webhook_docuseal(donnees, bt, x_webhook_secret=secret)
    return reponse, bt


def executer(bt):
    for tache in bt.tasks:
        tache.func(*tache.args, **tache.kwargs)


def refus(donnees, secret):
    # Renvoie (code, detail, BackgroundTasks) pour un appel refuse.
    bt = BackgroundTasks()

    try:
        portal_main.webhook_docuseal(donnees, bt, x_webhook_secret=secret)
    except HTTPException as error:
        return error.status_code, error.detail, bt

    return None, None, bt


RESULTAT_OK = {"client_id": "page-1", "fiches_creees": 22, "kpi_crees": 4, "invite_envoyee": True, "invite_erreur": None}


# --- Tests -------------------------------------------------------------------------

print("=" * 80)
print("TEST 1/11 : succes - onboarding appele en tache de fond, log info, aucune alerte")
print("=" * 80)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client", return_value=RESULTAT_OK) as onboard, \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    reponse, bt = appeler(payload())
    check("reponse inchangee : accepte + parcours", reponse == {"status": "accepte", "parcours": "Coaching 90 jours"})
    check("une seule tache de fond planifiee", len(bt.tasks) == 1)
    check("l'onboarding n'est pas execute avant la reponse (asynchrone)", onboard.call_count == 0)

    executer(bt)
    check("onboard_client appele une fois avec les bons arguments",
          onboard.call_count == 1 and onboard.call_args == ((NOM, EMAIL), {
              "kpi_j0": {}, "parcours": "Coaching 90 jours", "telephone": TEL, "date_demarrage": ""}))
    nouveaux = logs_depuis(debut)
    check("un log info 'onboarding OK'", any(r.levelname == "INFO" and "onboarding OK" in r.getMessage() for r in nouveaux))
    check("aucun log warning/error", not any(r.levelname in ("WARNING", "ERROR") for r in nouveaux))
    check("aucune alerte coach", alerte.call_count == 0)


print("\n" + "=" * 80)
print("TEST 2/11 : invitation non envoyee - log error nettoye + alerte sans detail technique")
print("=" * 80)

erreur_invite = (
    f"Erreur envoi invitation portail : 500 Server Error: Internal Server Error for url: {URL_N8N} "
    f"(client {EMAIL}, {NOM})"
)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client", return_value={**RESULTAT_OK, "invite_envoyee": False, "invite_erreur": erreur_invite}), \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    reponse, bt = appeler(payload())
    check("reponse inchangee", reponse == {"status": "accepte", "parcours": "Coaching 90 jours"})
    executer(bt)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("un log error 'lien d'acces non envoye'",
          any(r.levelname == "ERROR" and "lien d'acces non envoye" in r.getMessage() for r in nouveaux))
    check("le log ne contient ni URL, ni email, ni nom", URL_N8N not in t and HOTE not in t and EMAIL not in t and NOM not in t)
    check("le log contient le texte nettoye", "<url>" in t and "<masque>" in t)
    check("une alerte coach envoyee", alerte.call_count == 1)
    sujet, message = alerte.call_args[0]
    check("l'alerte annonce le lien non envoye", "lien d'accès non envoyé" in sujet)
    check("l'alerte contient le nom et l'email (destinee au coach)", NOM in message and EMAIL in message)
    check("l'alerte contient la cause technique generique", "Cause technique : lien d'accès non envoyé." in message)
    check("l'alerte ne contient aucun detail technique",
          URL_N8N not in message and HOTE not in message and "500" not in message
          and "Server Error" not in message and "url" not in message.lower())


print("\n" + "=" * 80)
print("TEST 3/11 : echec d'onboarding - log error nettoye + alerte sans detail technique")
print("=" * 80)

erreur_onboarding = RuntimeError(
    f"Onboarding de {NOM} echoue (Erreur Notion (query) : 500 Server Error for url: {URL_NOTION} "
    f"pour {EMAIL}). Rollback partiel : 1 page(s) restent orphelines : ['page-orpheline']."
)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding), \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    reponse, bt = appeler(payload())
    check("reponse inchangee", reponse == {"status": "accepte", "parcours": "Coaching 90 jours"})
    executer(bt)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("un log error 'onboarding echoue' avec la classe de l'erreur",
          any(r.levelname == "ERROR" and "onboarding echoue" in r.getMessage() and "RuntimeError" in r.getMessage() for r in nouveaux))
    check("le log ne contient ni URL, ni email, ni nom", URL_NOTION not in t and "api.notion.com" not in t and EMAIL not in t and NOM not in t)
    check("le log est nettoye (placeholders)", "<url>" in t and "<masque>" in t)
    check("aucune trace d'exception dans les logs", all(r.exc_info is None for r in nouveaux))
    check("une alerte coach envoyee", alerte.call_count == 1)
    sujet, message = alerte.call_args[0]
    check("l'alerte annonce l'echec d'onboarding", "échoué" in sujet)
    check("l'alerte contient le nom et l'email (destinee au coach)", NOM in message and EMAIL in message)
    check("l'alerte contient la cause technique generique", "Cause technique : création automatique interrompue." in message)
    check("l'alerte ne contient aucun detail technique",
          "RuntimeError" not in message and "Notion" not in message and "https" not in message
          and "500" not in message and "Rollback" not in message and "orpheline" not in message)


print("\n" + "=" * 80)
print("TEST 4/11 : doublon - warning, aucune alerte, message actuel preserve")
print("=" * 80)

MESSAGE_DOUBLON_ACTUEL = (
    f"Un client existe deja avec l'email {EMAIL} "
    "(page Notion existing-123). Onboarding annule pour eviter un doublon."
)

with patch.object(ns, "find_client_by_email", return_value={"id": "existing-123"}):
    try:
        ns.onboard_client(NOM, EMAIL)
        erreur = None
    except RuntimeError as error:
        erreur = error

check("onboard_client leve toujours une RuntimeError", erreur is not None)
check("... de type ClientDejaExistant", isinstance(erreur, ns.ClientDejaExistant))
check("le message de doublon est strictement identique a l'actuel", erreur is not None and str(erreur) == MESSAGE_DOUBLON_ACTUEL)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "find_client_by_email", return_value={"id": "existing-123"}), \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    reponse, bt = appeler(payload())
    check("reponse inchangee", reponse == {"status": "accepte", "parcours": "Coaching 90 jours"})
    executer(bt)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("un warning 'client deja existant'",
          any(r.levelname == "WARNING" and "client deja existant" in r.getMessage() for r in nouveaux))
    check("aucun log error", "ERROR" not in niveaux(nouveaux))
    check("aucune alerte coach", alerte.call_count == 0)
    check("le log ne contient ni email, ni nom, ni id de page", EMAIL not in t and NOM not in t and "existing-123" not in t)


print("\n" + "=" * 80)
print("TEST 5/11 : form.completed non reconnu - warning + alerte avec email masque seulement")
print("=" * 80)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client") as onboard, \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    # (a) template inconnu, email present
    debut = repere()
    reponse, bt = appeler(payload(template=TEMPLATE_INCONNU))
    check("(a) reponse inchangee : ignore", reponse == {"status": "ignore"})
    check("(a) signalement planifie en tache de fond (asynchrone)", len(bt.tasks) == 1 and alerte.call_count == 0)
    executer(bt)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("(a) un warning 'contrat signe non reconnu' avec le template et la raison",
          any(r.levelname == "WARNING" and "non reconnu" in r.getMessage() and TEMPLATE_INCONNU in r.getMessage()
              and "template_inconnu" in r.getMessage() for r in nouveaux))
    check("(a) le log ne contient ni email ni nom ni telephone", EMAIL not in t and NOM not in t and TEL not in t)
    check("(a) une alerte coach", alerte.call_count == 1)
    sujet, message = alerte.call_args[0]
    check("(a) l'alerte contient evenement, template, raison", "form.completed" in message
          and TEMPLATE_INCONNU in message and "template_inconnu" in message)
    check("(a) l'alerte contient l'email masque", EMAIL_MASQUE in message)
    check("(a) l'alerte ne contient ni email en clair, ni nom, ni telephone", EMAIL not in message and NOM not in message
          and "Dupont" not in message and TEL not in message)
    check("(a) onboard_client non appele", onboard.call_count == 0)

    # (b) template connu mais email absent
    alerte.reset_mock()
    debut = repere()
    reponse, bt = appeler(payload(avec_email=False))
    check("(b) reponse inchangee : ignore", reponse == {"status": "ignore"})
    executer(bt)
    check("(b) un warning avec la raison email_absent",
          any(r.levelname == "WARNING" and "email_absent" in r.getMessage() and "sans-email" in r.getMessage()
              for r in logs_depuis(debut)))
    sujet, message = alerte.call_args[0]
    check("(b) l'alerte indique 'sans-email' et la raison", "sans-email" in message and "email_absent" in message)
    check("(b) l'alerte ne contient ni nom ni telephone", NOM not in message and TEL not in message)

    # (c) valeur hostile dans le payload : jamais injectee telle quelle
    alerte.reset_mock()
    debut = repere()
    hostile = "A" * 100 + "\nFAUX-LOG niveau=ERROR"
    reponse, bt = appeler(payload(template=hostile))
    executer(bt)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    sujet, message = alerte.call_args[0]
    check("(c) template tronque a 40 caracteres dans le log", "A" * 40 in t and "A" * 41 not in t)
    check("(c) template tronque a 40 caracteres dans l'alerte", "A" * 40 in message and "A" * 41 not in message)
    check("(c) aucun retour a la ligne injecte dans le log", all("\n" not in r.getMessage() for r in nouveaux))
    check("(c) aucun retour a la ligne injecte via le template dans l'alerte", "FAUX-LOG" not in message)

    # (d) event_type hostile reste neutralise
    alerte.reset_mock()
    reponse, bt = appeler({"event_type": "form.completed", "data": {"email": EMAIL, "template": {"id": "7\nINJECT"}}})
    executer(bt)
    sujet, message = alerte.call_args[0]
    check("(d) template avec retour a la ligne neutralise", "INJECT" in message and "7\nINJECT" not in message)


print("\n" + "=" * 80)
print("TEST 6/11 : evenement autre que form.completed - ignore, sans alerte")
print("=" * 80)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client") as onboard, \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    reponse, bt = appeler(payload(event="form.viewed"))
    check("reponse inchangee : ignore", reponse == {"status": "ignore"})
    check("aucune tache de fond planifiee", len(bt.tasks) == 0)
    executer(bt)
    check("aucune alerte coach", alerte.call_count == 0)
    check("onboard_client non appele", onboard.call_count == 0)
    check("aucun warning/error", not any(r.levelname in ("WARNING", "ERROR") for r in logs_depuis(debut)))


print("\n" + "=" * 80)
print("TEST 7/11 : secret invalide - 401, warning sans secret, aucun onboarding ni alerte")
print("=" * 80)

with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client") as onboard, \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    code, detail, bt = refus(payload(), MAUVAIS_SECRET)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("401 renvoye", code == 401)
    check("detail inchange", detail == "Secret invalide.")
    check("un warning 'secret invalide'", any(r.levelname == "WARNING" and "secret invalide" in r.getMessage() for r in nouveaux))
    check("aucun des deux secrets dans les logs", SECRET not in t and MAUVAIS_SECRET not in t)
    check("aucune tache de fond, aucun onboarding", len(bt.tasks) == 0 and onboard.call_count == 0)
    check("aucune alerte coach", alerte.call_count == 0)

    code, detail, bt = refus(payload(), "")
    check("en-tete absent : 401 aussi", code == 401)


print("\n" + "=" * 80)
print("TEST 8/11 : secret absent - 503, error sans secret, aucun onboarding ni alerte")
print("=" * 80)

with environnement(secret=None), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client") as onboard, \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    code, detail, bt = refus(payload(), MAUVAIS_SECRET)
    nouveaux = logs_depuis(debut)
    t = texte(nouveaux)
    check("503 renvoye", code == 503)
    check("detail = message generique, sans nom de variable",
          detail == "Le service est momentanément indisponible. Réessayez dans quelques minutes."
          and "DOCUSEAL" not in str(detail))
    check("un log error 'secret serveur non configure'",
          any(r.levelname == "ERROR" and "non configure" in r.getMessage() for r in nouveaux))
    check("aucun secret dans les logs", SECRET not in t and MAUVAIS_SECRET not in t)
    check("aucune tache de fond, aucun onboarding", len(bt.tasks) == 0 and onboard.call_count == 0)
    check("aucune alerte coach", alerte.call_count == 0)


print("\n" + "=" * 80)
print("TEST 9/11 : echec de l'alerte - ne sort jamais de la tache, sans URL ni hote dans les logs")
print("=" * 80)

erreur_onboarding_simple = RuntimeError("boom")

# (a) vraie fonction d'alerte, erreur reseau de type ConnectionError (hote + chemin dans le texte)
fausse_erreur_reseau = requests.ConnectionError(
    f"HTTPSConnectionPool(host='{HOTE}', port=443): Max retries exceeded with url: /webhook/abc123 (Caused by None)"
)

with environnement(), patch.object(requests, "post", side_effect=fausse_erreur_reseau), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    debut = repere()
    _, bt = appeler(payload())

    try:
        executer(bt)
        propagee = False
    except Exception:
        propagee = True

    t = texte(logs_depuis(debut))
    check("(a) aucune exception ne sort de la tache de fond", not propagee)
    check("(a) le log d'echec d'alerte ne contient que la classe", "ConnectionError" in t)
    check("(a) ni hote, ni chemin, ni URL n8n dans les logs", HOTE not in t and "/webhook" not in t and URL_N8N not in t
          and "Max retries" not in t and "host=" not in t.replace("host=<hote>", ""))

# (b) timeout reseau : seule la classe est journalisee
with environnement(), patch.object(requests, "post", side_effect=requests.Timeout(f"timeout vers {URL_N8N}")), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    debut = repere()
    _, bt = appeler(payload())
    executer(bt)
    t = texte(logs_depuis(debut))
    check("(b) Timeout : classe journalisee, jamais l'URL", "Timeout" in t and URL_N8N not in t and HOTE not in t)

# (c) reponse HTTP en erreur de n8n (raise_for_status)
reponse_500 = requests.Response()
reponse_500.status_code = 500
reponse_500.reason = "Internal Server Error"
reponse_500.url = URL_N8N

with environnement(), patch.object(requests, "post", return_value=reponse_500), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    debut = repere()
    _, bt = appeler(payload())
    executer(bt)
    t = texte(logs_depuis(debut))
    check("(c) HTTPError : classe journalisee, jamais l'URL ni le statut detaille",
          "HTTPError" in t and URL_N8N not in t and HOTE not in t and "Server Error" not in t)

# (d) variable d'alerte absente : warning generique, aucun appel reseau
with environnement(alerte=None), patch.object(requests, "post", side_effect=garde_reseau) as post, \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    debut = repere()
    _, bt = appeler(payload())
    executer(bt)
    nouveaux = logs_depuis(debut)
    check("(d) warning 'N8N_WEBHOOK_COACH_ALERT manquant', aucun appel reseau",
          any("N8N_WEBHOOK_COACH_ALERT manquant" in r.getMessage() for r in nouveaux) and post.call_count == 0)

# (e) bug inattendu dans l'alerte : capture par _docuseal_alerter, classe seule journalisee
with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple), \
     patch.object(ns, "alerter_coach_onboarding", side_effect=KeyError(f"{URL_N8N} {EMAIL}")):
    debut = repere()
    _, bt = appeler(payload())

    try:
        executer(bt)
        propagee = False
    except Exception:
        propagee = True

    t = texte(logs_depuis(debut))
    check("(e) KeyError de l'alerte : aucune exception ne sort de la tache", not propagee)
    check("(e) seule la classe est journalisee", "KeyError" in t and URL_N8N not in t and EMAIL not in t and HOTE not in t)

# (f) erreur non reseau dans requests.post : propagee par l'alerte, capturee par _docuseal_alerter
with environnement(), patch.object(requests, "post", side_effect=ValueError(f"mauvais {URL_N8N}")), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    debut = repere()
    _, bt = appeler(payload())

    try:
        executer(bt)
        propagee = False
    except Exception:
        propagee = True

    t = texte(logs_depuis(debut))
    check("(f) ValueError : aucune exception ne sort de la tache", not propagee)
    check("(f) seule la classe est journalisee", "ValueError" in t and URL_N8N not in t and HOTE not in t)

# (g) contenu reellement envoye a n8n (appel simule)
envoi = MagicMock(return_value=MagicMock(raise_for_status=MagicMock()))

with environnement(), patch.object(requests, "post", envoi), \
     patch.object(ns, "onboard_client", side_effect=erreur_onboarding_simple):
    _, bt = appeler(payload())
    executer(bt)
    appel = envoi.call_args
    corps = appel.kwargs.get("json", {}) if appel else {}
    check("(g) un seul envoi simule vers l'URL d'alerte configuree", envoi.call_count == 1 and appel.args[0] == URL_N8N)
    check("(g) timeout de 15 s", appel.kwargs.get("timeout") == 15)
    check("(g) champs event/subject/message/coach_url", set(corps) == {"event", "subject", "message", "coach_url"})
    check("(g) evenement dedie", corps.get("event") == "onboarding_docuseal_echec")
    check("(g) l'alerte ne contient pas la cause technique brute", "boom" not in corps.get("message", "")
          and "RuntimeError" not in corps.get("message", ""))


print("\n" + "=" * 80)
print("TEST 10/11 : confidentialite renforcee - nom court, telephone, url: /chemin, payload serialise")
print("=" * 80)

CHEMIN_PRIVE = "/webhook/chemin-prive"
PAYLOAD_DOCUSEAL = {
    "event_type": "form.completed",
    "data": {
        "email": EMAIL, "name": NOM, "phone": TEL,
        "template": {"id": TEMPLATE_COACHING},
        "values": [{"field": "Nom", "value": NOM}, {"field": "Telephone", "value": TEL}],
    },
}
PAYLOAD_REPR = str(PAYLOAD_DOCUSEAL)
PAYLOAD_JSON = json.dumps(PAYLOAD_DOCUSEAL)
PAYLOAD_TRONQUE = PAYLOAD_REPR[:120]  # accolade fermante absente
CLES_PAYLOAD = ("event_type", "form.completed", "'data'", '"data"', "values", TEMPLATE_COACHING)


def mot(nom, texte_):
    # Le nom apparait-il comme mot entier (insensible a la casse) ?
    return re.search(rf"(?<!\w){re.escape(nom)}(?![\w'’])", texte_, flags=re.IGNORECASE) is not None


nettoyer = portal_main._nettoyer_erreur

# --- A. noms courts (unitaire) ---
resultat = nettoyer("Onboarding de Li echoue (client Li, contact LI, li)", {"nom": "Li"})
check("[A] nom de 2 caracteres masque (toutes casses, plusieurs occurrences)", not mot("Li", resultat) and resultat.count("<masque>") == 4)
resultat = nettoyer("livraison Lisbonne Lilas et Li", {"nom": "Li"})
check("[A] 2 car. : « livraison », « Lisbonne », « Lilas » intacts", all(m in resultat for m in ("livraison", "Lisbonne", "Lilas")))
check("[A] 2 car. : seule l'identite isolee est masquee", resultat.endswith("et <masque>"))
resultat = nettoyer("Onboarding de X echoue (client X). Box, exemple, taxe", {"nom": "X"})
check("[A] nom de 1 caractere masque", not mot("X", resultat) and resultat.count("<masque>") == 2)
check("[A] 1 car. : lettres dans les mots ordinaires intactes", all(m in resultat for m in ("Box", "exemple", "taxe")))
resultat = nettoyer("Client L : livraison L'entreprise (L)", {"nom": "L"})
check("[A] « L » isole masque", resultat.startswith("Client <masque> :") and resultat.endswith("(<masque>)"))
check("[A] « livraison » et l'elision « L'entreprise » intactes", "livraison" in resultat and "L'entreprise" in resultat)
check("[A] nom absent : aucun masquage parasite", nettoyer("Onboarding de Li echoue", {"nom": ""}) == "Onboarding de Li echoue")

# --- B. telephone ---
resultat = nettoyer(f"Echec de l'appel pour {TEL} (contact)", {"telephone": TEL})
check("[B] telephone masque (valeur complete et chiffres)", TEL not in resultat and TEL.lstrip("+") not in resultat)

# --- C. format requests sans schema : url: /chemin ---
resultat = nettoyer(f"Max retries exceeded with url: {CHEMIN_PRIVE} (Caused by None)")
check("[C] chemin prive absent apres nettoyage", "chemin-prive" not in resultat and "/webhook" not in resultat)
resultat = nettoyer(f"Max retries exceeded with URL: {CHEMIN_PRIVE}")
check("[C] idem avec « URL: » en majuscules", "chemin-prive" not in resultat)

# --- D. payload serialise (repr, JSON, tronque), avec et sans infos ---
infos_client = {"email": EMAIL, "nom": NOM, "telephone": TEL}
for libelle, brut in (("repr", PAYLOAD_REPR), ("JSON", PAYLOAD_JSON), ("tronque", PAYLOAD_TRONQUE)):
    for avec_infos in (True, False):
        resultat = nettoyer(f"Erreur Notion avec payload {brut}", infos_client if avec_infos else None)
        sans_cle = not any(c in resultat for c in CLES_PAYLOAD)
        sans_identite = EMAIL not in resultat and TEL not in resultat and NOM not in resultat and "Dupont" not in resultat
        check(f"[D] payload {libelle} ({'avec' if avec_infos else 'sans'} infos) : aucune cle ni identite", sans_cle and sans_identite)

# --- A-D de bout en bout : webhook, tache de fond, logs Render ---
def echec_bout_en_bout(nom_client, message_erreur):
    with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
         patch.object(ns, "onboard_client", side_effect=RuntimeError(message_erreur)), \
         patch.object(ns, "alerter_coach_onboarding") as alerte:
        debut = repere()
        _, bt = appeler(payload(nom=nom_client))
        executer(bt)
        return texte(logs_depuis(debut)), alerte


for nom_court in ("Li", "X"):
    message = (
        f"Onboarding de {nom_court} echoue (client {nom_court}) : Max retries exceeded with url: {CHEMIN_PRIVE} "
        f"- tel {TEL} - payload {PAYLOAD_REPR} - json {PAYLOAD_JSON}"
    )
    t, alerte = echec_bout_en_bout(nom_court, message)
    check(f"[E2E] nom « {nom_court} » ({len(nom_court)} car.) : absent des logs Render", not mot(nom_court, t))
    check(f"[E2E] {nom_court} : telephone absent des logs", TEL not in t and TEL.lstrip("+") not in t)
    check(f"[E2E] {nom_court} : chemin url: absent des logs", "chemin-prive" not in t and "/webhook" not in t)
    check(f"[E2E] {nom_court} : payload serialise absent des logs (cles, email, nom, telephone, template)",
          not any(c in t for c in CLES_PAYLOAD) and EMAIL not in t and NOM not in t)
    check(f"[E2E] {nom_court} : le log d'erreur est bien produit et nettoye", "onboarding echoue" in t and "<masque>" in t and "<donnees>" in t)
    sujet, message_alerte = alerte.call_args[0]
    check(f"[E2E] {nom_court} : l'alerte coach n'a aucun detail technique",
          "chemin-prive" not in message_alerte and TEL not in message_alerte and "event_type" not in message_alerte
          and "Max retries" not in message_alerte and "Cause technique : création automatique interrompue." in message_alerte)

# invitation non envoyee avec les memes valeurs injectees
with environnement(), patch.object(requests, "post", side_effect=garde_reseau), \
     patch.object(ns, "onboard_client", return_value={**RESULTAT_OK, "invite_envoyee": False,
                   "invite_erreur": f"Erreur pour Li, url: {CHEMIN_PRIVE}, tel {TEL}, payload {PAYLOAD_JSON}"}), \
     patch.object(ns, "alerter_coach_onboarding") as alerte:
    debut = repere()
    _, bt = appeler(payload(nom="Li"))
    executer(bt)
    t = texte(logs_depuis(debut))
    check("[E2E] invitation non envoyee : nom court, telephone, chemin et payload absents des logs",
          not mot("Li", t) and TEL not in t and "chemin-prive" not in t and not any(c in t for c in CLES_PAYLOAD))
    check("[E2E] invitation non envoyee : alerte coach sans detail technique",
          "chemin-prive" not in alerte.call_args[0][1] and TEL not in alerte.call_args[0][1])


print("\n" + "=" * 80)
print("TEST 11/11 : masquage des accolades - structure fermee, imbriquee, multiple, non fermee, performance")
print("=" * 80)

SUFFIXE = "-- fin de message utile"

# --- A. JSON ferme : payload masque, texte utile conserve ---
for avec_infos in (True, False):
    etiquette = "avec" if avec_infos else "sans"
    resultat = nettoyer(f"Erreur Notion, payload recu : {PAYLOAD_JSON} {SUFFIXE}", infos_client if avec_infos else None)
    check(f"[A] JSON ferme ({etiquette} infos) : payload -> <donnees>, suite conservee (resultat exact)",
          resultat == f"Erreur Notion, payload recu : <donnees> {SUFFIXE}")
    check(f"[A] JSON ferme ({etiquette} infos) : ni email, ni telephone, ni template, ni nom, ni cle",
          not any(c in resultat for c in (EMAIL, TEL, TEMPLATE_COACHING, NOM, "Dupont", "event_type", "values")))

# --- B. dictionnaire Python ferme ---
for avec_infos in (True, False):
    etiquette = "avec" if avec_infos else "sans"
    resultat = nettoyer(f"Erreur Notion, payload recu : {PAYLOAD_REPR} {SUFFIXE}", infos_client if avec_infos else None)
    check(f"[B] dict Python ferme ({etiquette} infos) : payload -> <donnees>, suite conservee (resultat exact)",
          resultat == f"Erreur Notion, payload recu : <donnees> {SUFFIXE}")
    check(f"[B] dict Python ferme ({etiquette} infos) : ni email, ni telephone, ni template, ni nom, ni cle",
          not any(c in resultat for c in (EMAIL, TEL, TEMPLATE_COACHING, NOM, "Dupont", "event_type", "values")))

# --- C. structures imbriquees : masquees entierement, avant et apres conserves ---
imbriquee = f"avant {{niveau1: {{niveau2: {{email: {EMAIL}}}, tel: {TEL}}}, nom: {NOM}}} apres"
resultat = nettoyer(imbriquee, None)
check("[C] structure imbriquee (3 niveaux) : remplacee entierement, avant/apres conserves (resultat exact)",
      resultat == "avant <donnees> apres")
check("[C] imbriquee : aucun fragment du contenu ne demeure",
      not any(c in resultat for c in ("niveau", "email", EMAIL, TEL, NOM, "{", "}")))
resultat = nettoyer("x {a: {b: {c: {d: {e: 1}}}}} y", None)
check("[C] imbrication a 5 niveaux : un seul <donnees>, texte autour conserve", resultat == "x <donnees> y")

# --- D. plusieurs structures separees ---
resultat = nettoyer("debut {a: 1} milieu {b: {c: 2}} fin utile", None)
check("[D] deux structures : les deux masquees, texte entre elles et apres conserve",
      resultat == "debut <donnees> milieu <donnees> fin utile")
resultat = nettoyer("{a} un {b} deux {c} trois", None)
check("[D] trois structures consecutives : texte intercalaire conserve", resultat == "<donnees> un <donnees> deux <donnees> trois")

# --- E. accolade non fermee : masque jusqu'a la fin ---
resultat = nettoyer("Erreur payload {'event_type': 'form.completed', 'email': '" + EMAIL + "' -- fin de message", None)
check("[E] accolade non fermee : de l'accolade a la fin -> <donnees>", resultat == "Erreur payload <donnees>")
resultat = nettoyer("ok {a} puis {b: debut non ferme -- fin", None)
check("[E] structure fermee + accolade non fermee : la premiere est masquee, la seconde masque la fin",
      resultat == "ok <donnees> puis <donnees>")
resultat = nettoyer("avant { ligne1\nligne2 -- fin", None)
check("[E] accolade non fermee sur plusieurs lignes : tout le reste est masque", resultat == "avant <donnees>")
resultat = nettoyer("accolade fermante seule } et suite", None)
check("[E] accolade fermante isolee : message inchange", resultat == "accolade fermante seule } et suite")

# --- F. accolades legitimes non sensibles : contenu masque, mots conserves ---
resultat = nettoyer("Propriété {Etat} introuvable ; valeurs attendues {Pas commencé, En cours}.", None)
check("[F] accolades legitimes : seul le contenu entre accolades est remplace (resultat exact)",
      resultat == "Propriété <donnees> introuvable ; valeurs attendues <donnees>.")
check("[F] « Propriété », « introuvable », « valeurs attendues » conserves",
      all(m in resultat for m in ("Propriété", "introuvable", "valeurs attendues")) and "Etat" not in resultat)

# --- G. pages orphelines apres une structure sensible ---
LISTE_ORPHELINES = "Pages orphelines : ['page-1', 'page-2']"
resultat = nettoyer(f"Onboarding echoue {PAYLOAD_REPR}. {LISTE_ORPHELINES}", infos_client)
check("[G] structure sensible masquee", "<donnees>" in resultat and not any(c in resultat for c in (EMAIL, TEL, "event_type")))
check("[G] la liste des pages orphelines est conservee exactement", resultat.endswith(LISTE_ORPHELINES))
resultat = nettoyer(f"Echec {PAYLOAD_JSON} puis {{autre: 1}} ; {LISTE_ORPHELINES}", None)
check("[G] avec plusieurs structures : la liste reste intacte a la fin", resultat.endswith(LISTE_ORPHELINES) and resultat.count("<donnees>") == 2)

# --- H. performance : messages longs, termine et reste borne a 300 caracteres ---
cas_longs = {
    "100 000 structures fermees": "{x} " * 100_000,
    "100 000 accolades ouvrantes": "{" * 100_000,
    "melange ferme / non ferme (50 000 x)": "{a} texte {b " * 50_000,
    "imbrication profonde (30 000 niveaux)": "{" * 30_000 + "}" * 30_000,
    "message de 5 Mo sans accolade": "erreur utile " * 400_000,
    "message de 5 Mo avec accolades": ("erreur {k: v} utile " * 250_000),
}
for libelle, message_long in cas_longs.items():
    debut_chrono = time.perf_counter()
    resultat = nettoyer(message_long, infos_client)
    duree = time.perf_counter() - debut_chrono
    check(f"[H] {libelle} : termine ({duree:.2f} s < 10 s) et resultat <= 300 caracteres", duree < 10 and len(resultat) <= 300)

resultat = nettoyer("{" * 30_000 + "}" * 30_000, None)
check("[H] imbrication au-dela de la borne de passes : fail-closed, aucune accolade ne subsiste", "{" not in resultat and "}" not in resultat)
check("[H] la borne de passes est finie", 0 < portal_main._NETTOYAGE_PASSES_MAX <= 100)

# --- De bout en bout : texte utile conserve dans le log, payload masque, alerte inchangee ---
message_utile = f"Onboarding echoue {PAYLOAD_JSON} -- cause utile: Notion indisponible. {LISTE_ORPHELINES}"
t, alerte = echec_bout_en_bout(NOM, message_utile)
check("[E2E] log : le texte utile apres le payload ferme est conserve", "cause utile: Notion indisponible" in t and LISTE_ORPHELINES in t)
check("[E2E] log : le payload est masque (aucune cle, email, telephone, template)",
      "<donnees>" in t and not any(c in t for c in CLES_PAYLOAD) and EMAIL not in t and TEL not in t)
sujet, message_alerte = alerte.call_args[0]
check("[E2E] alerte coach inchangee : cause generique, aucun detail du log",
      "Cause technique : création automatique interrompue." in message_alerte
      and "cause utile" not in message_alerte and "Pages orphelines" not in message_alerte and "<donnees>" not in message_alerte)


print("\n" + "=" * 80)
print("VERIFICATION GLOBALE : confidentialite de l'ensemble des logs captures")
print("=" * 80)

tout = texte(capture.records)
interdits = {
    "email en clair": EMAIL,
    "nom complet": NOM,
    "nom de famille": "Dupont",
    "telephone": TEL,
    "URL n8n": URL_N8N,
    "hote n8n": HOTE,
    "URL Notion": "api.notion.com",
    "secret": SECRET,
    "mauvais secret": MAUVAIS_SECRET,
    "schema http://": "http://",
    "schema https://": "https://",
    "chemin de webhook": "/webhook",
    "payload (event_type)": "event_type",
    "payload (values)": "'values'",
    "payload (data)": "'data'",
}

interdits.update({
    "chemin url: prive": "chemin-prive",
    "telephone (chiffres)": TEL.lstrip("+"),
    "payload (accolade)": "{",
})

for libelle, valeur in interdits.items():
    check(f"aucun log ne contient : {libelle}", valeur not in tout)

for nom_court in ("Li", "X"):
    check(f"aucun log ne contient le nom court « {nom_court} » ({len(nom_court)} car.)", not mot(nom_court, tout))

check("aucun 'host=' reel (seul le placeholder est autorise)", "host=" not in tout.replace("host=<hote>", ""))
check("aucune trace d'exception dans l'ensemble des logs", all(r.exc_info is None for r in capture.records))
check("les logs contiennent bien des references masquees", EMAIL_MASQUE in tout)

# Helpers de nettoyage (cas des deux formats d'erreur de requests, hors reseau)
check("nettoyage : erreur de connexion (hote + chemin)",
      "n8n" not in portal_main._nettoyer_erreur(
          f"HTTPSConnectionPool(host='{HOTE}', port=443): Max retries exceeded with url: /webhook/abc123"))
check("nettoyage : tronque a 300 caracteres", len(portal_main._nettoyer_erreur("x" * 1000)) == 300)
check("nettoyage : adresse email inconnue masquee", "@" not in portal_main._nettoyer_erreur("contact autre@exemple.test"))
check("email masque sans arobase", portal_main._masquer_email("pas-un-email") == "***")


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
