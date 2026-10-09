# docuseal_service.py - Lecture d'une soumission DocuSeal (API REST).
#
# Le webhook form.completed part a chaque signataire avec ses seules valeurs.
# Pour l'Atelier, la date de la session 1 est un champ du coach : le webhook du
# coach ne porte pas l'email du participant, et celui du participant ne porte
# pas la date. On relit donc la soumission complete pour relier les deux.
#
# Configuration : DOCUSEAL_API_KEY (Parametres > API dans DocuSeal) et, pour un
# compte hors docuseal.com, DOCUSEAL_API_URL. Sans cle, tout est desactive.

import os

import requests

_API_DEFAUT = "https://api.docuseal.com"


def enabled() -> bool:
    return bool(os.getenv("DOCUSEAL_API_KEY", "").strip())


def lire_soumission(submission_id) -> dict:
    base = (os.getenv("DOCUSEAL_API_URL", "").strip() or _API_DEFAUT).rstrip("/")

    try:
        response = requests.get(
            f"{base}/submissions/{int(submission_id)}",
            headers={"X-Auth-Token": os.getenv("DOCUSEAL_API_KEY", "").strip()},
            timeout=15,
        )
        response.raise_for_status()

    except requests.RequestException as error:
        raise RuntimeError(f"Erreur DocuSeal (lecture soumission) : {type(error).__name__}") from error

    return response.json()
