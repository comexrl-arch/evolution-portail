# Garde de POST /portal/auth/request-link (anti-enumeration, anti-inondation).
#
# Meme decision pour tout email, connu ou non : elle est evaluee AVANT toute
# recherche Notion, donc la reponse ne depend jamais de l'existence du compte
# et l'API Notion est protegee des balayages. Etat en memoire (process unique),
# borne et purge a chaque appel : il est perdu au redemarrage et n'est pas
# partage entre instances (meilleur effort, assume).

import hashlib
import threading
import time
from collections import deque
from typing import NamedTuple

COOLDOWN_SECONDS = 60
EMAIL_MAX_REQUESTS = 5
EMAIL_WINDOW_SECONDS = 15 * 60
GLOBAL_MAX_REQUESTS = 100
GLOBAL_WINDOW_SECONDS = 15 * 60
MAX_EMAIL_ENTRIES = 1000  # garde-fou memoire

_lock = threading.Lock()
_par_email: dict[str, deque] = {}
_global: deque = deque()


class Decision(NamedTuple):
    autorise: bool
    raison: str  # "ok" | "cooldown" | "limite_email" | "limite_globale"


def _cle(email: str) -> str:
    # Empreinte de l'email nettoye : la memoire ne conserve ni email brut ni cle
    # de taille arbitraire.
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def _purger(maintenant: float) -> None:
    while _global and maintenant - _global[0] >= GLOBAL_WINDOW_SECONDS:
        _global.popleft()

    for cle in list(_par_email):
        historique = _par_email[cle]

        while historique and maintenant - historique[0] >= EMAIL_WINDOW_SECONDS:
            historique.popleft()

        if not historique:
            del _par_email[cle]


def verifier_et_enregistrer(email: str) -> Decision:
    # Une demande refusee n'est pas enregistree : elle ne prolonge ni le
    # cooldown ni les quotas.
    maintenant = time.monotonic()
    cle = _cle(email)

    with _lock:
        _purger(maintenant)

        if len(_global) >= GLOBAL_MAX_REQUESTS:
            return Decision(False, "limite_globale")

        historique = _par_email.get(cle)

        if historique:
            if maintenant - historique[-1] < COOLDOWN_SECONDS:
                return Decision(False, "cooldown")

            if len(historique) >= EMAIL_MAX_REQUESTS:
                return Decision(False, "limite_email")

        elif len(_par_email) >= MAX_EMAIL_ENTRIES:
            return Decision(False, "limite_globale")

        _par_email.setdefault(cle, deque()).append(maintenant)
        _global.append(maintenant)
        return Decision(True, "ok")


def _reinitialiser_pour_tests() -> None:
    with _lock:
        _par_email.clear()
        _global.clear()
