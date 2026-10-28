# portal_main.py - API FastAPI dediee au Portail Client eVolution 2.0
#
# Backend separe de main.py (agents IA, port 8010) : le portail a son propre
# process/port pour ne jamais risquer d'interrompre le backend agents en
# production lors d'un redemarrage ou d'un crash cote portail.

import hashlib
import hmac
import logging
import math
import os
import time
from datetime import date, datetime, timezone

import re

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.services import agenda_service
from backend.services import cockpit_service
from backend.services import eleves_service
from backend.services import docuseal_service
from backend.services import bibliotheque_service, brouillon_service, entrainement_service, fidelite_service, idris_service
from backend.services import prospects_service, push_service
from backend.services import login_guard
from backend.services import notion_service
from backend.services import portal_auth_service
from backend.services import request_link_guard
from backend.services import sheets_service
from backend.services import systeme_io_service


app = FastAPI(
    title="eVolution 2.0 - Portail Client",
    description="API du portail client interactif (auth lien magique + donnees Notion)",
    version="0.1.0",
)
# CORS : autorise le frontend Cloudflare Pages en production et Vite en local.
# PORTAL_ALLOWED_ORIGINS peut remplacer la liste par défaut, par exemple :
# https://portail.rl-evolution.fr,https://evolution-portail.pages.dev
_default_origins = [
    "https://portail.rl-evolution.fr",
    "https://evolution-portail.pages.dev",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

_configured_origins = os.getenv("PORTAL_ALLOWED_ORIGINS", "")

_allowed_origins = (
    [origin.strip() for origin in _configured_origins.split(",") if origin.strip()]
    if _configured_origins
    else _default_origins
)

# Autorise les URL de déploiement individuelles de Cloudflare Pages :
# https://<deployment-id>.evolution-portail.pages.dev
_cloudflare_pages_preview_pattern = (
    r"^https://[a-z0-9-]+\.evolution-portail\.pages\.dev$"
)

# Réponses JSON compressées (fiches longues) : moins de données à télécharger.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_cloudflare_pages_preview_pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _journal_duree(request, call_next):
    # Duree de chaque requete dans les logs Render : "PERF 12.3s POST /portal/..."
    debut = time.monotonic()
    response = await call_next(request)
    duree = time.monotonic() - debut

    if request.method != "OPTIONS":
        logging.getLogger("uvicorn.error").info("PERF %.1fs %s %s", duree, request.method, request.url.path)

    return response


# Horodatage calcule une seule fois au chargement du module (donc au demarrage
# du process). Sert a detecter un "process fantome" qui repond encore sur le
# port attendu avec du code perime (deja arrive en verification manuelle :
# un ancien process invisible de tasklist/Get-Process/taskkill continuait de
# repondre sur 8011 avec du code d'avant l'ajout de FICHE_MODULES). Sans ce
# marqueur, /health renvoie toujours la meme reponse statique et ne permet
# pas de distinguer le bon process d'un fantome.
_STARTED_AT = datetime.now(timezone.utc).isoformat()


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "project": "eVolution-Portail-Client",
        "version": "0.1.0",
        "started_at": _STARTED_AT,
        "sheets_sync": sheets_service.enabled(),
        "cockpit_sync": cockpit_service.enabled(),
    }


def _session_from_header(authorization: str) -> dict:
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""

    if not token:
        raise HTTPException(status_code=401, detail="Authorization manquant.")

    try:
        return portal_auth_service.verify_session_token(token)

    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error))

    except RuntimeError as error:
        raise _erreur_service_indisponible("session", error)


class PortalLoginRequest(BaseModel):
    email: str


_MESSAGE_LIEN_INDISPONIBLE = "Le service est momentanément indisponible. Réessaie dans quelques minutes."


def _journaliser_echec_lien(contexte: str, error: Exception, email: str, nom: str = "") -> None:
    # Detail technique de l'echec (nettoye) : logs Render uniquement, jamais dans
    # la reponse HTTP. Pas de trace d'exception (exc_info) : le texte d'une
    # erreur `requests` contient l'URL du webhook n8n. La journalisation ne doit
    # jamais modifier la reponse de la route, meme si elle echoue.
    try:
        _journal_docuseal.error(
            "[request-link] echec contexte=%s ref_email=%s erreur=%s: %s",
            contexte,
            _reference_docuseal(email),
            type(error).__name__,
            _nettoyer_erreur(error, {"email": (email or "").strip().lower(), "nom": nom}),
        )

    except Exception:
        pass


_MESSAGE_SERVICE_INDISPONIBLE = _MESSAGE_LIEN_INDISPONIBLE
_MESSAGE_CLIENT_INTROUVABLE = "Client introuvable."
_MESSAGE_CLIENT_DEJA_EXISTANT = "Un client existe déjà avec cet email."


def _journaliser_erreur_portail(
    contexte: str, error: Exception, infos: dict | None = None, limite: int = 300
) -> None:
    # Detail technique de l'echec (nettoye) : logs Render uniquement, jamais dans
    # la reponse HTTP. `contexte` est un libelle fixe choisi par le code, jamais
    # une donnee venant de la requete. Pas de trace d'exception (exc_info) : le
    # texte d'une erreur `requests` contient des URL. La journalisation ne doit
    # jamais modifier la reponse, meme si elle echoue.
    try:
        _journal_docuseal.error(
            "[portal-error] contexte=%s erreur=%s: %s",
            contexte,
            type(error).__name__,
            _nettoyer_erreur(error, infos, limite),
        )

    except Exception:
        pass


def _erreur_service_indisponible(
    contexte: str, error: Exception, infos: dict | None = None, limite: int = 300
) -> HTTPException:
    _journaliser_erreur_portail(contexte, error, infos, limite)
    return HTTPException(status_code=503, detail=_MESSAGE_SERVICE_INDISPONIBLE)


def _erreur_client_introuvable(contexte: str, error: Exception) -> HTTPException:
    # Pas d'echo de l'identifiant saisi dans la reponse.
    _journaliser_erreur_portail(contexte, error)
    return HTTPException(status_code=404, detail=_MESSAGE_CLIENT_INTROUVABLE)


def _erreur_configuration(contexte: str, nom_variable: str) -> HTTPException:
    # Variable d'environnement absente : 503 generique cote reponse, le nom de la
    # variable (jamais sa valeur) reste dans les logs serveur uniquement.
    _journaliser_erreur_portail(contexte, RuntimeError(f"{nom_variable} manquant"))
    return HTTPException(status_code=503, detail=_MESSAGE_SERVICE_INDISPONIBLE)


def _journaliser_alerte_impossible(contexte: str, error: Exception) -> None:
    # Echec d'une alerte coach en tache de fond : meme format que les autres logs
    # [portal-error], texte nettoye, niveau warning (best-effort). Ne doit jamais
    # lever.
    try:
        _journal_docuseal.warning(
            "[portal-error] contexte=%s erreur=%s: %s",
            contexte,
            type(error).__name__,
            _nettoyer_erreur(error),
        )

    except Exception:
        pass


def _journaliser_filtre_lien(raison: str, email: str) -> None:
    # Demande filtree par la garde : categorie controlee + reference masquee,
    # jamais de donnee brute. Ne doit jamais modifier la reponse de la route.
    try:
        _journal_docuseal.info(
            "[request-link] demande filtree raison=%s ref_email=%s", raison, _reference_docuseal(email)
        )

    except Exception:
        pass


def _envoyer_lien_en_arriere_plan(email: str, client_page_id: str, client_nom: str) -> None:
    # Tache de fond : la reponse HTTP est deja partie, un echec d'envoi ne peut
    # plus la modifier. Toute exception est journalisee (texte nettoye) et
    # capturee : sinon uvicorn journaliserait la trace complete, qui contient
    # l'URL du webhook n8n.
    try:
        notion_service.send_portal_invite(email, client_page_id, client_nom)

    except Exception as error:
        _journaliser_echec_lien("envoi_lien", error, email, client_nom)


@app.post("/portal/auth/request-link")
def portal_request_link(request: PortalLoginRequest, background_tasks: BackgroundTasks):
    generic_response = {
        "status": "sent",
        "message": "Si cet email est enregistré, un lien d'accès a été envoyé.",
    }

    # Garde evaluee AVANT la recherche : meme decision pour tout email, connu ou
    # non. Une demande filtree recoit la meme reponse generique, sans envoi.
    decision = request_link_guard.verifier_et_enregistrer(request.email)

    if not decision.autorise:
        _journaliser_filtre_lien(decision.raison, request.email)
        return generic_response

    try:
        client = notion_service.find_client_by_email(request.email)

    except RuntimeError as error:
        _journaliser_echec_lien("recherche_client", error, request.email)
        raise HTTPException(status_code=503, detail=_MESSAGE_LIEN_INDISPONIBLE)

    if not client:
        return generic_response

    client_nom = notion_service.client_display_name(client)

    # Envoi en tache de fond : la reponse ne depend plus de n8n (statut et delai
    # identiques pour un email connu et inconnu).
    background_tasks.add_task(_envoyer_lien_en_arriere_plan, request.email, client["id"], client_nom)

    return generic_response


class PortalVerifyRequest(BaseModel):
    token: str


_MESSAGE_LIEN_UTILISE = (
    "Ce lien a déjà servi. Connecte-toi avec ton mot de passe, "
    "ou demande un nouveau lien si tu l'as oublié."
)


def _client_du_lien(token: str) -> tuple[dict, dict]:
    # Lien recu par email (ouverture de l'espace ou mot de passe oublie) : il
    # ne sert qu'a definir le mot de passe, et une seule fois.
    try:
        data = portal_auth_service.verify_magic_link_token(token)

    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error))

    except RuntimeError as error:
        raise _erreur_service_indisponible("verify", error)

    try:
        client = notion_service.get_client_page(data["client_page_id"])

    except RuntimeError as error:
        raise _erreur_service_indisponible("verify_client", error)

    if portal_auth_service.lien_deja_utilise(data, notion_service.client_password_hash(client)):
        raise HTTPException(status_code=401, detail=_MESSAGE_LIEN_UTILISE)

    return data, client


@app.post("/portal/auth/verify")
def portal_verify(request: PortalVerifyRequest):
    # Verifie le lien avant d'afficher l'ecran "Cree ton mot de passe" : aucune
    # session n'est ouverte ici.
    data, client = _client_du_lien(request.token)

    return {
        "status": "verified",
        "email": data["email"],
        "nom": notion_service.client_display_name(client),
        "mot_de_passe_existant": portal_auth_service.mot_de_passe_defini(
            notion_service.client_password_hash(client)
        ),
    }


class PortalSetPasswordRequest(BaseModel):
    token: str
    password: str


@app.post("/portal/auth/set-password")
def portal_set_password(request: PortalSetPasswordRequest):
    refus = portal_auth_service.erreur_mot_de_passe(request.password)

    if refus:
        raise HTTPException(status_code=400, detail=refus)

    data, _ = _client_du_lien(request.token)

    try:
        empreinte = portal_auth_service.hash_password(request.password)
        notion_service.definir_mot_de_passe_client(data["client_page_id"], empreinte)

    except RuntimeError as error:
        raise _erreur_service_indisponible("set_password", error)

    login_guard.reinitialiser(data["email"])
    session_token = portal_auth_service.create_session_token(data["email"], data["client_page_id"])
    notion_service.log_portal_connection(data["email"], data["client_page_id"])

    return {"status": "password_set", "session_token": session_token}


class PortalPasswordLoginRequest(BaseModel):
    email: str
    password: str


_MESSAGE_IDENTIFIANTS_INVALIDES = "Email ou mot de passe incorrect."
_MESSAGE_TROP_DE_TENTATIVES = (
    "Trop de tentatives. Réessaie dans quelques minutes, "
    "ou utilise « Mot de passe oublié »."
)


@app.post("/portal/auth/login")
def portal_login(request: PortalPasswordLoginRequest):
    email = (request.email or "").strip().lower()

    # Garde evaluee AVANT la recherche : meme decision pour un email connu ou non.
    if login_guard.bloque(email):
        _journaliser_filtre_lien("login_bloque", email)
        raise HTTPException(status_code=429, detail=_MESSAGE_TROP_DE_TENTATIVES)

    try:
        client = notion_service.find_client_by_email(email) if email else None

    except RuntimeError as error:
        raise _erreur_service_indisponible("login", error)

    # Meme reponse (et meme duree de calcul) pour un email inconnu, un compte
    # sans mot de passe et un mauvais mot de passe.
    stocke = notion_service.client_password_hash(client) if client else ""

    if not portal_auth_service.verify_password(request.password or "", stocke) or not client:
        login_guard.enregistrer_echec(email)
        raise HTTPException(status_code=401, detail=_MESSAGE_IDENTIFIANTS_INVALIDES)

    login_guard.reinitialiser(email)
    session_token = portal_auth_service.create_session_token(email, client["id"])
    notion_service.log_portal_connection(email, client["id"])

    return {"status": "verified", "session_token": session_token}


def _exiger_fiche_ouverte(dashboard: dict, fiche_id: str) -> None:
    # Verrou cote serveur : un client ne peut ni enregistrer ni valider une
    # fiche qui n'est pas la sienne ou qui est encore bloquee (jour pas
    # atteint, fiche precedente non terminee, verrou coach de la fiche 8).
    cible = fiche_id.replace("-", "")

    for fiche in dashboard.get("fiches", []):
        if (fiche.get("id") or "").replace("-", "") == cible:
            if "Bloqué" in (fiche.get("acces") or ""):
                raise HTTPException(status_code=403, detail="Cette fiche n'est pas encore ouverte.")
            return

    raise HTTPException(status_code=403, detail="Fiche inconnue pour ce client.")


def _fiche_du_client(dashboard: dict, fiche_id: str) -> dict:
    # Lecture : la fiche doit appartenir au client (404 sinon, on ne confirme
    # pas l'existence chez un autre client) et etre ouverte (403 sinon).
    cible = fiche_id.replace("-", "")

    for fiche in dashboard.get("fiches", []):
        if (fiche.get("id") or "").replace("-", "") == cible:
            if "Bloqué" in (fiche.get("acces") or ""):
                raise HTTPException(status_code=403, detail="Cette fiche n'est pas encore ouverte.")
            return fiche

    raise HTTPException(status_code=404, detail="Fiche introuvable.")


@app.get("/portal/me")
def portal_me(authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_me", error)

    return dashboard


@app.get("/portal/fiches/{fiche_id}")
def portal_get_fiche(fiche_id: str, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        fiche = _fiche_du_client(dashboard, fiche_id)
        resultat = notion_service.get_fiche(fiche["id"], session["client_page_id"])
        resultat["brouillon_ia"] = brouillon_service.disponible(fiche.get("master_id"))
        return resultat

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_get_fiche", error)


@app.post("/portal/fiches/{fiche_id}/brouillon")
def portal_brouillon_fiche(fiche_id: str, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        _exiger_fiche_ouverte(dashboard, fiche_id)
        fiche = _fiche_du_client(dashboard, fiche_id)
        master_id = fiche.get("master_id")
        champs = notion_service._champs_for(notion_service.FICHE_SCHEMAS[master_id], master_id)
        return brouillon_service.proposer(session["client_page_id"], dashboard.get("fiches", []), master_id, champs)

    except (LookupError, KeyError):
        raise HTTPException(status_code=404, detail="Pas de brouillon pour cette fiche.")

    except PermissionError:
        raise HTTPException(status_code=429, detail="Limite de brouillons atteinte pour aujourd'hui.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_brouillon_fiche", error)


@app.get("/portal/livrables/{livrable_id}")
def portal_get_livrable(livrable_id: str, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        return notion_service.get_livrable(livrable_id, dashboard)

    except notion_service.LivrableNonAutorise:
        # Levee uniquement quand le livrable a ete lu mais n'est pas autorise.
        raise HTTPException(status_code=404, detail="Livrable introuvable.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_get_livrable", error)


class PortalEntryRequest(BaseModel):
    data: dict


@app.post("/portal/fiches/{fiche_id}/entries")
def portal_create_entry(
    fiche_id: str,
    request: PortalEntryRequest,
    authorization: str = Header(default=""),
    background_tasks: BackgroundTasks = None,
):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        _exiger_fiche_ouverte(dashboard, fiche_id)
        entry = notion_service.create_entry(
            fiche_id, session["client_page_id"], dashboard["nom"], request.data
        )

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_create_entry", error)

    if background_tasks is not None:
        background_tasks.add_task(_recalculer_fiche8, session["client_page_id"], fiche_id)
        background_tasks.add_task(_reporter_bilans_kpi, session["client_page_id"], fiche_id)
        background_tasks.add_task(_demander_retour_ia, fiche_id, (entry or {}).get("id"), session["client_page_id"])
    return {"status": "saved", "entry": entry}


def _demander_retour_ia(fiche_id: str, entry_id: str | None, client_page_id: str | None = None) -> None:
    # Tache de fond, best-effort : met la saisie en file pour le retour IA.
    try:
        if notion_service.demander_retour_ia(fiche_id, entry_id):
            if notion_service.generer_retour_ia_immediat(entry_id) and client_page_id:
                # Autonome : retour visible tout de suite, on previent le telephone.
                try:
                    push_service.retour_idris_pret(client_page_id, fiche_id)
                except Exception as error:
                    _journaliser_alerte_impossible("push_retour_ia", error)
    except Exception as error:
        # L'entree reste "À générer" : le workflow n8n prendra le relais.
        _journaliser_alerte_impossible("retour_ia", error)


def _reporter_bilans_kpi(client_page_id: str, fiche_id: str) -> None:
    # Tache de fond, best-effort : un bilan hebdomadaire met a jour les KPI
    # RDV et Nouveaux clients du tableau de bord.
    try:
        notion_service.reporter_bilans_dans_kpi(client_page_id, fiche_id)
    except Exception as error:
        _journaliser_alerte_impossible("kpi_bilans", error)


def _recalculer_fiche8(client_page_id: str, fiche_id: str) -> None:
    # Tache de fond, best-effort : une reponse de diagnostic modifiee apres
    # coup met a jour la fiche 8 automatique (parcours Autonome).
    try:
        notion_service.recalculer_fiche8_autonome(client_page_id, fiche_id)
    except Exception as error:
        _journaliser_alerte_impossible("fiche8_recalcul", error)


def _alerter_si_diagnostic_termine(client_page_id: str, fiche_id: str) -> None:
    # Tache de fond : previent le coach quand le client vient de terminer ses
    # 5 fiches de diagnostic. Best-effort, ne bloque jamais la validation.
    try:
        infos = notion_service.diagnostic_vient_de_se_terminer(client_page_id, fiche_id)

        if not infos:
            return

        if notion_service._est_parcours_autonome(infos.get("parcours")):
            # Autonome : pas de coach, la fiche 8 se remplit et se valide seule.
            try:
                notion_service.remplir_fiche8_autonome(client_page_id)
            except Exception as error:
                _journaliser_alerte_impossible("fiche8_autonome", error)
            return

        notion_service.alerter_coach_diagnostic(infos["client_nom"], infos["client_email"])

    except Exception as error:
        _journaliser_alerte_impossible("alerte_diagnostic", error)


def _alerter_si_bonus_termine(client_page_id: str, fiche_id: str) -> None:
    try:
        infos = notion_service.bonus_vient_de_se_terminer(client_page_id, fiche_id)

        if infos and infos["resultat"]:
            notion_service.alerter_coach_bonus(infos["client_nom"], infos["resultat"])

    except Exception as error:
        _journaliser_alerte_impossible("alerte_bonus", error)


@app.post("/portal/fiches/{fiche_id}/valider")
def portal_valider_fiche(
    fiche_id: str, background_tasks: BackgroundTasks, authorization: str = Header(default="")
):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        _exiger_fiche_ouverte(dashboard, fiche_id)
        deja_terminee = any(
            f["id"].replace("-", "") == fiche_id.replace("-", "") and f.get("etat") == "Terminé"
            for f in dashboard["fiches"]
        )
        notion_service.validate_fiche(fiche_id)

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_valider_fiche", error)

    if not deja_terminee:
        background_tasks.add_task(_alerter_si_diagnostic_termine, session["client_page_id"], fiche_id)
        background_tasks.add_task(_alerter_si_bonus_termine, session["client_page_id"], fiche_id)

    # Renvoie directement le tableau de bord a jour : le portail n'a plus a
    # refaire un second appel /portal/me juste apres la validation.
    try:
        tableau = notion_service.get_client_dashboard(session["client_page_id"])
    except RuntimeError:
        tableau = None

    return {"status": "validee", "dashboard": tableau}


class PortalKpiRequest(BaseModel):
    valeurs: dict


@app.post("/portal/kpi/{kpi_id}")
def portal_update_kpi(kpi_id: str, request: PortalKpiRequest, authorization: str = Header(default="")):
    # Saisie des valeurs et objectifs KPI par le client lui-meme, depuis le
    # tableau de bord. Le client ne peut modifier que ses propres indicateurs.
    session = _session_from_header(authorization)
    valeurs = request.valeurs or {}

    if not valeurs or any(cle not in notion_service.KPI_CHAMPS_SAISISSABLES for cle in valeurs):
        raise HTTPException(status_code=400, detail="Champ KPI inconnu.")

    for valeur in valeurs.values():
        if valeur is None:
            continue

        if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) or not math.isfinite(valeur) or valeur < 0:
            raise HTTPException(status_code=400, detail="Tes chiffres doivent être des nombres positifs.")

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        kpi = next(
            (k for k in dashboard.get("kpi") or [] if k["id"].replace("-", "") == kpi_id.replace("-", "")),
            None,
        )

        if not kpi:
            raise HTTPException(status_code=404, detail="Indicateur introuvable.")

        notion_service.update_kpi(kpi["id"], valeurs, etat_actuel=kpi.get("etat"))
        tableau = notion_service.get_client_dashboard(session["client_page_id"])

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_update_kpi", error)

    return {"status": "enregistre", "dashboard": tableau}


# --- Espace Onboarding Coach (mobile) : protege par un code d'acces simple,
# distinct de l'auth client par lien magique. Cree de vrais clients dans
# Notion, donc jamais accessible sans ce code. ---

def _require_coach_key(x_coach_key: str) -> None:
    expected = os.getenv("COACH_ONBOARD_KEY")

    if not expected:
        raise _erreur_configuration("coach_cle_manquante", "COACH_ONBOARD_KEY")

    # Comparaison a temps constant : meme resultat qu'une egalite simple.
    if not hmac.compare_digest(x_coach_key.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Code d'accès invalide.")


def _require_diagnostic_api_key(authorization: str) -> None:
    # Cle technique dediee a la lecture consolidee du diagnostic (endpoint
    # consomme par l'assistant de synthese de la fiche 8), distincte du code
    # d'acces de l'Espace Coach (COACH_ONBOARD_KEY / X-Coach-Key) et de l'auth
    # client par lien magique. Passee en header "Authorization: Bearer <cle>".
    expected = os.getenv("COACH_DIAGNOSTIC_API_KEY")

    if not expected:
        raise _erreur_configuration("coach_diagnostic_cle_manquante", "COACH_DIAGNOSTIC_API_KEY")

    token = authorization.removeprefix("Bearer ").strip() if authorization else ""

    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Clé API invalide.")


@app.get("/coach/diagnostics")
def coach_diagnostics(x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return {"diagnostics": notion_service.list_diagnostics_fiche8()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_diagnostics", error)


@app.get("/coach/diagnostic-rapport/{client_page_id}")
def coach_diagnostic_rapport(client_page_id: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return notion_service.get_diagnostic_rapport(client_page_id)

    except LookupError as error:
        raise _erreur_client_introuvable("coach_diagnostic_rapport", error)

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_diagnostic_rapport", error)


@app.get("/coach/bonus/{client_page_id}")
def coach_bonus(client_page_id: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return notion_service.get_bonus_resultat(client_page_id) or {}

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_bonus", error)


@app.get("/coach/diagnostic/{client_id}")
def coach_diagnostic_bundle(client_id: str, authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return notion_service.get_coach_diagnostic_bundle(client_id)

    except LookupError as error:
        raise _erreur_client_introuvable("coach_diagnostic_bundle", error)

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_diagnostic_bundle", error)


@app.get("/coach/fiches/{fiche_client_id}")
def coach_get_fiche(
    fiche_client_id: str, client_page_id: str, x_coach_key: str = Header(default="")
):
    _require_coach_key(x_coach_key)

    try:
        return notion_service.get_fiche(fiche_client_id, client_page_id)

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_get_fiche", error)


@app.get("/coach/fiches/{fiche_client_id}/diagnostic-champs")
def coach_get_diagnostic_champs(fiche_client_id: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return {
            "champs": notion_service.get_diagnostic_fiche8(fiche_client_id),
            "mis_a_jour": notion_service._derniere_maj_blocs(fiche_client_id),
        }

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_get_diagnostic_champs", error)


class DiagnosticUpdate(BaseModel):
    block_id: str
    type: str
    label: str
    valeur: str


class DiagnosticUpdateRequest(BaseModel):
    updates: list[DiagnosticUpdate]


@app.post("/coach/fiches/{fiche_client_id}/diagnostic-champs")
def coach_update_diagnostic_champs(
    fiche_client_id: str, request: DiagnosticUpdateRequest, x_coach_key: str = Header(default="")
):
    _require_coach_key(x_coach_key)

    try:
        notion_service.update_diagnostic_fiche8([u.model_dump() for u in request.updates])

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_update_diagnostic_champs", error)

    return {"status": "mis a jour"}


@app.post("/coach/fiches/{fiche_client_id}/valider")
def coach_valider_fiche(fiche_client_id: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        notion_service.validate_fiche(fiche_client_id)

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_valider_fiche", error)

    return {"status": "validee"}


# --- Parcours Autonome : syntheses mensuelles (workflow n8n). Meme cle
# technique que /coach/diagnostic (Authorization: Bearer COACH_DIAGNOSTIC_API_KEY). ---

class SyntheseAutonomeRequest(BaseModel):
    client_page_id: str
    mois: int
    axe: str
    texte: str
    nb_fiches_terminees: int = 0
    email: str = ""


class SyntheseStatutRequest(BaseModel):
    statut: str


@app.get("/automation/autonome/syntheses-dues")
def automation_syntheses_dues(authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return {"clients": notion_service.clients_autonome_synthese_due()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_syntheses_dues", error)


@app.post("/automation/autonome/syntheses")
def automation_enregistrer_synthese(request: SyntheseAutonomeRequest, authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        synthese_id = notion_service.enregistrer_synthese_autonome(
            request.client_page_id, request.mois, request.axe, request.texte, request.nb_fiches_terminees,
            email=request.email,
        )

    except ValueError:
        raise HTTPException(status_code=422, detail="Axe ou statut de synthèse invalide.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_enregistrer_synthese", error)

    return {"synthese_id": synthese_id}


@app.post("/automation/autonome/syntheses/{synthese_id}/statut")
def automation_statut_synthese(
    synthese_id: str, request: SyntheseStatutRequest, authorization: str = Header(default="")
):
    _require_diagnostic_api_key(authorization)

    if request.statut not in ("Envoyée", "Bloquée"):
        raise HTTPException(status_code=422, detail="Statut attendu : Envoyée ou Bloquée.")

    try:
        notion_service.changer_statut_synthese(synthese_id, request.statut)

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_statut_synthese", error)

    return {"status": "mis a jour"}


# --- Entrainement aux objections (IA interactive, Gemini direct) ---

class EntrainementRequest(BaseModel):
    scenario: str
    messages: list[dict] = []
    terminer: bool = False


@app.get("/portal/entrainement/scenarios")
def portal_entrainement_scenarios(authorization: str = Header(default="")):
    _session_from_header(authorization)

    # Sans cle Gemini, aucun scenario : le bloc d'entrainement reste masque.
    if not entrainement_service.ia_service.enabled():
        return {"scenarios": []}

    return {"scenarios": [{"id": cle, "titre": s["titre"]} for cle, s in entrainement_service.SCENARIOS.items()]}


@app.post("/portal/entrainement")
def portal_entrainement(request: EntrainementRequest, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        return entrainement_service.repondre(
            session["client_page_id"], request.scenario, request.messages, request.terminer
        )

    except ValueError:
        raise HTTPException(status_code=422, detail="Scénario ou conversation invalide.")

    except PermissionError:
        raise HTTPException(status_code=429, detail="Limite d'entraînements atteinte pour aujourd'hui.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_entrainement", error)


# --- Idris au quotidien : questions, messages, preparation de RDV (lot 2) ---

class IdrisQuestionRequest(BaseModel):
    messages: list[dict] = []


class IdrisMessageRequest(BaseModel):
    type: str
    precision: str = ""


class IdrisRdvRequest(BaseModel):
    prospect: str
    besoin: str = ""
    objectif: str = ""


def _appel_idris(nom: str, fonction, *args):
    # Erreurs communes aux 3 fonctions d'Idris, sans jamais exposer le detail.
    try:
        return fonction(*args)

    except LookupError:
        raise HTTPException(status_code=403, detail="Cette fonction est incluse dans le Coaching 90 jours.")

    except ValueError:
        raise HTTPException(status_code=422, detail="Demande invalide.")

    except PermissionError:
        raise HTTPException(status_code=429, detail="Limite atteinte : reviens plus tard.")

    except RuntimeError as error:
        raise _erreur_service_indisponible(nom, error)


def _dashboard_idris(authorization: str) -> tuple[dict, dict]:
    session = _session_from_header(authorization)

    try:
        return session, notion_service.get_client_dashboard(session["client_page_id"])
    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_idris", error)


@app.get("/portal/idris")
def portal_idris_etat(authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return idris_service.etat(session["client_page_id"], dashboard)


@app.post("/portal/idris/question")
def portal_idris_question(request: IdrisQuestionRequest, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return _appel_idris("portal_idris_question", idris_service.repondre_question, session["client_page_id"], dashboard, request.messages)


@app.post("/portal/idris/message")
def portal_idris_message(request: IdrisMessageRequest, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return _appel_idris("portal_idris_message", idris_service.rediger_message, session["client_page_id"], dashboard, request.type, request.precision)


@app.post("/portal/idris/rdv")
def portal_idris_rdv(request: IdrisRdvRequest, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return _appel_idris(
        "portal_idris_rdv", idris_service.preparer_rdv, session["client_page_id"], dashboard, request.prospect, request.besoin, request.objectif
    )


@app.post("/portal/bilan-j90")
def portal_bilan_j90(authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)

    try:
        return idris_service.rediger_bilan_j90(session["client_page_id"], dashboard)

    except LookupError:
        raise HTTPException(status_code=403, detail="Ton bilan J90 s'ouvre à partir de J80.")

    except PermissionError:
        raise HTTPException(status_code=429, detail="Limite atteinte : reviens plus tard.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_bilan_j90", error)


# --- Lot 4 : bibliotheque, accueil guide, partage, avis J90, recap hebdo ---

class PersonnaliserModeleRequest(BaseModel):
    modele: str
    metier: str | None = None


class ObjectifRequest(BaseModel):
    objectif: str


class AvisJ90Request(BaseModel):
    note: int
    avis: str
    accord_publication: bool = False
    signature: str = ""


@app.get("/portal/bibliotheque")
def portal_bibliotheque(metier: str | None = None, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return bibliotheque_service.bibliotheque(session["client_page_id"], dashboard, metier)


@app.post("/portal/bibliotheque/personnaliser")
def portal_bibliotheque_personnaliser(request: PersonnaliserModeleRequest, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    return _appel_idris(
        "portal_bibliotheque_personnaliser", bibliotheque_service.personnaliser, session["client_page_id"], dashboard, request.modele, request.metier
    )


@app.post("/portal/objectif")
def portal_objectif(request: ObjectifRequest, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        return {"objectif_90j": fidelite_service.enregistrer_objectif(session["client_page_id"], request.objectif)}

    except ValueError:
        raise HTTPException(status_code=422, detail="Écris ton objectif en une ou deux phrases.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_objectif", error)


@app.post("/portal/partage")
def portal_creer_partage(authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        return fidelite_service.creer_lien_partage(session["client_page_id"])

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_partage", error)


@app.get("/public/partage")
def public_partage(jeton: str):
    try:
        client_page_id = fidelite_service.client_du_partage(jeton)

    except ValueError:
        raise HTTPException(status_code=404, detail="Ce lien de partage n'est plus valable.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("public_partage", error)

    try:
        return fidelite_service.progression_publique(notion_service.get_client_dashboard(client_page_id))

    except RuntimeError as error:
        raise _erreur_service_indisponible("public_partage", error)


@app.post("/portal/avis-j90")
def portal_avis_j90(request: AvisJ90Request, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)

    try:
        fidelite_service.enregistrer_avis(
            session["client_page_id"], dashboard, request.note, request.avis, request.accord_publication, request.signature
        )

    except LookupError:
        raise HTTPException(status_code=403, detail="Ton avis s'ouvre avec ton bilan J90.")

    except ValueError:
        raise HTTPException(status_code=422, detail="Avis invalide.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_avis_j90", error)

    return {"status": "merci"}


# --- Carnet de prospects (27/10/2026) ---------------------------------------

class ProspectRequest(BaseModel):
    action: str
    id: str | None = None
    prospect: dict | None = None


@app.get("/portal/prospects")
def portal_prospects(authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)

    try:
        return prospects_service.vue_client(prospects_service.lire(session["client_page_id"], dashboard))

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_prospects", error)


@app.post("/portal/prospects")
def portal_prospects_action(request: ProspectRequest, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)

    try:
        carnet = prospects_service.appliquer(
            session["client_page_id"], dashboard.get("nom"), dashboard, request.action, request.id, request.prospect
        )

    except LookupError:
        raise HTTPException(status_code=404, detail="Ce prospect n'est plus dans ton carnet.")

    except prospects_service.CarnetInvalide as error:
        raise HTTPException(status_code=422, detail=error.message_client)

    except ValueError:
        raise HTTPException(status_code=422, detail="Cette modification n'a pas pu être enregistrée.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_prospects_action", error)

    return prospects_service.vue_client(carnet)


# --- Passerelle Autonome vers Coaching (27/10/2026) ---------------------------

@app.post("/portal/passerelle-coaching")
def portal_passerelle_coaching(background_tasks: BackgroundTasks, authorization: str = Header(default="")):
    session, dashboard = _dashboard_idris(authorization)
    passerelle = dashboard.get("passerelle_coaching")

    if not passerelle:
        raise HTTPException(status_code=403, detail="Proposition non disponible.")

    bilan = next((f for f in dashboard.get("fiches") or [] if f.get("master_id") == notion_service._BILAN_HEBDO_MASTER_ID), None)
    identite = dashboard.get("identite") or {}

    def alerter():
        try:
            historique = notion_service._historique_bilans(bilan["id"]) if bilan else []
            notion_service.alerter_coach_passerelle(dashboard.get("nom"), identite.get("email"), identite.get("telephone"), {
                "jour": (dashboard.get("rythme") or {}).get("jour"),
                "fiches_terminees": sum(1 for f in dashboard.get("fiches") or [] if f.get("etat") == "Terminé"),
                "fiches_total": len(dashboard.get("fiches") or []),
                "en_retard": passerelle.get("en_retard"),
                "semaine": historique[-1] if historique else None,
                "objectif": dashboard.get("objectif_90j"),
            })
        except Exception as error:
            _journaliser_alerte_impossible("passerelle_coaching", error)

    background_tasks.add_task(alerter)
    return {"url": passerelle["url"]}


# --- Notifications sur le telephone (27/10/2026) -------------------------------

class PushAbonnementRequest(BaseModel):
    abonnement: dict


class PushDesabonnementRequest(BaseModel):
    endpoint: str


@app.get("/portal/push/cle")
def portal_push_cle(authorization: str = Header(default="")):
    _session_from_header(authorization)
    return {"cle": push_service.cle_publique() if push_service.enabled() else None}


@app.post("/portal/push/abonnement")
def portal_push_abonner(request: PushAbonnementRequest, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    if not push_service.enabled():
        raise HTTPException(status_code=404, detail="Notifications indisponibles.")

    try:
        push_service.abonner(session["client_page_id"], request.abonnement)

    except ValueError:
        raise HTTPException(status_code=422, detail="Abonnement invalide.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_push_abonner", error)

    return {"status": "abonne"}


@app.post("/portal/push/desabonnement")
def portal_push_desabonner(request: PushDesabonnementRequest, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        push_service.desabonner(session["client_page_id"], request.endpoint)

    except RuntimeError as error:
        raise _erreur_service_indisponible("portal_push_desabonner", error)

    return {"status": "desabonne"}


@app.post("/automation/notifications-du-jour")
def automation_notifications_du_jour(authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return push_service.notifications_du_jour()

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_notifications_du_jour", error)


@app.get("/automation/recap-hebdo")
def automation_recap_hebdo(authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return {"recaps": fidelite_service.recaps_hebdo()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_recap_hebdo", error)


# --- Retours IA sur les fiches (workflow n8n + Gemini), meme cle technique. ---

class RetourIARequest(BaseModel):
    texte: str
    autonome: bool = False


@app.get("/automation/retours-ia/a-generer")
def automation_retours_ia_a_generer(authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return {"retours": notion_service.retours_ia_a_generer()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_retours_ia_a_generer", error)


@app.post("/automation/retours-ia/{entry_id}")
def automation_enregistrer_retour_ia(entry_id: str, request: RetourIARequest, authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        statut = notion_service.enregistrer_retour_ia(entry_id, request.texte, request.autonome)

    except ValueError:
        raise HTTPException(status_code=422, detail="Texte du retour vide.")

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_enregistrer_retour_ia", error)

    return {"statut": statut}


# --- Relances intelligentes (workflow n8n quotidien), meme cle technique. ---

@app.get("/automation/relances-dues")
def automation_relances_dues(authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        return {"relances": notion_service.relances_dues()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_relances_dues", error)


@app.post("/automation/relances/{client_page_id}")
def automation_relance_envoyee(client_page_id: str, authorization: str = Header(default="")):
    _require_diagnostic_api_key(authorization)

    try:
        notion_service.marquer_relance_envoyee(client_page_id)

    except RuntimeError as error:
        raise _erreur_service_indisponible("automation_relance_envoyee", error)

    return {"status": "relance enregistree"}


@app.get("/coach/suivi-clients")
def coach_suivi_clients(x_coach_key: str = Header(default="")):
    # Onglet "Suivi client" : lecture seule de "Suivi clients" du cockpit Google
    # Sheets. Uniquement les champs de la fiche (voir cockpit_service) : ni email,
    # ni notes, ni montants, ni autre onglet.
    _require_coach_key(x_coach_key)

    if not cockpit_service.enabled():
        raise _erreur_configuration("coach_suivi_clients", "COCKPIT_SPREADSHEET_ID")

    try:
        return {"clients": cockpit_service.lire_suivi_clients()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_suivi_clients", error)


@app.get("/coach/eleves")
def coach_eleves(x_coach_key: str = Header(default="")):
    # Onglet "Eleves" : ce que chaque eleve fait dans son espace client, lu
    # dans Notion comme le portail (voir eleves_service). Lecture seule.
    _require_coach_key(x_coach_key)

    try:
        return {"eleves": eleves_service.liste()}

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_eleves", error)


@app.get("/coach/eleves/{client_page_id}")
def coach_eleve_detail(client_page_id: str, frais: bool = False, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return eleves_service.detail(client_page_id, frais=frais)

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_eleve_detail", error)


# --- Agenda de l'Espace Coach (28/10/2026) : le Google Agenda de Rony. Seuls
# les evenements crees depuis le portail sont modifiables (agenda_service). ---

class AgendaEvenement(BaseModel):
    type: str = "rdv"
    eleve_id: str | None = None
    eleve_nom: str | None = None
    titre: str | None = None
    description: str | None = None
    lieu: str | None = None
    debut: str
    fin: str


class AgendaModification(BaseModel):
    type: str | None = None
    eleve_id: str | None = None
    eleve_nom: str | None = None
    titre: str | None = None
    description: str | None = None
    lieu: str | None = None
    debut: str | None = None
    fin: str | None = None


_JOUR_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _agenda_config(raison: str = "a_configurer") -> dict:
    # Etat "a brancher" : l'onglet affiche la marche a suivre. raison vaut
    # "a_configurer" (GOOGLE_CALENDAR_ID absent) ou "acces_refuse" (Google
    # refuse l'agenda : pas encore partage, ou mauvais identifiant).
    return {
        "configure": False,
        "raison": raison,
        "acces": agenda_service.mode_acces(),
        "compte_de_service": agenda_service.compte_de_service(),
        "calendrier": agenda_service.calendrier_configure(),
    }


def _agenda_erreur(contexte: str, error: Exception) -> HTTPException:
    if isinstance(error, agenda_service.AgendaInaccessible):
        _journaliser_erreur_portail(contexte, error)
        return HTTPException(status_code=403, detail="Votre Google Agenda n'est pas encore accessible : finissez le réglage indiqué dans l'onglet Agenda.")
    if isinstance(error, agenda_service.EvenementIntrouvable):
        return HTTPException(status_code=404, detail="Rendez-vous introuvable dans l'agenda.")
    if isinstance(error, agenda_service.EvenementProtege):
        return HTTPException(status_code=403, detail="Ce rendez-vous n'a pas été créé depuis l'Espace Coach : modifiez-le dans Google Agenda.")
    if isinstance(error, agenda_service.CreneauInvalide):
        return HTTPException(status_code=422, detail=error.message)
    return _erreur_service_indisponible(contexte, error)


@app.get("/coach/agenda")
def coach_agenda(debut: str, fin: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    if not (_JOUR_ISO.match(debut) and _JOUR_ISO.match(fin)) or fin <= debut:
        raise HTTPException(status_code=422, detail="Période invalide.")

    if not agenda_service.enabled():
        return {**_agenda_config(), "evenements": []}

    try:
        return {"configure": True, "fuseau": agenda_service.fuseau(), "evenements": agenda_service.lister(debut, fin)}

    except agenda_service.AgendaInaccessible as error:
        _journaliser_erreur_portail("coach_agenda", error)
        return {**_agenda_config("acces_refuse"), "evenements": []}

    except (RuntimeError, ValueError) as error:
        raise _agenda_erreur("coach_agenda", error)


@app.get("/coach/agenda/prochains")
def coach_agenda_prochains(depuis: str, x_coach_key: str = Header(default="")):
    # Prochain RDV ou suivi de chaque eleve (cartes de l'onglet Eleves).
    _require_coach_key(x_coach_key)

    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", depuis):
        raise HTTPException(status_code=422, detail="Date invalide.")

    if not agenda_service.enabled():
        return {"configure": False, "prochains": {}}

    # Simple pastille sur les cartes eleves : jamais d'erreur, au pire rien.
    try:
        return {"configure": True, "prochains": agenda_service.prochains(depuis)}

    except Exception as error:
        _journaliser_erreur_portail("coach_agenda_prochains", error)
        return {"configure": False, "prochains": {}}


@app.post("/coach/agenda")
def coach_agenda_creer(evenement: AgendaEvenement, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    if evenement.type not in agenda_service.TYPES:
        raise HTTPException(status_code=422, detail="Type de rendez-vous inconnu.")

    if not agenda_service.enabled():
        raise _erreur_configuration("coach_agenda_creer", "GOOGLE_CALENDAR_ID")

    try:
        return agenda_service.creer(evenement.model_dump())

    except (RuntimeError, ValueError) as error:
        raise _agenda_erreur("coach_agenda_creer", error)


@app.patch("/coach/agenda/{evenement_id}")
def coach_agenda_modifier(evenement_id: str, modification: AgendaModification, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    if modification.type is not None and modification.type not in agenda_service.TYPES:
        raise HTTPException(status_code=422, detail="Type de rendez-vous inconnu.")

    if not agenda_service.enabled():
        raise _erreur_configuration("coach_agenda_modifier", "GOOGLE_CALENDAR_ID")

    try:
        return agenda_service.modifier(evenement_id, modification.model_dump(exclude_unset=True))

    except (RuntimeError, ValueError) as error:
        raise _agenda_erreur("coach_agenda_modifier", error)


@app.delete("/coach/agenda/{evenement_id}")
def coach_agenda_supprimer(evenement_id: str, x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    if not agenda_service.enabled():
        raise _erreur_configuration("coach_agenda_supprimer", "GOOGLE_CALENDAR_ID")

    try:
        agenda_service.supprimer(evenement_id)

    except RuntimeError as error:
        raise _agenda_erreur("coach_agenda_supprimer", error)

    return {"supprime": True}


@app.get("/coach/leads/systeme-io")
def coach_leads_systeme_io(query: str = "", x_coach_key: str = Header(default="")):
    _require_coach_key(x_coach_key)

    try:
        return {"leads": systeme_io_service.search_contacts(query)}

    except RuntimeError as error:
        raise _erreur_service_indisponible("coach_leads_systeme_io", error, {"email": query, "nom": query})


class CoachClientOnboardRequest(BaseModel):
    nom: str
    email: str
    activite: str = ""
    secteur: str = ""
    territoire: str = ""
    contact: str = ""
    telephone: str = ""
    site_reseaux: str = ""
    offre_principale: str = ""
    parcours: str = ""
    client_cible: str = ""
    objectif_90j: str = ""
    urgence_echeance: str = ""
    leads_j0: float | None = None
    rdv_j0: float | None = None
    nouveaux_clients_j0: float | None = None
    ca_j0: float | None = None


@app.post("/coach/clients/onboard")
def coach_onboard_client(
    request: CoachClientOnboardRequest, x_coach_key: str = Header(default="")
):
    _require_coach_key(x_coach_key)

    data = request.model_dump(exclude={"nom", "email"})
    kpi_j0 = {
        "leads_j0": data.pop("leads_j0"),
        "rdv_j0": data.pop("rdv_j0"),
        "nouveaux_clients_j0": data.pop("nouveaux_clients_j0"),
        "ca_j0": data.pop("ca_j0"),
    }

    try:
        result = notion_service.onboard_client(request.nom, request.email, kpi_j0=kpi_j0, **data)

    except notion_service.ClientDejaExistant:
        # Cas metier, pas une panne : 409 + code stable. Le message de
        # l'exception (email, identifiant de page Notion) n'est ni renvoye ni
        # journalise : reference masquee uniquement.
        _journal_docuseal.warning(
            "[portal] onboarding refuse contexte=coach_onboard_client raison=client_deja_existant ref=%s",
            _reference_docuseal(request.email),
        )
        return JSONResponse(
            status_code=409,
            content={"detail": _MESSAGE_CLIENT_DEJA_EXISTANT, "code": "client_deja_existant"},
        )

    except RuntimeError as error:
        # Rollback, pages orphelines et detail utile : logs uniquement (limite elargie
        # pour conserver la liste des pages a archiver a la main).
        raise _erreur_service_indisponible(
            "coach_onboard_client",
            error,
            {"nom": request.nom, "email": request.email, "telephone": request.telephone},
            limite=1500,
        )

    return result


# --- Contrat signe dans DocuSeal -> creation automatique du client et envoi
# du lien d'acces. DocuSeal appelle cette adresse a chaque contrat termine,
# avec l'en-tete secret X-Webhook-Secret (= DOCUSEAL_WEBHOOK_SECRET). ---

_DOCUSEAL_PARCOURS = {
    "6159080": "Atelier",
    "6152105": "Coaching 90 jours",
}

# form.completed part a chaque signataire. Les deux modeles ont un signataire
# "Coach" (Rony) : sa signature n'est pas celle d'un nouveau client.
_DOCUSEAL_ROLES_IGNORES = {"coach"}


def _docuseal_signature_coach(payload: dict) -> bool:
    data = (payload or {}).get("data")
    role = str(data.get("role") or "").strip().lower() if isinstance(data, dict) else ""
    return (payload or {}).get("event_type") == "form.completed" and role in _DOCUSEAL_ROLES_IGNORES


def _docuseal_valeur(values: list, *mots: str) -> str:
    for item in values or []:
        champ = str((item or {}).get("field") or "").lower()
        valeur = (item or {}).get("value")

        if valeur in (None, "", False, True) or not isinstance(valeur, (str, int, float)):
            continue

        if any(mot in champ for mot in mots):
            return str(valeur).strip()

    return ""


def _docuseal_date_iso(texte: str) -> str:
    texte = (texte or "").strip()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", texte)

    if match:
        return match.group(0)

    match = re.search(r"(\d{1,2})[/.\- ](\d{1,2})[/.\- ](\d{4})", texte)

    if match:
        jour, mois, annee = match.groups()
        return f"{annee}-{int(mois):02d}-{int(jour):02d}"

    return ""


def _docuseal_date_session(values: list) -> str:
    # Atelier : "Date de la session 1" (champ du coach), au format AAAA-MM-JJ,
    # ou "" si absente ou impossible (ex. 31/02).
    texte = _docuseal_date_iso(_docuseal_valeur(values, "session 1", "date de la session", "champ de date"))

    try:
        date.fromisoformat(texte)
    except ValueError:
        return ""

    return texte


def _docuseal_soumission_id(payload: dict) -> str:
    data = (payload or {}).get("data")
    data = data if isinstance(data, dict) else {}
    soumission = data.get("submission") if isinstance(data.get("submission"), dict) else {}
    valeur = soumission.get("id") or data.get("submission_id")
    return str(valeur) if isinstance(valeur, int) or str(valeur or "").isdigit() else ""


def _docuseal_session_coach(payload: dict) -> tuple[str, str] | None:
    # Signature du coach sur un contrat Atelier portant la date de la session 1 :
    # (identifiant de soumission, date) a reporter chez le participant.
    data = (payload or {}).get("data")
    data = data if isinstance(data, dict) else {}
    modele = data.get("template") if isinstance(data.get("template"), dict) else {}

    if _DOCUSEAL_PARCOURS.get(str(modele.get("id") or "")) != "Atelier":
        return None

    date_iso = _docuseal_date_session(data.get("values") or [])
    submission_id = _docuseal_soumission_id(payload)
    return (submission_id, date_iso) if date_iso and submission_id else None


def _docuseal_extraire(payload: dict) -> dict | None:
    if (payload or {}).get("event_type") != "form.completed":
        return None

    data = payload.get("data") or {}
    template_id = str((data.get("template") or {}).get("id") or "")
    parcours = _DOCUSEAL_PARCOURS.get(template_id)
    email = str(data.get("email") or "").strip().lower()

    if not parcours or not email:
        return None

    values = data.get("values") or []
    nom = _docuseal_valeur(values, "nom", "raison sociale") or str(data.get("name") or "").strip() or email

    return {
        "nom": nom,
        "email": email,
        "parcours": parcours,
        "telephone": _docuseal_valeur(values, "téléphone", "telephone") or str(data.get("phone") or "").strip(),
        "date_demarrage": _docuseal_date_session(values) if parcours == "Atelier" else "",
        "completed_at": str(data.get("completed_at") or "").strip(),
        "modalite_paiement": _docuseal_valeur(values, "paiement", "règlement", "reglement", "modalit"),
    }


_journal_docuseal = logging.getLogger("uvicorn.error")  # visible dans les logs Render


def _champ_log(valeur, limite: int = 40) -> str:
    # Valeur venant du payload DocuSeal : jamais injectee telle quelle dans un
    # log. On neutralise tout caractere inattendu (retours a la ligne, etc.) et
    # on tronque.
    return re.sub(r"[^\w.\-]", "?", str(valeur or ""))[:limite] or "?"


def _masquer_email(email: str) -> str:
    local, _, domaine = (email or "").strip().lower().partition("@")
    return f"{local[:1]}***@{domaine}" if local and domaine else "***"


def _reference_docuseal(email: str) -> str:
    # Email masque + empreinte courte : permet de rapprocher plusieurs lignes
    # de log d'un meme client sans donnee personnelle exploitable.
    empreinte = hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()[:8]
    return f"{_masquer_email(email)}#{empreinte}"


_STRUCTURE_FERMEE = re.compile(r"\{[^{}]*\}")  # structure {...} sans accolade imbriquee
_NETTOYAGE_PASSES_MAX = 20


def _nettoyer_erreur(texte, infos: dict | None = None, limite: int = 300) -> str:
    # Retire d'un texte d'erreur tout ce qui ne doit pas finir dans un log :
    # payload serialise, identite du client (nom, meme court, email, telephone),
    # URL (avec ou sans schema), hote et chemin des erreurs de connexion,
    # adresses email. Tronque a `limite` caracteres (300 par defaut). Reserve aux logs : ce texte
    # n'est jamais repris dans une alerte coach.
    texte = str(texte or "")

    # Payload serialise (repr ou JSON) : les structures {...} sont remplacees par
    # <donnees> en commencant par les plus internes, puis on repete (une
    # structure imbriquee disparait entierement, de l'interieur vers
    # l'exterieur) ; le texte qui suit une structure fermee est conserve. Le
    # nombre de passes est borne. Pour une accolade jamais refermee (ou si la
    # borne est atteinte), tout ce qui suit la premiere accolade restante est
    # masque : aucune fuite possible, aucune boucle sans fin.
    for _ in range(_NETTOYAGE_PASSES_MAX):
        texte, remplacements = _STRUCTURE_FERMEE.subn("<donnees>", texte)

        if not remplacements:
            break

    texte = re.sub(r"\{.*", "<donnees>", texte, flags=re.DOTALL)

    for cle in ("email", "nom", "telephone"):
        valeur = str((infos or {}).get(cle) or "").strip()

        if not valeur:
            continue

        if len(valeur) >= 3:
            motif = re.escape(valeur)
        else:
            # Nom court (1 ou 2 caracteres) : mot entier uniquement, pour ne pas
            # alterer « livraison » ni « L'entreprise » en masquant leurs lettres.
            motif = rf"(?<!\w){re.escape(valeur)}(?![\w'’])"

        texte = re.sub(motif, "<masque>", texte, flags=re.IGNORECASE)

    texte = re.sub(r"https?://\S+", "<url>", texte)
    texte = re.sub(r"host='[^']*'", "host=<hote>", texte)
    texte = re.sub(r"(?i)\burl:\s*\S+", "url: <url>", texte)
    texte = re.sub(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", "<email>", texte)
    return texte[:limite]


def _docuseal_alerter(sujet: str, lignes: list[str], event: str = "onboarding_docuseal_echec") -> None:
    # Best-effort : rien ne doit sortir de la tache de fond, quelle que soit
    # l'erreur de l'alerte. On ne logue que la classe de l'exception.
    try:
        notion_service.alerter_coach_onboarding(sujet, "\n".join(lignes), event=event)

    except Exception as error:
        _journal_docuseal.warning("[docuseal] alerte coach impossible (%s)", type(error).__name__)


def _cockpit_onboarding(infos: dict, client_notion: bool, acces_envoye: bool) -> None:
    # Reporte le resultat de l'onboarding dans le cockpit (Suivi clients AF/AG).
    # Best-effort : un echec est journalise sans alerte, car le cockpit affiche
    # deja l'action « Vérifier la création du client dans Notion » au coach.
    if not cockpit_service.enabled():
        return

    ref = _reference_docuseal(infos["email"])

    try:
        resultat = cockpit_service.marquer_onboarding(
            infos["email"], client_notion, cockpit_service.aujourd_hui() if acces_envoye else None,
        )
        _journal_docuseal.info("[cockpit] onboarding reporte resultat=%s ref=%s", resultat, ref)

    except Exception as error:
        _journal_docuseal.warning(
            "[cockpit] onboarding non reporte ref=%s erreur=%s: %s",
            ref, type(error).__name__, _nettoyer_erreur(error, infos),
        )


def _docuseal_onboard(infos: dict) -> None:
    ref = _reference_docuseal(infos["email"])
    parcours = infos.get("parcours")

    try:
        resultat = notion_service.onboard_client(
            infos["nom"], infos["email"], kpi_j0={},
            parcours=infos["parcours"], telephone=infos["telephone"],
            date_demarrage=infos["date_demarrage"],
        )

    except notion_service.ClientDejaExistant:
        _journal_docuseal.warning(
            "[docuseal] onboarding ignore, client deja existant parcours=%s ref=%s", parcours, ref
        )
        # Alerte assainie : evenement, reference masquee et parcours uniquement
        # (ni nom, ni email, ni identifiant de page Notion).
        _docuseal_alerter("Contrat DocuSeal signé : client déjà existant", [
            "Un contrat DocuSeal a été signé pour un email déjà associé à un client.",
            "Aucun nouveau dossier n'a été créé.",
            "Événement : docuseal_client_deja_existant",
            f"Référence : {ref}",
            f"Parcours : {parcours}",
        ], event="docuseal_client_deja_existant")
        _cockpit_onboarding(infos, client_notion=True, acces_envoye=False)
        return

    except Exception as error:  # Notion indisponible, rollback, bug, etc.
        # Le detail technique (nettoye) reste dans les logs Render uniquement.
        _journal_docuseal.error(
            "[docuseal] onboarding echoue parcours=%s ref=%s erreur=%s: %s",
            parcours, ref, type(error).__name__, _nettoyer_erreur(error, infos),
        )
        _docuseal_alerter("Onboarding DocuSeal échoué", [
            "Un contrat DocuSeal est signé, mais le client n'a pas pu être créé automatiquement.",
            "Cause technique : création automatique interrompue.",
            "Événement : onboarding_docuseal_echec",
            f"Référence : {ref}",
            f"Parcours : {parcours}",
        ])
        return

    if not (resultat or {}).get("invite_envoyee"):
        _journal_docuseal.error(
            "[docuseal] client cree mais lien d'acces non envoye parcours=%s ref=%s erreur=%s",
            parcours, ref, _nettoyer_erreur((resultat or {}).get("invite_erreur"), infos),
        )
        _docuseal_alerter("Onboarding DocuSeal : lien d'accès non envoyé", [
            "Le client a été créé dans Notion, mais son lien d'accès n'a pas été envoyé.",
            "Cause technique : lien d'accès non envoyé.",
            "Le client peut demander un nouveau lien depuis la page de connexion.",
            "Événement : onboarding_docuseal_echec",
            f"Référence : {ref}",
            f"Parcours : {parcours}",
        ])
        _cockpit_onboarding(infos, client_notion=True, acces_envoye=False)
        return

    _journal_docuseal.info(
        "[docuseal] onboarding OK parcours=%s ref=%s fiches=%s kpi=%s",
        parcours, ref, resultat.get("fiches_creees"), resultat.get("kpi_crees"),
    )
    _cockpit_onboarding(infos, client_notion=True, acces_envoye=True)


def _cockpit_signature(infos: dict) -> None:
    # Tache de fond independante de l'onboarding Notion : le contrat est signe,
    # il doit apparaitre dans le cockpit meme si Notion echoue. Best-effort :
    # aucune erreur ne remonte, le coach est alerte.
    ref = _reference_docuseal(infos["email"])
    parcours = infos.get("parcours")

    try:
        resultat = cockpit_service.enregistrer_signature(infos)

    except Exception as error:
        if isinstance(error, cockpit_service.NomDejaPris):
            cause = "nom de client déjà utilisé par un autre client"
        elif isinstance(error, cockpit_service.CockpitPlein):
            cause = "plus de ligne libre dans le cockpit"
        else:
            cause = "écriture dans le cockpit interrompue"

        _journal_docuseal.error(
            "[cockpit] signature non reportee parcours=%s ref=%s erreur=%s: %s",
            parcours, ref, type(error).__name__, _nettoyer_erreur(error, infos),
        )
        _docuseal_alerter("Cockpit : contrat signé non reporté", [
            "Un contrat DocuSeal est signé, mais il n'a pas pu être ajouté au cockpit.",
            f"Cause : {cause}.",
            "Événement : cockpit_signature_echec",
            f"Référence : {ref}",
            f"Parcours : {parcours}",
        ], event="cockpit_signature_echec")
        return

    _journal_docuseal.info("[cockpit] signature reportee resultat=%s parcours=%s ref=%s", resultat, parcours, ref)


def _docuseal_lire_session(submission_id: str) -> tuple[str, str]:
    # Relit la soumission DocuSeal : (email du participant, date de la session 1
    # saisie par le coach). Chaine vide pour une donnee absente.
    soumission = docuseal_service.lire_soumission(submission_id)
    email, date_iso = "", ""

    for signataire in soumission.get("submitters") or []:
        if not isinstance(signataire, dict):
            continue

        role = str(signataire.get("role") or "").strip().lower()

        if role in _DOCUSEAL_ROLES_IGNORES:
            date_iso = date_iso or _docuseal_date_session(signataire.get("values") or [])
        elif not email:
            email = str(signataire.get("email") or "").strip().lower()

    return email, date_iso


def _docuseal_completer_date(infos: dict, submission_id: str) -> None:
    # Participant Atelier sans date de session 1 (champ du coach) : si le coach
    # a deja signe, on la reprend de la soumission. Tache planifiee avant le
    # cockpit et l'onboarding, qui lisent ensuite infos["date_demarrage"].
    ref = _reference_docuseal(infos["email"])

    try:
        _email, date_iso = _docuseal_lire_session(submission_id)

    except Exception as error:
        _journal_docuseal.warning("[docuseal] date session 1 non lue ref=%s erreur=%s", ref, type(error).__name__)
        return

    if date_iso:
        infos["date_demarrage"] = date_iso
        _journal_docuseal.info("[docuseal] date session 1 reprise du coach ref=%s", ref)


# Le coach signe souvent juste apres le participant, pendant l'onboarding
# Notion de celui-ci (une vingtaine d'appels) : on reessaie quelques fois.
_SESSION_ATTENTES = (0, 20, 40, 60)  # secondes


def _docuseal_reporter_session(submission_id: str, date_iso: str) -> None:
    # Signature du coach (Atelier) : reporte la date de la session 1 dans le
    # cockpit (Contrats!D) et sur la fiche Notion du participant (Date de
    # demarrage, J0 du parcours). Best-effort, logs uniquement.
    if not docuseal_service.enabled():
        _journal_docuseal.warning("[docuseal] date session 1 non reportee : DOCUSEAL_API_KEY absente")
        return

    try:
        email, _date = _docuseal_lire_session(submission_id)

    except Exception as error:
        _journal_docuseal.warning("[docuseal] date session 1 non reportee : soumission illisible (%s)", type(error).__name__)
        return

    if not email:
        _journal_docuseal.warning("[docuseal] date session 1 non reportee : participant sans email")
        return

    ref = _reference_docuseal(email)
    cibles = {"notion": lambda: notion_service.definir_date_demarrage(email, date_iso)}

    if cockpit_service.enabled():
        cibles["cockpit"] = lambda: cockpit_service.reporter_demarrage(email, date.fromisoformat(date_iso))

    for attente in _SESSION_ATTENTES:
        if not cibles:
            return

        if attente:
            time.sleep(attente)

        for cible, reporter in list(cibles.items()):
            try:
                resultat = reporter()

            except Exception as error:
                _journal_docuseal.warning(
                    "[docuseal] date session 1 non reportee cible=%s ref=%s erreur=%s: %s",
                    cible, ref, type(error).__name__, _nettoyer_erreur(error, {"email": email}),
                )
                del cibles[cible]
                continue

            if resultat != "absent":
                _journal_docuseal.info("[docuseal] date session 1 cible=%s resultat=%s ref=%s", cible, resultat, ref)
                del cibles[cible]

    for cible in cibles:
        _journal_docuseal.warning("[docuseal] date session 1 non reportee cible=%s ref=%s : client introuvable", cible, ref)


def _docuseal_signaler_non_reconnu(payload: dict) -> None:
    # form.completed recu mais sans template connu ou sans email exploitable :
    # un contrat signe reste sans client. Warning + alerte coach (best-effort).
    # Ni nom ni email en clair, dans le log comme dans l'alerte.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    modele = data.get("template") if isinstance(data.get("template"), dict) else {}
    template_id = str(modele.get("id") or "")
    email = str(data.get("email") or "").strip().lower()
    raison = "template_inconnu" if template_id not in _DOCUSEAL_PARCOURS else "email_absent"
    evenement = _champ_log(payload.get("event_type"))
    template = _champ_log(template_id, 40)
    reference = _reference_docuseal(email) if email else "sans-email"

    _journal_docuseal.warning(
        "[docuseal] contrat signe non reconnu event=%s template=%s raison=%s ref=%s",
        evenement, template, raison, reference,
    )
    _docuseal_alerter("Contrat DocuSeal signé non reconnu", [
        "Un contrat DocuSeal a été signé mais n'a pas pu être rattaché à un parcours.",
        f"Événement : {evenement}",
        f"Template : {template}",
        f"Raison : {raison}",
        f"Référence : {reference}",
    ])


@app.post("/webhooks/docuseal")
def webhook_docuseal(
    payload: dict, background_tasks: BackgroundTasks, x_webhook_secret: str = Header(default="")
):
    expected = os.getenv("DOCUSEAL_WEBHOOK_SECRET")

    if not expected:
        _journal_docuseal.error("[docuseal] webhook refuse : secret serveur non configure")
        raise HTTPException(status_code=503, detail=_MESSAGE_SERVICE_INDISPONIBLE)

    if x_webhook_secret != expected:
        _journal_docuseal.warning("[docuseal] webhook refuse : secret invalide")
        raise HTTPException(status_code=401, detail="Secret invalide.")

    if _docuseal_signature_coach(payload):
        session = _docuseal_session_coach(payload)

        if session:
            # Atelier : seule la date de la session 1, saisie par le coach, est
            # reportee chez le participant (ni onboarding, ni nouvelle ligne).
            background_tasks.add_task(_docuseal_reporter_session, *session)
            _journal_docuseal.info("[docuseal] signature coach : date session 1 a reporter")
            return {"status": "accepte", "raison": "date_session"}

        # Ni onboarding, ni cockpit, ni alerte : seul le signataire client compte.
        modele = (payload.get("data") or {}).get("template")
        template = _champ_log((modele or {}).get("id") if isinstance(modele, dict) else "", 40)
        _journal_docuseal.info("[docuseal] signature coach ignoree template=%s", template)
        return {"status": "ignore", "raison": "signature_coach"}

    infos = _docuseal_extraire(payload)

    if not infos:
        if (payload or {}).get("event_type") == "form.completed":
            background_tasks.add_task(_docuseal_signaler_non_reconnu, payload)

        return {"status": "ignore"}

    submission_id = _docuseal_soumission_id(payload)

    if infos["parcours"] == "Atelier" and not infos["date_demarrage"] and submission_id and docuseal_service.enabled():
        # Avant tout le reste : complete infos["date_demarrage"] si le coach a
        # deja signe (sa date de session 1 n'est pas dans ce webhook).
        background_tasks.add_task(_docuseal_completer_date, infos, submission_id)

    # Le cockpit d'abord (les taches de fond s'executent dans l'ordre) : la
    # ligne du client existe ainsi quand l'onboarding y reporte AF/AG.
    if cockpit_service.enabled():
        background_tasks.add_task(_cockpit_signature, infos)

    # L'onboarding enchaine une vingtaine d'appels Notion : on repond tout de
    # suite a DocuSeal et on cree le client en arriere-plan.
    background_tasks.add_task(_docuseal_onboard, infos)

    return {"status": "accepte", "parcours": infos["parcours"]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8013, reload=True)
