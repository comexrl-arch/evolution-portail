# Appels directs a Gemini pour les fonctions interactives du portail
# (entrainement aux objections, brouillons). Les traitements differes
# (retours IA, relances, syntheses) passent par n8n ; ici le client attend la
# reponse, d'ou l'appel direct. Cle : GEMINI_API_KEY (variable Render), la
# meme que celle du credential n8n "Gemini API Key — RL Evolution".

import os

import requests

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def generer(systeme: str, echanges: list[dict], temperature: float = 0.6, max_tokens: int = 600) -> str:
    """echanges : [{"role": "user" | "model", "texte": "..."}], dans l'ordre."""
    cle = os.getenv("GEMINI_API_KEY")

    if not cle:
        raise RuntimeError("GEMINI_API_KEY manquante : IA interactive indisponible.")

    corps = {
        "systemInstruction": {"parts": [{"text": systeme}]},
        "contents": [{"role": e["role"], "parts": [{"text": e["texte"]}]} for e in echanges],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }

    try:
        response = requests.post(
            _URL.format(modele=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")),
            headers={"x-goog-api-key": cle},
            json=corps,
            timeout=30,
        )
        response.raise_for_status()
        candidats = response.json().get("candidates") or []
        texte = "".join(part.get("text", "") for part in candidats[0]["content"]["parts"]).strip() if candidats else ""
    except (requests.RequestException, KeyError, IndexError, ValueError) as error:
        # Jamais l'URL ni la cle dans le message : seulement le type d'erreur.
        raise RuntimeError(f"Gemini indisponible ({type(error).__name__})") from None

    if not texte:
        raise RuntimeError("Gemini n'a renvoye aucun texte")

    return texte
