# Tests de non-regression : aucune URL de webhook, aucun texte brut
# d'exception et aucune identite client (email, nom) ne sortent de
# notion_service, ni dans la reponse de l'onboarding coach, ni dans les logs
# (alertes coach diagnostic/bonus, journal des connexions, invitation portail).
#
# Entierement mockes (aucun appel reseau reel vers Notion ou n8n) : le client
# HTTP de Notion et requests.post sont remplaces par des faux qui renvoient de
# vraies reponses `requests` (un vrai HTTPError est leve par raise_for_status).
# Toutes les valeurs (emails, noms, URL, secrets) sont fictives. Meme style que
# les autres scripts de test (pas de framework, aucune dependance en plus).
#
# Lancer : python test_error_sanitization.py

import json
import logging
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

import requests

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-sanitization"

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

EMAIL = "client.factice@exemple.invalid"
NOM = "Prenom Factice"
HOTE = "n8n.exemple.invalid"
CHEMIN = "/webhook/chemin-factice-7f3a9c"
URL_INVITE = f"https://{HOTE}{CHEMIN}"
URL_ALERTE = f"https://{HOTE}/webhook/alerte-factice-2b8e41"
PORTAIL = "https://portail.exemple.invalid"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"

# Fragments qui ne doivent apparaitre nulle part (hors champ email/nom attendus).
INTERDITS = [
    URL_INVITE, URL_ALERTE, HOTE, CHEMIN, "chemin-factice", "alerte-factice",
    "api.notion.com", "Client Error", "Server Error", "for url", "Max retries",
    "Erreur envoi invitation", "Erreur Notion",
]
INTERDITS_LOG = INTERDITS + [EMAIL, NOM, "Prenom", "client.factice"]


def fuites(texte, liste):
    bas = texte.lower()
    return [f for f in liste if f.lower() in bas]


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


def texte_logs(debut):
    records = capture.records[debut:]
    lignes = [r.getMessage() for r in records]
    # Une trace d'exception (exc_info) contiendrait le texte brut : on l'inclut.
    lignes += [logging.Formatter().formatException(r.exc_info) for r in records if r.exc_info]
    return records, "\n".join(lignes)


# --- Faux reseau ----------------------------------------------------------------

def garde_reseau(*args, **kwargs):
    raise AssertionError("appel reseau reel interdit dans ces tests")


def reponse(statut, url, corps=None):
    # Vraie reponse `requests` : raise_for_status() leve un vrai HTTPError
    # dont le texte contient l'URL appelee.
    r = requests.Response()
    r.status_code = statut
    r.url = url
    r.reason = "Not Found" if statut == 404 else "Erreur factice"
    r._content = json.dumps(corps or {}).encode("utf-8")
    return r


class FauxNotion:
    # Remplace ns._http : requete de recherche -> aucun client, creation de
    # page -> identifiant factice (ou erreur HTTP si demande).
    def __init__(self, creation_statut=200):
        self.creations = []
        self.creation_statut = creation_statut

    def post(self, url, headers=None, json=None, timeout=None):
        if url.endswith("/query"):
            return reponse(200, url, {"results": []})

        if url.endswith("/pages"):
            self.creations.append(json)

            if self.creation_statut != 200:
                return reponse(self.creation_statut, url, {"message": f"erreur factice pour {EMAIL}"})

            return reponse(200, url, {"id": f"page-factice-{len(self.creations)}"})

        raise AssertionError("route Notion inattendue")

    def get(self, url, headers=None, timeout=None):
        return reponse(200, url, {"id": CLIENT_ID, "properties": {"Nom": {"type": "title", "title": [{"plain_text": NOM}]}}})

    def patch(self, *args, **kwargs):
        raise AssertionError("aucune modification Notion attendue")


@contextmanager
def environnement(faux_notion, post):
    # Variables isolees : aucune valeur reelle du poste n'est lue.
    with patch.dict(os.environ, {}, clear=False):
        for cle in ("N8N_WEBHOOK_MAGIC_LINK", "N8N_WEBHOOK_COACH_ALERT", "PORTAL_FRONTEND_URL", "COACH_ONBOARD_KEY"):
            os.environ.pop(cle, None)

        os.environ.update({
            "N8N_WEBHOOK_MAGIC_LINK": URL_INVITE,
            "N8N_WEBHOOK_COACH_ALERT": URL_ALERTE,
            "PORTAL_FRONTEND_URL": PORTAIL,
            "COACH_ONBOARD_KEY": "cle-coach-factice",
        })

        with patch.object(ns, "NOTION_API_KEY", "cle-notion-factice"), \
             patch.object(ns, "_http", faux_notion), \
             patch.object(requests, "post", side_effect=post) as faux_post:
            yield faux_post


def http_404(url, json=None, timeout=None):
    return reponse(404, url)


def http_500(url, json=None, timeout=None):
    return reponse(500, url)


def connexion_impossible(url, json=None, timeout=None):
    raise requests.ConnectionError(
        f"HTTPSConnectionPool(host='{HOTE}', port=443): Max retries exceeded with url: {CHEMIN} ({EMAIL})"
    )


def http_200(url, json=None, timeout=None):
    return reponse(200, url)


ONBOARD = portal_main.CoachClientOnboardRequest(nom=NOM, email=EMAIL)


# --- TEST 1-2 : onboarding coach de bout en bout, invitation en echec -------------

for numero, libelle, post, classe in (
    (1, "HTTPError 404 du webhook", http_404, "HTTPError"),
    (2, "ConnectionError vers le webhook", connexion_impossible, "ConnectionError"),
):
    print("\n" + "=" * 80)
    print(f"TEST {numero}/6 : /coach/clients/onboard de bout en bout - {libelle}")
    print("=" * 80)

    faux = FauxNotion()
    debut = repere()

    with environnement(faux, post) as faux_post:
        try:
            resultat = portal_main.coach_onboard_client(ONBOARD, x_coach_key="cle-coach-factice")
            sortie = "aucune exception"
        except Exception as exc:
            resultat, sortie = None, type(exc).__name__

    records, logs = texte_logs(debut)
    reste = {k: v for k, v in (resultat or {}).items() if k not in ("email", "nom")}
    reste_json = json.dumps(reste, ensure_ascii=False)
    tout_json = json.dumps(resultat or {}, ensure_ascii=False)

    check(f"[{numero}] aucune exception : reponse 200 inchangee", sortie == "aucune exception")
    check(f"[{numero}] structure de la reponse inchangee",
          set(resultat or {}) == {"client_id", "nom", "email", "fiches_creees", "kpi_crees",
                                  "kpi_a_completer", "invite_envoyee", "invite_erreur"})
    check(f"[{numero}] nom et email dans leurs champs habituels",
          (resultat or {}).get("email") == EMAIL and (resultat or {}).get("nom") == NOM)
    check(f"[{numero}] invite_envoyee=False et invite_erreur = code generique",
          (resultat or {}).get("invite_envoyee") is False
          and (resultat or {}).get("invite_erreur") == "envoi_invitation_echoue")
    check(f"[{numero}] reponse entiere : aucune URL ni texte brut ({', '.join(fuites(tout_json, INTERDITS)) or 'aucune'})",
          not fuites(tout_json, INTERDITS))
    check(f"[{numero}] email et nom absents des autres champs ({', '.join(fuites(reste_json, [EMAIL, NOM])) or 'aucune'})",
          not fuites(reste_json, [EMAIL, NOM]))
    check(f"[{numero}] logs : aucune URL, email, nom ni texte brut ({', '.join(fuites(logs, INTERDITS_LOG)) or 'aucune'})",
          not fuites(logs, INTERDITS_LOG))
    check(f"[{numero}] logs : le diagnostic assaini est present (classe {classe})",
          any(r.getMessage().startswith("Invitation portail non envoyee : RuntimeError (" + classe) for r in records))
    check(f"[{numero}] aucune trace d'exception (exc_info)", all(r.exc_info is None for r in records))
    attendues = 1 + len(ns.FICHE_SCHEMAS) + len(ns._KPI_ONBOARDING_DEFAULTS)
    check(f"[{numero}] flux Notion inchange : 1 client + toutes les fiches + KPI J0 crees ({attendues} pages)",
          len(faux.creations) == attendues)

    appel = faux_post.call_args
    envoye = (appel.kwargs.get("json") if appel else None) or {}
    check(f"[{numero}] payload n8n de l'invitation inchange",
          appel is not None and appel.args == (URL_INVITE,)
          and set(envoye) == {"to", "client_name", "magic_link"}
          and envoye["to"] == EMAIL and envoye["client_name"] == NOM
          and envoye["magic_link"].startswith(f"{PORTAIL}/verify?token="))


# --- TEST 3 : alerte diagnostic -------------------------------------------------------

print("\n" + "=" * 80)
print("TEST 3/6 : alerter_coach_diagnostic - logs sans nom, email, URL ni texte brut")
print("=" * 80)

PAYLOAD_DIAGNOSTIC = {
    "event": "diagnostic_termine",
    "client_nom": NOM,
    "client_email": EMAIL,
    "coach_url": f"{PORTAIL}/coach",
    "subject": f"Diagnostic terminé : {NOM} (fiche 8 à valider)",
    "message": (
        f"{NOM} vient de terminer son diagnostic (fiches 3 à 7).\n\n"
        f"Ouvre l'Espace Coach, onglet Diagnostics : le rapport et les scores proposés sont prêts.\n"
        f"{PORTAIL}/coach"
    ),
}

for libelle, post, attendu in (
    ("HTTPError 500", http_500, "Alerte diagnostic non envoyee : HTTPError (500)"),
    ("ConnectionError", connexion_impossible, "Alerte diagnostic non envoyee : ConnectionError"),
    ("envoi reussi", http_200, "Alerte diagnostic envoyee au coach."),
):
    debut = repere()

    with environnement(FauxNotion(), post) as faux_post:
        try:
            ns.alerter_coach_diagnostic(NOM, EMAIL)
            sortie = "aucune exception"
        except Exception as exc:
            sortie = type(exc).__name__

    records, logs = texte_logs(debut)
    appel = faux_post.call_args

    check(f"[3] {libelle} : aucune exception", sortie == "aucune exception")
    check(f"[3] {libelle} : log attendu exact", [r.getMessage() for r in records] == [attendu])
    check(f"[3] {libelle} : logs sans fuite ({', '.join(fuites(logs, INTERDITS_LOG)) or 'aucune'})",
          not fuites(logs, INTERDITS_LOG))
    check(f"[3] {libelle} : payload n8n inchange",
          appel is not None and appel.args == (URL_ALERTE,) and appel.kwargs.get("json") == PAYLOAD_DIAGNOSTIC)

debut = repere()

with environnement(FauxNotion(), garde_reseau), patch.dict(os.environ, {"N8N_WEBHOOK_COACH_ALERT": ""}):
    ns.alerter_coach_diagnostic(NOM, EMAIL)

records, logs = texte_logs(debut)
check("[3] webhook absent : warning sans nom", [r.getMessage() for r in records]
      == ["N8N_WEBHOOK_COACH_ALERT manquant : alerte diagnostic non envoyee."])
check(f"[3] webhook absent : logs sans fuite ({', '.join(fuites(logs, INTERDITS_LOG)) or 'aucune'})",
      not fuites(logs, INTERDITS_LOG))


# --- TEST 4 : alerte bonus ----------------------------------------------------------

print("\n" + "=" * 80)
print("TEST 4/6 : alerter_coach_bonus - logs sans nom, URL ni texte brut")
print("=" * 80)

RESULTAT_BONUS = {"territoire": "Territoire factice", "score": 13, "max": 20, "niveau": "Niveau factice",
                  "aides": ["Aide factice A"], "alertes": ["Vigilance factice"]}
PAYLOAD_BONUS = {
    "event": "bonus_termine",
    "client_nom": NOM,
    "subject": f"Bonus aides : {NOM} (13/20)",
    "message": "\n".join([
        f"{NOM} a validé son diagnostic d'éligibilité aux aides.",
        "Territoire : Territoire factice",
        "Score d'ancrage local : 13 / 20 (Niveau factice, seuil bonus 12)",
        "Aides à explorer : Aide factice A",
        "Points de vigilance : Vigilance factice",
        f"{PORTAIL}/coach",
    ]),
}

for libelle, post, attendu in (
    ("HTTPError 404", http_404, ["Alerte bonus non envoyee : HTTPError (404)"]),
    ("ConnectionError", connexion_impossible, ["Alerte bonus non envoyee : ConnectionError"]),
    ("envoi reussi", http_200, []),
):
    debut = repere()

    with environnement(FauxNotion(), post) as faux_post:
        try:
            ns.alerter_coach_bonus(NOM, RESULTAT_BONUS)
            sortie = "aucune exception"
        except Exception as exc:
            sortie = type(exc).__name__

    records, logs = texte_logs(debut)
    appel = faux_post.call_args

    check(f"[4] {libelle} : aucune exception", sortie == "aucune exception")
    check(f"[4] {libelle} : log attendu exact", [r.getMessage() for r in records] == attendu)
    check(f"[4] {libelle} : logs sans fuite ({', '.join(fuites(logs, INTERDITS_LOG)) or 'aucune'})",
          not fuites(logs, INTERDITS_LOG))
    check(f"[4] {libelle} : payload n8n inchange",
          appel is not None and appel.args == (URL_ALERTE,) and appel.kwargs.get("json") == PAYLOAD_BONUS)


# --- TEST 5 : journal des connexions -----------------------------------------------

print("\n" + "=" * 80)
print("TEST 5/6 : log_portal_connection - echec Notion sans email, nom, URL ni texte brut")
print("=" * 80)

faux = FauxNotion(creation_statut=400)
debut = repere()

with environnement(faux, garde_reseau):
    try:
        ns.log_portal_connection(EMAIL, CLIENT_ID)
        sortie = "aucune exception"
    except Exception as exc:
        sortie = type(exc).__name__

records, logs = texte_logs(debut)
props = (faux.creations[0] or {}).get("properties", {}) if faux.creations else {}

check("[5] aucune exception : la connexion du client n'echoue jamais", sortie == "aucune exception")
check("[5] log attendu exact", [r.getMessage() for r in records]
      == ["Echec journalisation connexion portail : RuntimeError (HTTPError 400)"])
check(f"[5] logs sans fuite ({', '.join(fuites(logs, INTERDITS_LOG)) or 'aucune'})", not fuites(logs, INTERDITS_LOG))
check("[5] page Notion envoyee inchangee (email, nom client, date)",
      set(props) == {"Email", "Client", "Date de connexion"}
      and props["Email"]["title"][0]["text"]["content"] == EMAIL
      and props["Client"]["rich_text"][0]["text"]["content"] == NOM)


# --- TEST 6 : helper et structure du code --------------------------------------------

print("\n" + "=" * 80)
print("TEST 6/6 : _resume_erreur et structure du code")
print("=" * 80)

erreur_http = requests.HTTPError(f"404 Client Error: Not Found for url: {URL_INVITE}", response=reponse(404, URL_INVITE))

try:
    raise RuntimeError(f"Erreur envoi invitation portail : {erreur_http} {EMAIL}") from erreur_http
except RuntimeError as enveloppe:
    resume_enveloppe = ns._resume_erreur(enveloppe)

check("[6] RuntimeError enveloppant un HTTPError : classe + cause + statut",
      resume_enveloppe == "RuntimeError (HTTPError 404)")
check("[6] HTTPError direct : classe + statut", ns._resume_erreur(erreur_http) == "HTTPError (404)")
check("[6] erreur sans cause requests : classe seule", ns._resume_erreur(ValueError(EMAIL)) == "ValueError")
check("[6] aucun texte brut dans les resumes",
      not fuites(resume_enveloppe + ns._resume_erreur(erreur_http), INTERDITS_LOG))

source = open("backend/services/notion_service.py", encoding="utf-8").read()
onboard = source[source.index("def onboard_client("):]
check("[6] onboard_client ne renvoie plus str(error)", "str(error)" not in onboard)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
