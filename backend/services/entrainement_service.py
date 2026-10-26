# Entrainement aux objections (decision de Rony du 22/10/2026) : l'IA joue un
# prospect des Antilles-Guyane qui oppose une objection, le client repond,
# puis l'IA (en coach) lui fait un retour. Rien n'est enregistre.

import threading
from datetime import datetime, timezone

from backend.services import ia_service, notion_service

SCENARIOS = {
    "trop_cher": {"titre": "« C'est trop cher »", "objection": "Le prospect trouve le prix trop élevé par rapport à ce qu'il imagine."},
    "reflechir": {"titre": "« Je vais réfléchir »", "objection": "Le prospect ne dit ni oui ni non et veut « réfléchir », sans dire à quoi."},
    "deja_quelquun": {"titre": "« J'ai déjà quelqu'un »", "objection": "Le prospect a déjà un prestataire ou fait lui-même et ne voit pas pourquoi changer."},
    "pas_le_temps": {"titre": "« Pas le temps »", "objection": "Le prospect dit qu'il est débordé et n'a pas le temps d'en parler maintenant."},
    "envoyez_doc": {"titre": "« Envoyez-moi une plaquette »", "objection": "Le prospect demande une documentation par e-mail pour écourter l'échange."},
}

_MAX_TOURS_CLIENT = 6
_MAX_APPELS_JOUR = 40
_compteurs: dict[str, tuple[str, int]] = {}
_verrou = threading.Lock()


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


def _contexte_client(client_page_id: str) -> str:
    props = notion_service._get_page(client_page_id).get("properties", {})
    valeur = lambda nom: notion_service._prop_value(notion_service._prop(props, nom))
    lignes = [
        f"Activité du client : {valeur('Activité')}" if valeur("Activité") else None,
        f"Son offre principale : {valeur('Offre Principale')}" if valeur("Offre Principale") else None,
        f"Sa clientèle cible : {valeur('Client Cible')}" if valeur("Client Cible") else None,
        f"Territoire : {valeur('Territoire')}" if valeur("Territoire") else None,
    ]
    return "\n".join(ligne for ligne in lignes if ligne) or "Activité du client : non précisée (reste général)."


def _systeme_prospect(scenario: dict, contexte: str) -> str:
    return f"""Tu joues un prospect réaliste des Antilles-Guyane (Guadeloupe, Martinique ou Guyane) dans un jeu de rôle commercial. L'utilisateur est un indépendant qui s'entraîne à te vendre son offre.

CONTEXTE DE L'UTILISATEUR
{contexte}

TON RÔLE
- Tu es un client potentiel crédible pour cette activité. Objection de départ : {scenario['objection']}
- Réponds comme à l'oral : 1 à 3 phrases, naturel, vouvoiement ou tutoiement selon ce que l'utilisateur emploie, sans jargon.
- Ne cède pas trop vite : si sa réponse est faible, relance avec une nouvelle hésitation crédible. Si elle est vraiment convaincante (écoute, question, reformulation, preuve, prochaine étape claire), montre-toi plus ouvert.
- Reste toujours dans le rôle, ne donne jamais de conseil et ne commente jamais l'exercice.
- Au premier message, présente-toi en une phrase (prénom, situation) et exprime l'objection."""


_SYSTEME_COACH = """Tu es Idris, l'assistant IA et coach commercial du programme eVolution 2.0 (RL-eVolution). Tu viens d'observer un jeu de rôle où l'utilisateur (un indépendant des Antilles-Guyane) répondait à une objection d'un prospect joué par une IA.

Fais-lui un retour en français, en le tutoyant, chaleureux et concret, 120 à 180 mots, sans markdown ni titre :
1. Ce qu'il a bien fait (cite une de ses phrases).
2. Le point principal à améliorer, avec la technique utile (écouter et reformuler, poser une question pour comprendre la vraie raison, ramener à la valeur et au résultat, proposer une prochaine étape précise).
3. Une phrase qu'il pourrait dire mot pour mot la prochaine fois, adaptée à son activité.
N'invente aucun chiffre ni fait sur son activité."""


def repondre(client_page_id: str, scenario_id: str, messages: list[dict], terminer: bool = False) -> dict:
    """messages : [{"role": "prospect" | "client", "texte": ...}]. Renvoie
    {"role": "prospect", "texte"} pour continuer, ou {"role": "coach", "texte"}
    pour le retour final."""
    scenario = SCENARIOS.get(scenario_id)

    if not scenario:
        raise ValueError("Scénario inconnu")

    if len(messages) > 2 * _MAX_TOURS_CLIENT + 1 or any(len(m.get("texte") or "") > 800 for m in messages):
        raise ValueError("Conversation trop longue")

    if not _quota_ok(client_page_id):
        raise PermissionError("Limite d'entraînements atteinte pour aujourd'hui")

    tours_client = sum(1 for m in messages if m.get("role") == "client")
    contexte = _contexte_client(client_page_id)

    if terminer or tours_client >= _MAX_TOURS_CLIENT:
        transcription = "\n".join(
            f"{'Prospect' if m.get('role') == 'prospect' else 'Utilisateur'} : {m.get('texte')}" for m in messages
        )
        texte = ia_service.generer(
            _SYSTEME_COACH,
            [{"role": "user", "texte": f"{contexte}\nObjection travaillée : {scenario['titre']}\n\nÉchange :\n{transcription}"}],
            temperature=0.5,
            max_tokens=700,
        )
        return {"role": "coach", "texte": texte}

    # Cote Gemini, le prospect est le modele et le client l'utilisateur.
    echanges = [{"role": "user", "texte": "Commence la conversation."}]
    echanges += [
        {"role": "model" if m.get("role") == "prospect" else "user", "texte": m.get("texte") or ""}
        for m in messages
    ]
    texte = ia_service.generer(_systeme_prospect(scenario, contexte), echanges, temperature=0.8, max_tokens=250, style=False)
    return {"role": "prospect", "texte": texte}
