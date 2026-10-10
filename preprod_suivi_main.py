# preprod_suivi_main.py - Point d'entree de PREPROD pour tester l'onglet « Suivi client »
# avec des donnees entierement fictives.
#
# Lancement : uvicorn preprod_suivi_main:app
# Ne jamais utiliser comme commande de production : render.yaml demarre portal_main:app.
#
# Ce module refuse de demarrer hors preprod ou si une configuration reelle est
# presente, bloque tout appel reseau sortant, et remplace uniquement la lecture
# du classeur Google par un faux classeur en memoire. Le parsing reel de
# cockpit_service est conserve. Aucune ecriture n'est possible.

import os
from datetime import date
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

# Charge le .env local AVANT les garde-fous, comme le fait notion_service :
# un .env contenant de vrais identifiants doit faire echouer le demarrage.
load_dotenv()

_ENVIRONNEMENT = "preprod"
_MARQUEURS_PROD = ("rl-evolution.fr",)
_IDENTIFIANTS_REELS = (
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
    "COCKPIT_SPREADSHEET_ID",
    "NOTION_API_KEY",
    "SYSTEME_IO_API_KEY",
    "N8N_WEBHOOK_MAGIC_LINK",
    "DOCUSEAL_API_KEY",
)


def _verifier_configuration() -> None:
    if os.getenv("PORTAL_ENVIRONMENT") != _ENVIRONNEMENT:
        raise RuntimeError("preprod_suivi_main refuse : PORTAL_ENVIRONMENT doit valoir 'preprod'.")

    frontend = os.getenv("PORTAL_FRONTEND_URL", "")

    if not frontend:
        raise RuntimeError("preprod_suivi_main refuse : PORTAL_FRONTEND_URL doit etre defini explicitement.")

    configuration = " ".join([frontend, os.getenv("PORTAL_ALLOWED_ORIGINS", "")])

    if any(marqueur in configuration for marqueur in _MARQUEURS_PROD):
        raise RuntimeError("preprod_suivi_main refuse : la configuration pointe vers la production.")

    presents = [cle for cle in _IDENTIFIANTS_REELS if os.getenv(cle)]

    if presents:
        raise RuntimeError(
            "preprod_suivi_main refuse : identifiants reels presents ("
            + ", ".join(presents) + ")."
        )


_verifier_configuration()


def _bloquer_reseau() -> None:
    def _interdit(self, method, url, *args, **kwargs):
        hote = urlparse(str(url)).netloc or "inconnu"
        raise RuntimeError(f"[PREPROD] appel reseau bloque : {method.upper()} {hote}")

    requests.sessions.Session.request = _interdit


_bloquer_reseau()

# Identifiant fictif : jamais un vrai classeur. Le faux classeur ignore sa valeur.
os.environ["COCKPIT_SPREADSHEET_ID"] = "fixture-suivi-preprod"

from backend.services import cockpit_service, sheets_service  # noqa: E402

_EN_TETES_SANS_ONGLET = [
    "Notes", "Reste à encaisser (€)", "Email", "J0 (démarrage)", "☐ Client Notion créé",
    "Accès portail envoyé le", "1re connexion le", "Diagnostic terminé le", "☐ Fiche 8 validée",
    "KPI reçus", "Prochaine relance KPI", "Action portail", "Priorité",
]
_EN_TETES = list(cockpit_service.EN_TETES_SUIVI.values()) + _EN_TETES_SANS_ONGLET
_CASES = [
    "☐ RDV qualifié", "☐ Questionnaire envoyé", "☐ 1re session faite", "☐ Synthèse envoyée",
    "☐ J+7 fait", "☐ J+15 fait", "☐ Bilan J+30 fait", "☐ Suite ou clôture envoyée",
]


def _serie(annee: int, mois: int, jour: int) -> int:
    return (date(annee, mois, jour) - date(1899, 12, 30)).days


def _ligne(numero: int, offre: str, etape: str, etape_n: int, cases_cochees: int) -> dict:
    ligne = {nom: None for nom in _EN_TETES}
    ligne.update({
        "Client": f"Client Test {numero:02d}",
        "Offre": offre,
        "Date RDV qualifié": _serie(2026, 9, 1),
        "Date 1re session": _serie(2026, 9, 10),
        "J+7": _serie(2026, 9, 17),
        "J+15": _serie(2026, 9, 25),
        "J+30": _serie(2026, 10, 10),
        "Décision": "",
        "Étape en cours": etape,
        "Prochaine action": "Action fictive",
        "Échéance": _serie(2026, 10, 12),
        "Alerte": "Sous 48 h",
        "Leads": 10 + numero,
        "RDV": 4,
        "Ventes": 2,
        "Conversion": 0.5,
        "Panier moyen (€)": 400,
        "Réachat": "Non",
        "n": etape_n,
        "Notes": f"NOTE-FICTIVE-{numero:02d}",
        "Reste à encaisser (€)": "RESTE-FICTIF-999",
        "Email": f"client{numero:02d}@example.test",
        "KPI reçus": "KPI FICTIF",
        "Priorité": 1,
    })

    for case in _CASES:
        ligne[case] = _CASES.index(case) < cases_cochees

    return ligne


_LIGNES = [
    _ligne(1, "Coaching 90 j", "2. Après acceptation", 2, 1),
    _ligne(2, "Atelier", "1. Avant le RDV", 1, 0),
    _ligne(3, "Coaching 90 j", "5. Suivi 30 jours", 5, 4),
    _ligne(4, "Coaching 90 j", "✔ Terminé", 8, 8),
    _ligne(5, "Atelier", "6. Décision", 6, 6),
    {**_ligne(6, "Coaching 90 j", "1. Avant le RDV", 1, 0), "Décision": "Continuer"},
]


class _Reponse:
    def __init__(self, donnees: dict, status: int = 200):
        self._donnees = donnees
        self.status_code = status
        self.text = ""

    def json(self) -> dict:
        return self._donnees


class _ClasseurFictif:
    # Lecture seule : seuls les en-tetes et les colonnes de l'onglet sont servis.
    def __init__(self, en_tetes: list, lignes: list):
        self._en_tetes = en_tetes
        self._lignes = lignes
        self._index_par_lettre = {cockpit_service._lettre_colonne(i): i for i in range(len(en_tetes))}

    def get(self, url, params=None, timeout=None):
        if "values:batchGet" in url:
            valeurs = []

            for plage in (params or {}).get("ranges", []):
                lettre = plage.split("!", 1)[1].split(":", 1)[0].rstrip("0123456789")
                nom = self._en_tetes[self._index_par_lettre[lettre]]
                colonne = [ligne.get(nom) for ligne in self._lignes]
                valeurs.append({"range": plage, "values": [colonne] if colonne else []})

            return _Reponse({"valueRanges": valeurs})

        return _Reponse({"values": [self._en_tetes]})

    def post(self, *args, **kwargs):
        raise RuntimeError("[PREPROD] ecriture Google interdite")


_CLASSEUR = _ClasseurFictif(_EN_TETES, _LIGNES)
sheets_service._http = lambda: _CLASSEUR
sheets_service.enabled = lambda: True

from portal_main import app  # noqa: E402,F401
