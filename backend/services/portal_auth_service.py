import os
import threading
import time
import uuid

from dotenv import load_dotenv
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY")

MAGIC_LINK_MAX_AGE = 15 * 60  # 15 minutes
# Duree de vie de la session, configurable via PORTAL_SESSION_MAX_AGE_DAYS (defaut 30j).
SESSION_MAX_AGE = int(os.getenv("PORTAL_SESSION_MAX_AGE_DAYS", "30")) * 24 * 60 * 60

# Cycle de vie des jetons de lien magique (issue #4, P0) : un identifiant
# unique (jti) est integre a chaque jeton emis. Deux registres en memoire
# process (pas de base externe - perdus au redemarrage, sans consequence
# puisque les jetons expirent de toute facon au bout de MAGIC_LINK_MAX_AGE) :
# - _active_jti_by_client : le SEUL jeton actuellement valide pour un client.
#   Emettre un nouveau jeton (renvoi/nouvel onboarding) invalide donc
#   automatiquement tout jeton precedent encore non expire pour ce client.
# - _consumed_jti : jetons deja verifies avec succes -> usage unique, un
#   meme lien ne peut pas etre reutilise une seconde fois.
_tokens_lock = threading.Lock()
_active_jti_by_client: dict[str, str] = {}
_consumed_jti: dict[str, float] = {}  # jti -> horodatage de consommation


def _prune_consumed(now: float) -> None:
    # Purge les jti consommes depuis plus de 2x la duree de vie max d'un
    # jeton : ils ne pourraient de toute facon plus etre revalides par
    # itsdangerous (signature+age), inutile de les garder en memoire.
    expired = [jti for jti, consumed_at in _consumed_jti.items() if now - consumed_at > 2 * MAGIC_LINK_MAX_AGE]
    for jti in expired:
        _consumed_jti.pop(jti, None)


def _serializer() -> URLSafeTimedSerializer:
    if not SECRET_KEY:
        raise RuntimeError(
            "PORTAL_SECRET_KEY manquant. Renseigne-le dans .env (voir .env.example)."
        )

    return URLSafeTimedSerializer(SECRET_KEY)


def create_magic_link_token(email: str, client_page_id: str) -> str:
    jti = uuid.uuid4().hex

    with _tokens_lock:
        # Ecrase toute entree existante : un renvoi invalide immediatement
        # l'ancien lien encore non expire pour ce client.
        _active_jti_by_client[client_page_id] = jti

    return _serializer().dumps({
        "email": email,
        "client_page_id": client_page_id,
        "type": "magic_link",
        "jti": jti,
    })


def create_session_token(email: str, client_page_id: str) -> str:
    return _serializer().dumps({
        "email": email,
        "client_page_id": client_page_id,
        "type": "session",
    })


def verify_magic_link_token(token: str) -> dict:
    data = _verify(token, MAGIC_LINK_MAX_AGE, "magic_link")

    jti = data.get("jti")
    client_page_id = data.get("client_page_id")
    now = time.monotonic()

    with _tokens_lock:
        _prune_consumed(now)

        # COMPAT DEPLOIEMENT : un jeton emis AVANT ce changement n'a pas de
        # "jti" (champ absent des jetons signes par l'ancienne version) et
        # est donc rejete ici, meme s'il est encore dans sa fenetre de 15 min
        # naturelle. Consequence concrete : au moment du deploiement, tout
        # lien magique envoye dans les 15 minutes precedentes devient
        # inutilisable un peu plus tot que prevu (il faudra le redemander).
        # Un lien de plus de 15 min est de toute facon deja expire cote
        # itsdangerous, donc l'impact reel se limite a cette fenetre courte.
        # DECISION (Rony, 2026-09-21, PR issue #4) : deployer tel quel est
        # accepte - aucun lien magique n'est en vol au moment du merge. Un
        # client dont le lien recu dans le quart d'heure precedent le
        # deploiement ne fonctionnerait plus devrait simplement en
        # redemander un.
        if not jti or jti in _consumed_jti:
            raise ValueError("Ce lien a deja ete utilise.")

        if _active_jti_by_client.get(client_page_id) != jti:
            raise ValueError("Ce lien n'est plus valide (un lien plus recent a ete envoye).")

        _consumed_jti[jti] = now
        _active_jti_by_client.pop(client_page_id, None)

    return data


def verify_session_token(token: str) -> dict:
    return _verify(token, SESSION_MAX_AGE, "session")


def _verify(token: str, max_age: int, expected_type: str) -> dict:
    try:
        data = _serializer().loads(token, max_age=max_age)

    except SignatureExpired as error:
        raise ValueError("Ce lien a expire.") from error

    except BadSignature as error:
        raise ValueError("Lien invalide.") from error

    if data.get("type") != expected_type:
        raise ValueError("Type de jeton invalide.")

    return data
