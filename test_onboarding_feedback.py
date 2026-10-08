# Tests du retour d'onboarding au coach : invitation echouee (200 + code
# stable), client deja existant (409 + code stable), panne (503 generique),
# alertes DocuSeal assainies (evenement, reference masquee, parcours et lien
# de l'espace coach uniquement).
#
# Entierement mockes (aucun appel reseau reel vers Notion, n8n ou DocuSeal) :
# le client HTTP de Notion et requests.post sont remplaces par des faux qui
# renvoient de vraies reponses `requests` ; tout appel non prevu fait echouer
# le test. Toutes les valeurs (emails, noms, URL, secrets, identifiants) sont
# fictives, en .invalid. Meme style que les autres scripts de test (pas de
# framework, aucune dependance en plus).
#
# Lancer : python test_onboarding_feedback.py

import json
import logging
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

import requests
from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-feedback"

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


def titre(texte):
    print("\n" + "=" * 80)
    print(texte)
    print("=" * 80)


# --- Valeurs fictives ------------------------------------------------------------

EMAIL = "coralie.fictive@exemple.invalid"
NOM = "Coralie Fictive"
HOTE = "n8n.exemple.invalid"
URL_INVITE = f"https://{HOTE}/webhook/invite-factice-5d1e"
URL_ALERTE = f"https://{HOTE}/webhook/alerte-factice-8c2f"
PORTAIL = "https://portail.exemple.invalid"
COACH_URL = f"{PORTAIL}/coach"
CLE_COACH = "cle-coach-factice"
SECRET_DOCUSEAL = "secret-docuseal-factice"
PAGE_EXISTANTE = "99999999-8888-7777-6666-555555555555"
REF = portal_main._reference_docuseal(EMAIL)
GENERIQUE_503 = "Le service est momentanément indisponible. Réessayez dans quelques minutes."
DETAIL_409 = "Un client existe déjà avec cet email."
TEMPLATE_COACHING = next(k for k, v in portal_main._DOCUSEAL_PARCOURS.items() if v == "Coaching 90 jours")

# Fragments techniques qui ne doivent apparaitre nulle part.
TECHNIQUES = [
    URL_INVITE, URL_ALERTE, HOTE, "invite-factice", "alerte-factice", "/webhook",
    "api.notion.com", "Client Error", "Server Error", "for url", "Max retries",
    "Erreur envoi invitation", "Erreur Notion", "bug-factice", "existe deja avec l'email",
    "Onboarding annule", "Traceback",
]
# Donnees du client : interdites partout, sauf dans les champs nom/email de la reponse 200.
IDENTITE = [EMAIL, NOM, "coralie", "Fictive", PAGE_EXISTANTE]
INTERDITS = TECHNIQUES + IDENTITE
# Logs [portal-error] / [docuseal] d'echec Notion : le diagnostic assaini existant
# (classe, statut, "<url>", "<masque>") y est attendu ; seules les URL et
# l'identite du client y sont interdites.
URL_ET_IDENTITE = [URL_INVITE, URL_ALERTE, HOTE, "invite-factice", "alerte-factice", "/webhook",
                   "api.notion.com"] + IDENTITE


def fuites(texte, liste=INTERDITS):
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


def logs(debut):
    records = capture.records[debut:]
    lignes = [r.getMessage() for r in records]
    # Une trace d'exception (exc_info) contiendrait le texte brut : on l'inclut.
    lignes += [logging.Formatter().formatException(r.exc_info) for r in records if r.exc_info]
    return records, "\n".join(lignes)


# --- Faux reseau ----------------------------------------------------------------

def reponse(statut, url, corps=None):
    # Vraie reponse `requests` : raise_for_status() leve un vrai HTTPError
    # dont le texte contient l'URL appelee.
    r = requests.Response()
    r.status_code = statut
    r.url = url
    r.reason = "Erreur factice"
    r._content = json.dumps(corps or {}).encode("utf-8")
    return r


class FauxNotion:
    # Remplace ns._http. existant=True : la recherche par email trouve un
    # client. requete_statut / creation_statut != 200 : erreur HTTP Notion.
    def __init__(self, existant=False, requete_statut=200, creation_statut=200):
        self.existant = existant
        self.requete_statut = requete_statut
        self.creation_statut = creation_statut
        self.requetes = 0
        self.creations = []

    def post(self, url, headers=None, json=None, timeout=None):
        if url.endswith("/query"):
            self.requetes += 1

            if self.requete_statut != 200:
                return reponse(self.requete_statut, url, {"message": f"erreur factice pour {EMAIL}"})

            resultats = [{"id": PAGE_EXISTANTE, "properties": {}}] if self.existant else []
            return reponse(200, url, {"results": resultats, "has_more": False})

        if url.endswith("/pages"):
            self.creations.append(json)

            if self.creation_statut != 200:
                return reponse(self.creation_statut, url, {"message": f"erreur factice pour {EMAIL}"})

            return reponse(200, url, {"id": f"page-factice-{len(self.creations)}"})

        raise AssertionError("route Notion inattendue")

    def get(self, url, headers=None, timeout=None):
        raise AssertionError("aucune lecture Notion attendue")

    def patch(self, url, headers=None, json=None, timeout=None):
        # Archivage du rollback.
        return reponse(200, url, {"archived": True})


def routeur(invite="ok", alerte="ok"):
    # Faux requests.post : distingue le webhook du lien magique et celui de
    # l'alerte coach ; tout autre appel est interdit.
    def comportement(mode, url):
        if mode == "ok":
            return reponse(200, url)
        if mode == "http_500":
            return reponse(500, url)
        if mode == "connexion":
            raise requests.ConnectionError(
                f"HTTPSConnectionPool(host='{HOTE}', port=443): Max retries exceeded with url: {url} ({EMAIL})"
            )
        if mode == "timeout":
            raise requests.Timeout(f"Read timed out for url: {url} ({NOM})")
        if mode == "inattendue":
            raise ValueError(f"bug-factice {url} {EMAIL} {NOM}")
        raise AssertionError("mode inconnu")

    def post(url, json=None, timeout=None, **kwargs):
        if url == URL_INVITE:
            return comportement(invite, url)
        if url == URL_ALERTE:
            return comportement(alerte, url)
        raise AssertionError("appel reseau reel interdit dans ces tests")

    return post


@contextmanager
def environnement(faux_notion, post, invite_configure=True):
    # Variables isolees : aucune valeur reelle du poste n'est lue.
    cles = ("N8N_WEBHOOK_MAGIC_LINK", "N8N_WEBHOOK_COACH_ALERT", "PORTAL_FRONTEND_URL",
            "COACH_ONBOARD_KEY", "DOCUSEAL_WEBHOOK_SECRET")

    with patch.dict(os.environ, {}, clear=False):
        for cle in cles:
            os.environ.pop(cle, None)

        os.environ.update({
            "N8N_WEBHOOK_COACH_ALERT": URL_ALERTE,
            "PORTAL_FRONTEND_URL": PORTAIL,
            "COACH_ONBOARD_KEY": CLE_COACH,
            "DOCUSEAL_WEBHOOK_SECRET": SECRET_DOCUSEAL,
        })

        if invite_configure:
            os.environ["N8N_WEBHOOK_MAGIC_LINK"] = URL_INVITE

        with patch.object(ns, "NOTION_API_KEY", "cle-notion-factice"), \
             patch.object(ns, "_http", faux_notion), \
             patch.object(requests, "post", side_effect=post) as faux_post:
            yield faux_post


def onboarder(cle=CLE_COACH, email=EMAIL):
    # Appelle la route coach ; renvoie (statut, corps, nom de l'exception inattendue).
    requete = portal_main.CoachClientOnboardRequest(nom=NOM, email=email)

    try:
        resultat = portal_main.coach_onboard_client(requete, x_coach_key=cle)
    except HTTPException as error:
        return error.status_code, {"detail": error.detail}, None
    except Exception as error:
        return None, None, type(error).__name__

    if isinstance(resultat, JSONResponse):
        return resultat.status_code, json.loads(resultat.body), None

    return 200, resultat, None


def docuseal():
    # Appelle le webhook DocuSeal puis execute la tache de fond.
    payload = {"event_type": "form.completed",
               "data": {"name": NOM, "email": EMAIL, "template": {"id": TEMPLATE_COACHING}, "values": []}}
    bt = BackgroundTasks()
    reponse_webhook = portal_main.webhook_docuseal(payload, bt, x_webhook_secret=SECRET_DOCUSEAL)

    sortie = None

    for tache in bt.tasks:
        try:
            tache.func(*tache.args, **tache.kwargs)
        except Exception as error:
            sortie = type(error).__name__

    return reponse_webhook, sortie


def alertes_envoyees(faux_post):
    return [c.kwargs.get("json") or {} for c in faux_post.call_args_list if c.args and c.args[0] == URL_ALERTE]


def verifier_alerte(prefixe, corps, event):
    # L'alerte ne contient que : evenement, reference masquee, parcours, lien de
    # l'espace coach (et des phrases fixes).
    check(f"{prefixe} champs event/subject/message/coach_url", set(corps) == {"event", "subject", "message", "coach_url"})
    check(f"{prefixe} evenement {event}", corps.get("event") == event)
    check(f"{prefixe} coach_url = lien public de l'espace coach", corps.get("coach_url") == COACH_URL)
    message = corps.get("message", "")
    check(f"{prefixe} message : evenement, reference masquee et parcours",
          f"Événement : {event}" in message and f"Référence : {REF}" in message and "Parcours : Coaching 90 jours" in message)
    tout = (corps.get("subject", "") + "\n" + message).replace(COACH_URL, "")
    check(f"{prefixe} aucune autre URL que le lien de l'espace coach", "http" not in tout.lower())
    check(f"{prefixe} sans nom, email, id de page ni detail technique ({', '.join(fuites(tout)) or 'aucune'})",
          not fuites(tout))


# --- Tests -------------------------------------------------------------------------

CLES_200 = {"client_id", "nom", "email", "fiches_creees", "kpi_crees", "kpi_a_completer", "invite_envoyee", "invite_erreur"}
PAGES_ATTENDUES = 1 + len(ns.FICHE_SCHEMAS) + len(ns._KPI_ONBOARDING_DEFAULTS)

titre("TEST 1/7 : 200 - client cree, invitation echouee -> code stable, sans fuite")

variantes = (
    ("HTTP 500 du webhook", routeur(invite="http_500"), True, "HTTPError"),
    ("erreur reseau", routeur(invite="connexion"), True, "ConnectionError"),
    ("timeout", routeur(invite="timeout"), True, "Timeout"),
    ("webhook non configure", routeur(), False, "RuntimeError"),
    ("exception inattendue (ValueError)", routeur(invite="inattendue"), True, "ValueError"),
)

for libelle, post, configure, classe in variantes:
    faux = FauxNotion()
    debut = repere()

    with environnement(faux, post, invite_configure=configure):
        statut, corps, inattendue = onboarder()

    records, texte = logs(debut)
    reste = json.dumps({k: v for k, v in (corps or {}).items() if k not in ("nom", "email")}, ensure_ascii=False)
    p = f"[1] {libelle} :"
    check(f"{p} 200, aucune exception", (statut, inattendue) == (200, None))
    check(f"{p} structure inchangee", set(corps or {}) == CLES_200)
    check(f"{p} invite_envoyee=false et invite_erreur=envoi_invitation_echoue",
          (corps or {}).get("invite_envoyee") is False and (corps or {}).get("invite_erreur") == "envoi_invitation_echoue")
    check(f"{p} nom et email uniquement dans leurs champs", (corps or {}).get("nom") == NOM and (corps or {}).get("email") == EMAIL)
    check(f"{p} reste de la reponse sans fuite ({', '.join(fuites(reste)) or 'aucune'})", not fuites(reste))
    check(f"{p} logs sans fuite ({', '.join(fuites(texte)) or 'aucune'})", not fuites(texte))
    check(f"{p} diagnostic assaini present ({classe})",
          any(r.getMessage().startswith("Invitation portail non envoyee : ") and classe in r.getMessage() for r in records))
    check(f"{p} aucune trace d'exception", all(r.exc_info is None for r in records))
    check(f"{p} toutes les pages creees, aucun rollback ({PAGES_ATTENDUES})", len(faux.creations) == PAGES_ATTENDUES)


titre("TEST 2/7 : 409 - client deja existant -> code stable, aucune creation, sans fuite")

for libelle, email in (("email tel quel", EMAIL), ("email en majuscules", EMAIL.upper())):
    faux = FauxNotion(existant=True)
    debut = repere()

    with environnement(faux, routeur()) as faux_post:
        statut, corps, inattendue = onboarder(email=email)

    records, texte = logs(debut)
    p = f"[2] {libelle} :"
    check(f"{p} 409, aucune exception", (statut, inattendue) == (409, None))
    check(f"{p} corps exact", corps == {"detail": DETAIL_409, "code": "client_deja_existant"})
    check(f"{p} aucune page creee, aucun appel reseau", faux.creations == [] and faux_post.call_count == 0)
    lignes = [r for r in records if r.getMessage().startswith("[portal] onboarding refuse")]
    check(f"{p} une seule ligne de log au format attendu",
          len(lignes) == 1 and lignes[0].levelname == "WARNING" and lignes[0].getMessage() ==
          f"[portal] onboarding refuse contexte=coach_onboard_client raison=client_deja_existant ref={REF}")
    check(f"{p} aucun log error", not [r for r in records if r.levelno >= logging.ERROR])
    check(f"{p} reponse et logs sans fuite ({', '.join(fuites(json.dumps(corps, ensure_ascii=False) + texte)) or 'aucune'})",
          not fuites(json.dumps(corps, ensure_ascii=False) + texte))
    check(f"{p} aucune trace d'exception", all(r.exc_info is None for r in records))


titre("TEST 3/7 : 503 - panne Notion -> message generique, jamais 409")

for libelle, faux in (("recherche client en erreur", FauxNotion(requete_statut=500)),
                      ("creation en erreur (rollback)", FauxNotion(creation_statut=500))):
    debut = repere()

    with environnement(faux, routeur()):
        statut, corps, inattendue = onboarder()

    records, texte = logs(debut)
    p = f"[3] {libelle} :"
    check(f"{p} 503 et message generique exact", (statut, corps, inattendue) == (503, {"detail": GENERIQUE_503}, None))
    check(f"{p} un log [portal-error] contexte=coach_onboard_client",
          any(r.getMessage().startswith("[portal-error] contexte=coach_onboard_client erreur=RuntimeError") for r in records))
    check(f"{p} logs sans URL, email, nom ni id ({', '.join(fuites(texte, URL_ET_IDENTITE)) or 'aucune'})",
          not fuites(texte, URL_ET_IDENTITE) and "<url>" in texte)

check("[3] ClientDejaExistant reste une sous-classe de RuntimeError", issubclass(ns.ClientDejaExistant, RuntimeError))


titre("TEST 4/7 : 401 - mauvaise cle coach -> ni recherche, ni 409, ni 503")

faux = FauxNotion(existant=True)

with environnement(faux, routeur()) as faux_post:
    statut, corps, inattendue = onboarder(cle="mauvaise-cle-factice")

check("[4] 401 et message fixe", (statut, corps, inattendue) == (401, {"detail": "Code d'acces invalide."}, None))
check("[4] aucune recherche Notion ni appel reseau", faux.requetes == 0 and faux_post.call_count == 0)


titre("TEST 5/7 : DocuSeal - client deja existant -> warning + alerte assainie")

for libelle, mode in (("alerte envoyee", "ok"), ("alerte en HTTP 500", "http_500"), ("alerte en erreur reseau", "connexion")):
    faux = FauxNotion(existant=True)
    debut = repere()

    with environnement(faux, routeur(alerte=mode)) as faux_post:
        reponse_webhook, sortie = docuseal()

    records, texte = logs(debut)
    alertes = alertes_envoyees(faux_post)
    p = f"[5] {libelle} :"
    check(f"{p} reponse au webhook inchangee", reponse_webhook == {"status": "accepte", "parcours": "Coaching 90 jours"})
    check(f"{p} aucune exception ne sort de la tache de fond", sortie is None)
    check(f"{p} aucune page creee", faux.creations == [])
    check(f"{p} warning 'client deja existant' conserve",
          any(r.levelname == "WARNING" and "client deja existant" in r.getMessage() for r in records))
    check(f"{p} une seule alerte tentee", len(alertes) == 1)
    verifier_alerte(p, alertes[0] if alertes else {}, "docuseal_client_deja_existant")
    check(f"{p} logs sans fuite ({', '.join(fuites(texte)) or 'aucune'})", not fuites(texte))
    check(f"{p} aucune trace d'exception", all(r.exc_info is None for r in records))

    if mode != "ok":
        check(f"{p} echec de l'alerte journalise par sa classe seule",
              any("Alerte onboarding non envoyee" in r.getMessage() for r in records))


titre("TEST 6/7 : DocuSeal - alertes d'echec alignees (reference masquee, parcours)")

for libelle, faux, post, event in (
    ("creation echouee", FauxNotion(creation_statut=500), routeur(), "onboarding_docuseal_echec"),
    ("lien d'acces non envoye", FauxNotion(), routeur(invite="http_500"), "onboarding_docuseal_echec"),
):
    debut = repere()

    with environnement(faux, post) as faux_post:
        reponse_webhook, sortie = docuseal()

    records, texte = logs(debut)
    alertes = alertes_envoyees(faux_post)
    p = f"[6] {libelle} :"
    check(f"{p} aucune exception ne sort de la tache de fond", sortie is None)
    check(f"{p} une seule alerte", len(alertes) == 1)
    verifier_alerte(p, alertes[0] if alertes else {}, event)
    check(f"{p} logs sans URL, email, nom ni id ({', '.join(fuites(texte, URL_ET_IDENTITE)) or 'aucune'})",
          not fuites(texte, URL_ET_IDENTITE))


titre("TEST 7/7 : alerter_coach_onboarding - evenement par defaut et explicite")

for libelle, kwargs, attendu in (("par defaut", {}, "onboarding_docuseal_echec"),
                                 ("explicite", {"event": "docuseal_client_deja_existant"}, "docuseal_client_deja_existant")):
    with environnement(FauxNotion(), routeur()) as faux_post:
        ns.alerter_coach_onboarding("Sujet fixe", "Message fixe", **kwargs)

    alertes = alertes_envoyees(faux_post)
    check(f"[7] {libelle} : un envoi, event={attendu}", len(alertes) == 1 and alertes[0].get("event") == attendu)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
