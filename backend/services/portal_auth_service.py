import base64
import hashlib
import hmac
import os
import secrets
import time

from dotenv import load_dotenv
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY")

# Le lien envoye par email (ouverture de l'espace ou mot de passe oublie) sert
# uniquement a creer le mot de passe : il reste valable 48 h pour laisser au
# client le temps d'ouvrir son email de bienvenue, et devient inutilisable des
# qu'un mot de passe a ete defini apres son envoi (voir lien_deja_utilise).
MAGIC_LINK_MAX_AGE = 48 * 60 * 60  # 48 heures
# Duree de vie de la session, configurable via PORTAL_SESSION_MAX_AGE_DAYS (defaut 30j).
SESSION_MAX_AGE = int(os.getenv("PORTAL_SESSION_MAX_AGE_DAYS", "30")) * 24 * 60 * 60


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
        # Horodatage precis (l'horodatage signe d'itsdangerous est a la seconde).
        "emis_le": round(time.time(), 3),
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


# --- Mot de passe du portail ---------------------------------------------------
# Stocke dans Notion sous la forme "pbkdf2_sha256$iterations$sel$empreinte$defini_le"
# (jamais le mot de passe en clair). "defini_le" (secondes) permet d'invalider
# tout lien emis avant la derniere definition du mot de passe.

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
_PBKDF2_ITERATIONS = 600_000
_PBKDF2_PREFIX = "pbkdf2_sha256"


def _b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode("ascii")


def erreur_mot_de_passe(mot_de_passe: str) -> str | None:
    # Message affichable au client si le mot de passe est refuse, sinon None.
    longueur = len(mot_de_passe or "")

    if longueur < PASSWORD_MIN_LENGTH:
        return f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères."

    if longueur > PASSWORD_MAX_LENGTH:
        return f"Le mot de passe ne doit pas dépasser {PASSWORD_MAX_LENGTH} caractères."

    return None


def hash_password(mot_de_passe: str, defini_le: float | None = None) -> str:
    sel = secrets.token_bytes(16)
    empreinte = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, _PBKDF2_ITERATIONS)
    defini_le = time.time() if defini_le is None else defini_le
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${_b64(sel)}${_b64(empreinte)}${defini_le:.3f}"


def _decouper(stocke: str) -> tuple[int, bytes, bytes, float] | None:
    morceaux = (stocke or "").strip().split("$")

    if len(morceaux) != 5 or morceaux[0] != _PBKDF2_PREFIX:
        return None

    try:
        return int(morceaux[1]), base64.b64decode(morceaux[2]), base64.b64decode(morceaux[3]), float(morceaux[4])
    except ValueError:
        return None


def mot_de_passe_defini(stocke: str) -> bool:
    return _decouper(stocke) is not None


def verify_password(mot_de_passe: str, stocke: str) -> bool:
    morceaux = _decouper(stocke)

    if not morceaux or not mot_de_passe:
        # Calcul factice : meme duree de reponse qu'un compte avec mot de passe.
        hashlib.pbkdf2_hmac("sha256", (mot_de_passe or "").encode("utf-8"), b"0" * 16, _PBKDF2_ITERATIONS)
        return False

    iterations, sel, attendu, _ = morceaux
    calcule = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, iterations)
    return hmac.compare_digest(calcule, attendu)


def lien_deja_utilise(donnees_lien: dict, stocke: str) -> bool:
    # Un lien emis avant la derniere definition du mot de passe ne sert plus.
    morceaux = _decouper(stocke)
    return bool(morceaux) and float(donnees_lien.get("emis_le") or 0) < morceaux[3]
