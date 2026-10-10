# Tests du point d'entree de preproduction preprod_suivi_main.py.
# Chaque cas tourne dans un sous-processus : les garde-fous s'executent a l'import.
# Hors ligne : aucun appel reseau, identifiants reels vides.

import os
import subprocess
import sys
import unittest

RACINE = os.path.dirname(os.path.abspath(__file__))

_IDENTIFIANTS = (
    "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN", "COCKPIT_SPREADSHEET_ID", "NOTION_API_KEY",
    "SYSTEME_IO_API_KEY", "N8N_WEBHOOK_MAGIC_LINK", "DOCUSEAL_API_KEY",
)

_PREPROD = {
    "PORTAL_ENVIRONMENT": "preprod",
    "PORTAL_FRONTEND_URL": "https://evolution-portail.pages.dev",
    "PORTAL_ALLOWED_ORIGINS": "https://evolution-portail.pages.dev",
    "PORTAL_SECRET_KEY": "test-only-secret",
    "COACH_ONBOARD_KEY": "test-only-coach",
}


def _executer(code: str, env_extra: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Vide les identifiants reels : load_dotenv() ne remplace pas une variable deja presente.
    for cle in _IDENTIFIANTS:
        env[cle] = ""
    env.pop("PORTAL_ENVIRONMENT", None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", "import sys, os; sys.path.insert(0, os.getcwd()); " + code],
        cwd=RACINE, env=env, capture_output=True, text=True, timeout=120,
    )


class PreprodSuiviTests(unittest.TestCase):

    def test_refuse_sans_environnement_preprod(self):
        proc = _executer("import preprod_suivi_main", {**_PREPROD, "PORTAL_ENVIRONMENT": "production"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PORTAL_ENVIRONMENT doit valoir 'preprod'", proc.stderr)

    def test_refuse_sans_frontend_explicite(self):
        env = {k: v for k, v in _PREPROD.items() if k != "PORTAL_FRONTEND_URL"}
        proc = _executer("import preprod_suivi_main", env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PORTAL_FRONTEND_URL doit etre defini", proc.stderr)

    def test_refuse_origine_production(self):
        proc = _executer("import preprod_suivi_main", {**_PREPROD, "PORTAL_ALLOWED_ORIGINS": "https://portail.rl-evolution.fr"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("pointe vers la production", proc.stderr)

    def test_refuse_identifiant_reel_sans_afficher_sa_valeur(self):
        proc = _executer("import preprod_suivi_main", {**_PREPROD, "COCKPIT_SPREADSHEET_ID": "valeur-test-non-reelle"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("COCKPIT_SPREADSHEET_ID", proc.stderr)
        self.assertNotIn("valeur-test-non-reelle", proc.stderr)

    def test_endpoint_fictif_et_sans_fuite(self):
        # Appel direct de la route (comme test_suivi_clients.py) : pas de dependance httpx.
        code = (
            "from fastapi import HTTPException\n"
            "import preprod_suivi_main\n"
            "import portal_main as p\n"
            "def statut(f, **k):\n"
            "    try:\n"
            "        return 200, f(**k)\n"
            "    except HTTPException as e:\n"
            "        return e.status_code, e.detail\n"
            "s, _ = statut(p.coach_suivi_clients, x_coach_key=''); assert s == 401, s\n"
            "s, _ = statut(p.coach_suivi_clients, x_coach_key='mauvaise'); assert s == 401, s\n"
            "s, corps = statut(p.coach_suivi_clients, x_coach_key='test-only-coach'); assert s == 200, s\n"
            "clients = corps['clients']\n"
            "assert len(clients) == 6, len(clients)\n"
            "assert all(cl['nom'].startswith('Client Test') for cl in clients)\n"
            "assert {cl['offre'] for cl in clients} == {'Coaching 90 j', 'Atelier'}\n"
            "import json\n"
            "tout = json.dumps(corps, ensure_ascii=False)\n"
            "assert '@' not in tout, 'email expose'\n"
            "assert 'NOTE-FICTIVE' not in tout and 'RESTE-FICTIF' not in tout, 'fuite Notes ou Reste'\n"
            "assert 'email' not in tout.lower(), 'champ email'\n"
            "print('OK')\n"
        )
        proc = _executer(code, _PREPROD)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("OK", proc.stdout)

    def test_portal_me_sans_donnee_ni_email(self):
        # /portal/me passe par Notion : bloque en preprod, donc aucune donnee client ne sort.
        code = (
            "import preprod_suivi_main\n"
            "import portal_main as p\n"
            "from fastapi import HTTPException\n"
            "from backend.services import portal_auth_service as pa\n"
            "jeton = pa.create_session_token('client01@example.test', 'id-fictif')\n"
            "try:\n"
            "    p.portal_me(authorization='Bearer ' + jeton)\n"
            "    print('SORTIE=DONNEES')\n"
            "except HTTPException as e:\n"
            "    print('STATUT=' + str(e.status_code) + ' ' + str(e.detail))\n"
        )
        proc = _executer(code, _PREPROD)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertNotIn("SORTIE=DONNEES", proc.stdout)
        self.assertIn("STATUT=503", proc.stdout)
        self.assertNotIn("@", proc.stdout)

    def test_reseau_bloque(self):
        code = (
            "import preprod_suivi_main, requests\n"
            "try:\n"
            "    requests.get('https://sheets.googleapis.com/v4/spreadsheets/x', timeout=2)\n"
            "    print('RESEAU=OUVERT')\n"
            "except RuntimeError as e:\n"
            "    print('BLOQUE=' + str(e))\n"
        )
        proc = _executer(code, _PREPROD)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("BLOQUE=[PREPROD] appel reseau bloque : GET sheets.googleapis.com", proc.stdout)
        self.assertNotIn("RESEAU=OUVERT", proc.stdout)

    def test_production_inchangee(self):
        # La production demarre portal_main:app ; portal_main n'importe jamais le point d'entree preprod.
        with open(os.path.join(RACINE, "portal_main.py"), encoding="utf-8") as f:
            self.assertNotIn("preprod_suivi_main", f.read())
        with open(os.path.join(RACINE, "render.yaml"), encoding="utf-8") as f:
            contenu = f.read()
        self.assertIn("startCommand: uvicorn portal_main:app", contenu)
        self.assertNotIn("preprod_suivi_main", contenu)


if __name__ == "__main__":
    unittest.main()
