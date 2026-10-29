# « Question pour Rony » (decision de Rony du 29/10/2026) : canal direct de
# l'eleve Coaching vers Rony, separe d'Idris. Rony est prevenu sur son
# telephone, repond depuis l'Espace Coach, l'eleve est prevenu a son tour.
#
# - Stockage : une entree « <client> — Question pour Rony — <date> » de
#   [DB] Entrees Portail par question (JSON), rien a creer dans Notion.
# - Coaching seulement (l'Atelier et l'Autonome ont Idris et les points collectifs).

import json
import logging
from datetime import datetime, timezone

from backend.services import notion_service

logger = logging.getLogger(__name__)

NOM_QUESTION_RONY = "Question pour Rony"
MAX_EN_ATTENTE = 3
_MAX_QUESTION = 1500
_MAX_REPONSE = 3000
_TTL = 30


class QuestionInvalide(ValueError):
    pass


class QuestionNonAutorisee(LookupError):
    pass


class TropDeQuestions(ValueError):
    pass


def est_question(page: dict) -> bool:
    nom = notion_service._prop_value(notion_service._prop(page.get("properties", {}), "Nom"))
    return NOM_QUESTION_RONY in str(nom or "")


def ouvert_a(parcours) -> bool:
    return not notion_service._est_parcours_autonome(parcours) and not notion_service._est_parcours_atelier(parcours)


def _lire(page: dict) -> dict:
    brut = notion_service._prop_value(notion_service._prop(page.get("properties", {}), "Données (JSON)")) or "{}"

    try:
        donnees = json.loads(brut)
    except json.JSONDecodeError:
        donnees = {}

    if not isinstance(donnees, dict):
        donnees = {}

    return {
        "id": page["id"],
        "question": str(donnees.get("question") or ""),
        "posee_le": donnees.get("posee_le") or page.get("created_time"),
        "reponse": str(donnees.get("reponse") or "") or None,
        "repondu_le": donnees.get("repondu_le"),
    }


def depuis_entrees(entrees: list[dict]) -> list[dict]:
    """Questions trouvees parmi des entrees deja lues (liste des eleves)."""
    return [_lire(e) for e in entrees if est_question(e)]


def lister(client_page_id: str) -> list[dict]:
    """Questions de l'eleve, de la plus recente a la plus ancienne."""
    cle = f"questions_rony:{client_page_id}"
    en_cache = notion_service._cache_get(cle)

    if en_cache is not None:
        return en_cache

    pages = notion_service._query_data_source(
        notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"and": [
            {"property": "Client", "relation": {"contains": client_page_id}},
            {"property": "Nom", "title": {"contains": NOM_QUESTION_RONY}},
        ]},
    )
    questions = sorted((_lire(p) for p in pages), key=lambda q: q["posee_le"] or "", reverse=True)
    return notion_service._cache_set(cle, questions, _TTL)


def en_attente(questions: list[dict]) -> list[dict]:
    return [q for q in questions if not q["reponse"]]


def _ecrire(page_id: str, question: dict) -> None:
    contenu = json.dumps({
        "version": 1,
        "question": question["question"],
        "posee_le": question["posee_le"],
        "reponse": question["reponse"],
        "repondu_le": question["repondu_le"],
    }, ensure_ascii=False)
    notion_service._update_page(page_id, {
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })


def poser(client_page_id: str, dashboard: dict, question: str) -> dict:
    if not ouvert_a(dashboard.get("parcours")):
        raise QuestionNonAutorisee("Réservé au Coaching.")

    question = str(question or "").strip()[:_MAX_QUESTION]

    if len(question) < 5:
        raise QuestionInvalide("Écris ta question en quelques mots.")

    if len(en_attente(lister(client_page_id))) >= MAX_EN_ATTENTE:
        raise TropDeQuestions("Rony n'a pas encore répondu à tes questions précédentes.")

    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jour = maintenant[:10]
    contenu = json.dumps({"version": 1, "question": question, "posee_le": maintenant, "reponse": None, "repondu_le": None}, ensure_ascii=False)
    page = notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{dashboard.get('nom') or 'Client'} — {NOM_QUESTION_RONY} — {jour}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Date": {"date": {"start": jour}},
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })
    notion_service._cache_clear(f"questions_rony:{client_page_id}")
    return {"id": page.get("id"), "question": question, "posee_le": maintenant, "reponse": None, "repondu_le": None}


def repondre(client_page_id: str, question_id: str, reponse: str) -> dict:
    reponse = str(reponse or "").strip()[:_MAX_REPONSE]

    if not reponse:
        raise QuestionInvalide("Réponse vide.")

    question = next((q for q in lister(client_page_id) if q["id"].replace("-", "") == question_id.replace("-", "")), None)

    if not question:
        raise QuestionNonAutorisee("Question introuvable.")

    question = {**question, "reponse": reponse, "repondu_le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _ecrire(question["id"], question)
    notion_service._cache_clear(f"questions_rony:{client_page_id}")
    return question
