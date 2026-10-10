# Garde de POST /portal/auth/login (anti force brute).
#
# Seuls les echecs sont comptes, par email (empreinte) et au global, sur une
# fenetre glissante. Evaluee AVANT toute recherche Notion : meme decision pour
# un email connu ou non. Etat en memoire (process unique), borne et purge a
# chaque appel, perdu au redemarrage (meilleur effort, assume).

import hashlib
import threading
import time
from collections import deque

EMAIL_MAX_ECHECS = 8
GLOBAL_MAX_ECHECS = 200
FENETRE_SECONDES = 15 * 60
MAX_EMAIL_ENTRIES = 1000  # garde-fou memoire

_lock = threading.Lock()
_par_email: dict[str, deque] = {}
_global: deque = deque()


def _cle(email: str) -> str:
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def _purger(maintenant: float) -> None:
    while _global and maintenant - _global[0] >= FENETRE_SECONDES:
        _global.popleft()

    for cle in list(_par_email):
        historique = _par_email[cle]

        while historique and maintenant - historique[0] >= FENETRE_SECONDES:
            historique.popleft()

        if not historique:
            del _par_email[cle]


def bloque(email: str) -> bool:
    maintenant = time.monotonic()

    with _lock:
        _purger(maintenant)
        return len(_global) >= GLOBAL_MAX_ECHECS or len(_par_email.get(_cle(email), ())) >= EMAIL_MAX_ECHECS


def enregistrer_echec(email: str) -> None:
    maintenant = time.monotonic()
    cle = _cle(email)

    with _lock:
        _purger(maintenant)
        _global.append(maintenant)

        if cle in _par_email or len(_par_email) < MAX_EMAIL_ENTRIES:
            _par_email.setdefault(cle, deque()).append(maintenant)


def reinitialiser(email: str) -> None:
    with _lock:
        _par_email.pop(_cle(email), None)


def _reinitialiser_pour_tests() -> None:
    with _lock:
        _par_email.clear()
        _global.clear()
