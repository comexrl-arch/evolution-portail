# Appels directs a Gemini pour les fonctions interactives du portail
# (entrainement aux objections, brouillons). Les traitements differes
# (retours IA, relances, syntheses) passent par n8n ; ici le client attend la
# reponse, d'ou l'appel direct. Cle : GEMINI_API_KEY (variable Render), la
# meme que celle du credential n8n "Gemini API Key — RL Evolution".

import os
import re

import requests

_URL = "https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"

# Charte d'ecriture de Rony (skill rl-style-humain, demande du 26/10/2026) :
# ajoutee a tous les prompts d'Idris, ceux d'ici comme ceux envoyes a n8n.
_MARQUE_STYLE = "STYLE D'ÉCRITURE (charte RL-eVolution)"
STYLE_HUMAIN = f"""{_MARQUE_STYLE}
- Écris comme une vraie personne, pas comme une IA : comme Rony parlerait à quelqu'un autour d'un café, simple, direct, chaleureux, cash et bienveillant. On doit comprendre en 30 secondes. Garde le tutoiement ou le vouvoiement demandé plus haut.
- Alterne phrases courtes et moyennes. Une idée par paragraphe, aucune répétition.
- Jamais de tiret cadratin ni demi-cadratin (— ou –) : mets un point, une virgule ou deux-points.
- Pas d'emoji, presque pas de gras, un point d'exclamation au maximum, une question rhétorique au maximum.
- Évite les séries de trois adjectifs et les tournures en miroir (« ce n'est pas X, c'est Y »).
- Formules interdites : « Dans un monde où », « Imagine », « Et si je te disais », « Voici pourquoi », « Plongeons », « Décortiquons », « Mais ce n'est pas tout », « En effet », « Par ailleurs », « En résumé », « En conclusion », « Au final », « La clé, c'est », « N'oublie pas », « N'hésite pas à ».
- Mots interdits : véritable, réellement, incroyable, puissant, essentiel, crucial, incontournable, honnêtement, franchement, révolutionnaire, game-changer, mindset, scaler, funnel, flou.
- Préfère un détail concret du terrain antillais (WhatsApp, bouche-à-oreille, saison haute ou basse, clientèle locale) à une généralité, sans jamais inventer de chiffre, de témoignage ni de cas.
- La marque s'écrit RL-eVolution."""


def avec_style(systeme: str) -> str:
    return systeme if _MARQUE_STYLE in systeme else f"{systeme.rstrip()}\n\n{STYLE_HUMAIN}"


def humaniser(texte: str) -> str:
    """Filet de securite si le modele glisse quand meme des tirets longs."""
    texte = re.sub(r"^[ \t]*[—–][ \t]*", "- ", texte, flags=re.MULTILINE)
    texte = re.sub(r"[ \t]+[—–][ \t]+", ", ", texte)
    texte = re.sub(r"[—–]", "-", texte)
    return re.sub(r"RL[- ]?[Ee]volution", "RL-eVolution", texte)


def enabled() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def generer(systeme: str, echanges: list[dict], temperature: float = 0.6, max_tokens: int = 600, style: bool = True) -> str:
    """echanges : [{"role": "user" | "model", "texte": "..."}], dans l'ordre.
    style=False pour un role qui n'est pas Idris (le prospect du jeu de role)."""
    cle = os.getenv("GEMINI_API_KEY")

    if not cle:
        raise RuntimeError("GEMINI_API_KEY manquante : IA interactive indisponible.")

    corps = {
        "systemInstruction": {"parts": [{"text": avec_style(systeme) if style else systeme}]},
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

    return humaniser(texte)
