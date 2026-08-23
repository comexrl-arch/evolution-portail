# portal_main.py - API FastAPI dediee au Portail Client eVolution 2.0
#
# Backend separe de main.py (agents IA, port 8010) : le portail a son propre
# process/port pour ne jamais risquer d'interrompre le backend agents en
# production lors d'un redemarrage ou d'un crash cote portail.

import os
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.services import notion_service
from backend.services import portal_auth_service


app = FastAPI(
    title="eVolution 2.0 - Portail Client",
    description="API du portail client interactif (auth lien magique + donnees Notion)",
    version="0.1.0",
)

# En dev, PORTAL_ALLOWED_ORIGINS est absent -> fallback localhost. En prod,
# le definir dans .env avec le vrai domaine du frontend (ex. "https://portail.rl-evolution.fr").
_default_origins = "http://localhost:5174,http://127.0.0.1:5174"
_allowed_origins = os.getenv("PORTAL_ALLOWED_ORIGINS", _default_origins).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        raise HTTPException(status_code=503, detail=str(error))


class PortalLoginRequest(BaseModel):
    email: str


@app.post("/portal/auth/request-link")
def portal_request_link(request: PortalLoginRequest):
    generic_response = {
        "status": "sent",
        "message": "Si cet email est enregistre, un lien d'acces a ete envoye.",
    }

    try:
        client = notion_service.find_client_by_email(request.email)

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    if not client:
        return generic_response

    client_nom = notion_service.client_display_name(client)

    try:
        notion_service.send_portal_invite(request.email, client["id"], client_nom)

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return generic_response


class PortalVerifyRequest(BaseModel):
    token: str


@app.post("/portal/auth/verify")
def portal_verify(request: PortalVerifyRequest):
    try:
        data = portal_auth_service.verify_magic_link_token(request.token)

    except ValueError as error:
        raise HTTPException(status_code=401, detail=str(error))

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    session_token = portal_auth_service.create_session_token(
        data["email"], data["client_page_id"]
    )

    return {"status": "verified", "session_token": session_token}


@app.get("/portal/me")
def portal_me(authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return dashboard


@app.get("/portal/fiches/{fiche_id}")
def portal_get_fiche(fiche_id: str, authorization: str = Header(default="")):
    session = _session_from_header(authorization)

    try:
        return notion_service.get_fiche(fiche_id, session["client_page_id"])

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.get("/portal/livrables/{livrable_id}")
def portal_get_livrable(livrable_id: str, authorization: str = Header(default="")):
    _session_from_header(authorization)

    try:
        return notion_service.get_livrable(livrable_id)

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))


class PortalEntryRequest(BaseModel):
    data: dict


@app.post("/portal/fiches/{fiche_id}/entries")
def portal_create_entry(
    fiche_id: str,
    request: PortalEntryRequest,
    authorization: str = Header(default=""),
):
    session = _session_from_header(authorization)

    try:
        dashboard = notion_service.get_client_dashboard(session["client_page_id"])
        entry = notion_service.create_entry(
            fiche_id, session["client_page_id"], dashboard["nom"], request.data
        )

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return {"status": "saved", "entry": entry}


@app.post("/portal/fiches/{fiche_id}/valider")
def portal_valider_fiche(fiche_id: str, authorization: str = Header(default="")):
    _session_from_header(authorization)

    try:
        notion_service.validate_fiche(fiche_id)

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return {"status": "validee"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8013, reload=True)
