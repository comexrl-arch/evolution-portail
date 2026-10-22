# Brouillons pre-remplis (decision de Rony du 22/10/2026) : sur les fiches de
# redaction (phrase de positionnement, script d'approche), l'IA propose une
# premiere version a partir de ce que le client a deja ecrit dans ses fiches
# precedentes. Rien n'est enregistre : le brouillon arrive dans les champs
# vides, le client le corrige puis enregistre comme d'habitude.

import json
import re
import threading
from datetime import datetime, timezone

from backend.services import ia_service, notion_service
from backend.services.entrainement_service import _contexte_client

_N = notion_service._NUMERO_TO_MASTER_ID

# Numeros internes (ceux de _NUMERO_TO_MASTER_ID) : 9 = offre actuelle,
# 10 = cible prioritaire (affichee 12), 11 = phrase de positionnement
# (affichee 10), 15 = script d'approche (affiche 14).
BROUILLONS = {
    _N["11"]: {
        "champs": ["ma phrase officielle", "ma présentation flash", "ma bio de profil"],
        "sources": [_N["9"], _N["10"]],
        "consigne": """Rédige sa phrase de positionnement et ses déclinaisons.
- « ma phrase officielle » : une seule phrase selon la formule « J'aide [cible] à obtenir [résultat] sans [frustration] grâce à [méthode]. », dite en moins de 10 secondes, centrée sur le résultat pour le client, sans mot technique ni anglais.
- « ma présentation flash » : la version orale de 10 secondes, naturelle, à la première personne.
- « ma bio de profil » : 1 à 2 lignes pour WhatsApp, Facebook ou LinkedIn.""",
    },
    _N["15"]: {
        "champs": ["mon script personnalisé", "ma phrase de relance"],
        "sources": [_N["11"], _N["10"], _N["9"]],
        "consigne": """Rédige son script d'approche.
- « mon script personnalisé » : l'accroche (pourquoi il contacte, avec sa cible et le résultat), une question de qualification sur le problème principal, puis une demande de rendez-vous de 10 minutes avec deux créneaux au choix. Ni prix, ni lien, ni PDF. Vouvoiement, ton simple et chaleureux. Laisse [Prénom] pour le nom du prospect.
- « ma phrase de relance » : un message court de relance à J+3, sans insister lourdement.""",
    },
}

_SYSTEME = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-Evolution) pour des indépendants et TPE des Antilles-Guyane. Ici, tu aides à la rédaction.
Tu proposes un PREMIER JET que le client va corriger avec ses propres mots. Reprends au maximum ses mots et ses idées tirés de ses fiches. N'invente aucun chiffre, aucun client, aucune référence ni promesse chiffrée. Si une information manque, reste général plutôt que d'inventer.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour ni balise de code, dont les clés sont exactement les libellés demandés et les valeurs le texte proposé."""

_MAX_APPELS_JOUR = 15
_compteurs: dict[str, tuple[str, int]] = {}
_verrou = threading.Lock()


def disponible(master_id: str) -> bool:
    return master_id in BROUILLONS and ia_service.enabled()


def _quota_ok(client_page_id: str) -> bool:
    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with _verrou:
        jour_compte, nombre = _compteurs.get(client_page_id, (jour, 0))

        if jour_compte != jour:
            nombre = 0

        if nombre >= _MAX_APPELS_JOUR:
            return False

        _compteurs[client_page_id] = (jour, nombre + 1)
        return True


def _lire_json(texte: str) -> dict:
    # Gemini entoure parfois sa reponse de ```json ... ``` malgre la consigne.
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte.strip())
    debut, fin = texte.find("{"), texte.rfind("}")

    if debut < 0 or fin < debut:
        raise RuntimeError("Brouillon IA illisible")

    try:
        valeurs = json.loads(texte[debut : fin + 1])
    except json.JSONDecodeError:
        raise RuntimeError("Brouillon IA illisible") from None

    if not isinstance(valeurs, dict):
        raise RuntimeError("Brouillon IA illisible")

    return valeurs


def proposer(client_page_id: str, fiches: list[dict], master_id: str, champs: list[dict]) -> dict:
    """Renvoie {"valeurs": {cle_du_champ: texte}} pour les champs a rediger.
    Leve LookupError (fiche sans brouillon), PermissionError (quota)."""
    config = BROUILLONS.get(master_id)

    if not config:
        raise LookupError("Pas de brouillon pour cette fiche")

    cibles = []

    for prefixe in config["champs"]:
        champ = next((c for c in champs if c["libelle"].strip().lower().startswith(prefixe)), None)

        if champ:
            cibles.append((prefixe, champ))

    if not cibles:
        raise LookupError("Aucun champ a rediger")

    if not _quota_ok(client_page_id):
        raise PermissionError("Limite de brouillons atteinte pour aujourd'hui")

    sources = notion_service.reponses_des_fiches(client_page_id, fiches, config["sources"])
    blocs = [_contexte_client(client_page_id)]

    for source in sources:
        lignes = "\n".join(f"- {libelle} {valeur}" for libelle, valeur in source["reponses"])
        blocs.append(f"Ses réponses dans « {source['nom']} » :\n{lignes}")

    if not sources:
        blocs.append("Il n'a pas encore rempli ses fiches précédentes : reste simple et général.")

    libelles = ", ".join(f"« {prefixe} »" for prefixe, _ in cibles)
    demande = "\n\n".join(blocs) + f"\n\n{config['consigne']}\n\nClés JSON attendues : {libelles}."

    valeurs = _lire_json(
        ia_service.generer(_SYSTEME, [{"role": "user", "texte": demande}], temperature=0.7, max_tokens=900)
    )
    valeurs = {str(k).strip().lower(): v for k, v in valeurs.items()}
    resultat = {}

    for prefixe, champ in cibles:
        texte = valeurs.get(prefixe)

        if isinstance(texte, str) and texte.strip():
            resultat[champ["cle"]] = texte.strip()

    if not resultat:
        raise RuntimeError("Brouillon IA vide")

    return {"valeurs": resultat}
