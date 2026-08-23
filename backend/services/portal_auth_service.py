import os

from dotenv import load_dotenv
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY")

MAGIC_LINK_MAX_AGE = 15 * 60  # 15 minutes
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 jours


def _serializer() -> URLSafeTimedSerializer:
    if not SECRET_KEY:
        raise RuntimeError(
            "PORTAL_SECRET_KEY manquant. Renseigne-le dans .env (voir .env.example)."
        )

    return URLSafeTimedSerializer(SECRET_KEY)


def create_magic_link_token(email: str, client_page_id: str) -> str:
    return _serializer().dumps({
        "email": email,
        "client_page_id": client_page_id,
        "type": "magic_link",
    })


def create_session_token(email: str, client_page_id: str) -> str:
    return _serializer().dumps({
        "email": email,
        "client_page_id": client_page_id,
        "type": "session",
    })


def verify_magic_link_token(token: str) -> dict:
    return _verify(token, MAGIC_LINK_MAX_AGE, "magic_link")


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
