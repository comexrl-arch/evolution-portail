# systeme_io_service.py - Integration en lecture avec l'API systeme.io.
#
# Sert uniquement l'espace "Onboarding" du studio agents (main.py, port 8010,
# local) : le coach y recherche un contact systeme.io pour pre-remplir le
# formulaire d'onboarding client, plutot que de retaper nom/email a la main.
# Aucune ecriture dans systeme.io ici, lecture seule.

import os

import requests

SYSTEME_IO_API_BASE = "https://api.systeme.io/api"


def _headers() -> dict:
    api_key = os.getenv("SYSTEME_IO_API_KEY")

    if not api_key:
        raise RuntimeError(
            "SYSTEME_IO_API_KEY manquant. Renseigne-le dans .env (voir .env.example)."
        )

    return {"X-API-Key": api_key, "Accept": "application/json"}


def _field_value(fields: list[dict], slug: str) -> str:
    for field in fields:
        if field.get("slug") == slug:
            return field.get("value") or ""
    return ""


def _simplify_contact(contact: dict) -> dict:
    fields = contact.get("fields", [])

    return {
        "id": contact.get("id"),
        "email": contact.get("email", ""),
        "prenom": _field_value(fields, "first_name"),
        "nom_famille": _field_value(fields, "surname"),
        "telephone": _field_value(fields, "phone_number"),
        "registered_at": contact.get("registeredAt"),
    }


def search_contacts(query: str = "") -> list[dict]:
    params = {"limit": 50, "order": "desc"}

    if query and "@" in query:
        params["email"] = query

    try:
        response = requests.get(
            f"{SYSTEME_IO_API_BASE}/contacts",
            headers=_headers(),
            params=params,
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur systeme.io (contacts) : {error}") from error

    contacts = [_simplify_contact(item) for item in response.json().get("items", [])]

    if query and "@" not in query:
        query_lower = query.lower()
        contacts = [
            c for c in contacts
            if query_lower in c["prenom"].lower() or query_lower in c["nom_famille"].lower()
        ]

    return contacts
