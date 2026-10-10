# Tests de l'onglet "Suivi client" de l'Espace Coach : GET /coach/suivi-clients
# (portal_main.py) et la lecture seule de "Suivi clients" (cockpit_service.py).
#
# Entierement mockes : l'API Google Sheets est remplacee par un faux classeur en
# memoire, aucun appel reseau reel. Toutes les valeurs sont fictives. Meme style
# que test_cockpit_signature.py (script simple, sans framework de test).
#
# Lancer : python test_suivi_clients.py

import json
import logging
import os
import sys
from unittest.mock import patch

import requests
from fastapi import HTTPException

import portal_main
from backend.services import cockpit_service as cs
from backend.services import notion_service as ns
from backend.services import sheets_service
from backend.services import systeme_io_service

passed = 0
failed = 0


def check(label, condition):
    global passed, failed

    if condition:
        passed += 1
        print(f"  PASS - {label}")
    else:
        failed += 1
        print(f"  FAIL - {label}")


def statut(fonction, *args, **kwargs):
    try:
        return 200, fonction(*args, **kwargs)
    except HTTPException as error:
        return error.status_code, error.detail


CLE = "code-coach-factice"
SHEET_ID = "classeur-factice"

# En-tetes reels de la ligne 4 de "Suivi clients" (A a AN).
EN_TETES = [
    "Client", "Offre", "Date RDV qualifié", "☐ RDV qualifié", "☐ Questionnaire envoyé",
    "Date 1re session", "☐ 1re session faite", "☐ Synthèse envoyée", "J+7", "☐ J+7 fait",
    "J+15", "☐ J+15 fait", "J+30", "☐ Bilan J+30 fait", "Décision", "☐ Suite ou clôture envoyée",
    "Étape en cours", "Prochaine action", "Échéance", "Alerte", "Leads", "RDV", "Ventes",
    "Conversion", "Panier moyen (€)", "Réachat", "Notes", "n", "Reste à encaisser (€)", "Email",
    "J0 (démarrage)", "☐ Client Notion créé", "Accès portail envoyé le", "1re connexion le",
    "Diagnostic terminé le", "☐ Fiche 8 validée", "KPI reçus", "Prochaine relance KPI",
    "Action portail", "Priorité",
]

# Valeurs sensibles qui ne doivent jamais sortir de la route.
SENSIBLES = [
    "jean.dupont@exemple.test", "Note interne confidentielle", "987654",
    "Vérifier la création du client dans Notion", "J60", "contrat-secret",
]


def serie(a, m, j):
    from datetime import date

    return (date(a, m, j) - date(1899, 12, 30)).days


def ligne_complete():
    # Une ligne de cockpit avec toutes les colonnes, y compris les interdites.
    return {
        "Client": "Jean Dupont",
        "Offre": "Coaching 90 j",
        "Date RDV qualifié": serie(2026, 9, 1),
        "☐ RDV qualifié": True,
        "☐ Questionnaire envoyé": True,
        "Date 1re session": serie(2026, 9, 10),
        "☐ 1re session faite": True,
        "☐ Synthèse envoyée": True,
        "J+7": serie(2026, 9, 17),
        "☐ J+7 fait": True,
        "J+15": serie(2026, 9, 25),
        "☐ J+15 fait": False,
        "J+30": serie(2026, 10, 10),
        "☐ Bilan J+30 fait": False,
        "Décision": "",
        "☐ Suite ou clôture envoyée": False,
        "Étape en cours": "5. Suivi 30 jours",
        "Prochaine action": "J+15 : ajuster",
        "Échéance": serie(2026, 9, 25),
        "Alerte": "En retard",
        "Leads": 12,
        "RDV": 4,
        "Ventes": 2,
        "Conversion": 0.5,
        "Panier moyen (€)": 450,
        "Réachat": "Oui",
        "Notes": "Note interne confidentielle",
        "n": 5,
        "Reste à encaisser (€)": 987654,
        "Email": "jean.dupont@exemple.test",
        "J0 (démarrage)": serie(2026, 9, 1),
        "☐ Client Notion créé": True,
        "Accès portail envoyé le": serie(2026, 9, 2),
        "1re connexion le": serie(2026, 9, 3),
        "Diagnostic terminé le": serie(2026, 9, 5),
        "☐ Fiche 8 validée": False,
        "KPI reçus": "J60",
        "Prochaine relance KPI": serie(2026, 11, 1),
        "Action portail": "Vérifier la création du client dans Notion",
        "Priorité": 1,
    }


def ligne_minimale():
    # Client juste saisi : nom seul, cases vides (absentes), formules a "".
    return {
        "Client": "Marie Martin",
        "Offre": "Atelier",
        "Date RDV qualifié": "",
        "Date 1re session": "",
        "J+7": "",
        "J+15": "",
        "J+30": "",
        "Étape en cours": "1. Avant le RDV",
        "Prochaine action": "Obtenir un RDV qualifié",
        "Échéance": "",
        "Alerte": "",
        "Conversion": "",
        "n": 1,
        "Email": "marie.martin@exemple.test",
        "Reste à encaisser (€)": "Pas de contrat",
    }


def ligne_atypique():
    # Valeurs inattendues : texte au lieu d'une date, "TRUE" en texte, 0 en KPI.
    return {
        "Client": "  Paul Durand  ",
        "Offre": "Autre",
        "Date 1re session": "12/10",
        "☐ RDV qualifié": "TRUE",
        "☐ Questionnaire envoyé": 1,
        "Décision": "Continuer",
        "Étape en cours": "✔ Terminé",
        "n": 8,
        "Leads": 0,
        "Réachat": "",
        "Panier moyen (€)": "à confirmer",
    }


def lettre(index):
    return cs._lettre_colonne(index)


class Reponse:
    def __init__(self, donnees, status=200):
        self.status_code = status
        self._donnees = donnees
        self.text = "erreur factice"

    def json(self):
        return self._donnees


class FauxClasseur:
    # lignes : liste de dicts {en-tete: valeur} a partir de la ligne 5.
    def __init__(self, lignes, en_tetes=None, panne=None):
        self.en_tetes = list(EN_TETES if en_tetes is None else en_tetes)
        self.lignes = lignes
        self.panne = panne
        self.plages_lues = []
        self.ecritures = 0
        self.appels = 0

    def _colonne(self, lettres):
        index = 0

        for c in lettres:
            index = index * 26 + ord(c) - 64

        en_tete = self.en_tetes[index - 1] if index - 1 < len(self.en_tetes) else None
        return [ligne.get(en_tete) for ligne in self.lignes]

    def get(self, url, params=None, timeout=None):
        self.appels += 1

        if self.panne == "reseau":
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}?key=secret")

        if self.panne == "http":
            return Reponse({}, status=500)

        if "values:batchGet" in url:
            plages = params["ranges"]
            self.plages_lues.extend(plages)
            valeurs = []

            for plage in plages:
                a1 = plage.rsplit("!", 1)[1]
                lettres = "".join(c for c in a1.split(":")[0] if c.isalpha())
                colonne = self._colonne(lettres)
                # Google tronque les cellules vides en fin de colonne.
                while colonne and colonne[-1] in (None, ""):
                    colonne.pop()
                valeurs.append({"range": plage, "values": [colonne] if colonne else []})

            return Reponse({"valueRanges": valeurs})

        self.plages_lues.append(url.rsplit("/values/", 1)[1])
        return Reponse({"values": [self.en_tetes]})

    def post(self, *args, **kwargs):
        self.ecritures += 1
        raise AssertionError("Aucune ecriture attendue")



def appeler(classeur, cle=CLE, env=None):
    variables = {"COACH_ONBOARD_KEY": CLE, "COCKPIT_SPREADSHEET_ID": SHEET_ID}
    variables.update(env or {})
    variables = {k: v for k, v in variables.items() if v is not None}

    with patch.dict(os.environ, variables, clear=False), \
         patch.object(sheets_service, "enabled", return_value=True), \
         patch.object(sheets_service, "_http", return_value=classeur):
        for k, v in (env or {}).items():
            if v is None:
                os.environ.pop(k, None)
        return statut(portal_main.coach_suivi_clients, x_coach_key=cle)


CHAMPS_FICHE = {
    "ligne", "nom", "offre", "etape_numero", "etape", "date_premiere_session",
    "etapes", "prochaine_action", "echeance", "alerte", "indicateurs",
}
CLES_ETAPES = [
    "rdv_qualifie", "questionnaire_envoye", "premiere_session", "synthese_envoyee",
    "j7", "j15", "bilan_j30", "decision", "suite_cloture",
]
INDICATEURS = {"leads", "rdv", "ventes", "conversion", "panier_moyen", "reachat"}


def etape(fiche, cle):
    return next(e for e in fiche["etapes"] if e["cle"] == cle)


# --- 1. Champs autorises uniquement -----------------------------------------------

print("1. Reponse limitee aux champs autorises")
classeur = FauxClasseur([ligne_complete(), {}, ligne_minimale(), ligne_atypique()])
code, reponse = appeler(classeur)
check("200 avec le bon code", code == 200)
check("reponse = {'clients': [...]} seulement", set(reponse) == {"clients"})
fiches = reponse["clients"]
check("ligne sans nom ignoree (3 fiches)", len(fiches) == 3)
check("champs de fiche exactement autorises", all(set(f) == CHAMPS_FICHE for f in fiches))
check("etapes dans l'ordre du process", [e["cle"] for e in fiches[0]["etapes"]] == CLES_ETAPES)
check("champs d'etape autorises", all(
    set(e) <= {"cle", "libelle", "fait", "date", "valeur"} for f in fiches for e in f["etapes"]
))
check("indicateurs limites a U-Z", all(set(f["indicateurs"]) <= INDICATEURS for f in fiches))
texte = json.dumps(reponse, ensure_ascii=False)
check("aucune donnee sensible (email, notes, montant, suivi portail)",
      not any(s in texte for s in SENSIBLES) and "marie.martin@exemple.test" not in texte)
check("aucune cle email/notes/reste/action portail",
      not any(k in texte for k in ('"email"', '"notes"', '"reste', '"action_portail"', '"priorite"')))

# --- 2. Seules les colonnes utiles sont demandees a Google, sans ecriture ---------

print("2. Lecture seule, colonnes utiles uniquement")
colonnes_lues = {"".join(c for c in p.rsplit("!", 1)[1].split(":")[0] if c.isalpha()) for p in classeur.plages_lues if ":" in p and not p.endswith("4:4")}
interdites = {"AA", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN"}
check("aucune colonne AA, AC a AN lue", not (colonnes_lues & interdites))
check("colonnes A a Z + n (AB) lues", colonnes_lues == {lettre(i) for i in range(26)} | {"AB"})
check("toutes les plages visent 'Suivi clients'", all(p.startswith("'Suivi clients'!") for p in classeur.plages_lues))
check("aucune ecriture dans le classeur", classeur.ecritures == 0)
check("2 appels Google (en-tetes + colonnes)", classeur.appels == 2)

# --- 3. Valeurs : dates, cases, champs vides --------------------------------------

print("3. Dates, cases et champs vides")
complet, minimal, atypique = fiches
check("nom", complet["nom"] == "Jean Dupont" and atypique["nom"] == "Paul Durand")
check("offre", complet["offre"] == "Coaching 90 j")
check("etape en cours et numero", complet["etape"] == "5. Suivi 30 jours" and complet["etape_numero"] == 5)
check("date 1re session en ISO", complet["date_premiere_session"] == "2026-09-10")
check("prochaine action + echeance + alerte du cockpit",
      complet["prochaine_action"] == "J+15 : ajuster" and complet["echeance"] == "2026-09-25"
      and complet["alerte"] == "En retard")
check("case cochee -> fait", etape(complet, "j7")["fait"] is True)
check("case decochee -> a faire", etape(complet, "j15")["fait"] is False)
check("J+7/J+15/J+30 avec date prevue",
      etape(complet, "j7")["date"] == "2026-09-17" and etape(complet, "j15")["date"] == "2026-09-25"
      and etape(complet, "bilan_j30")["date"] == "2026-10-10")
check("date RDV qualifie sur l'etape", etape(complet, "rdv_qualifie")["date"] == "2026-09-01")
check("decision vide -> a faire, sans valeur",
      etape(complet, "decision")["fait"] is False and etape(complet, "decision")["valeur"] is None)
check("pas de statut 'En retard' dans les etapes", "En retard" not in json.dumps(complet["etapes"]))
check("indicateurs renseignes",
      complet["indicateurs"] == {"leads": 12, "rdv": 4, "ventes": 2, "conversion": 0.5,
                                 "panier_moyen": 450, "reachat": "Oui"})
check("fiche minimale : dates vides -> None",
      minimal["date_premiere_session"] is None and minimal["echeance"] is None
      and etape(minimal, "j7")["date"] is None)
check("fiche minimale : alerte vide -> None", minimal["alerte"] is None)
check("fiche minimale : cases absentes -> a faire", not any(e["fait"] for e in minimal["etapes"]))
check("fiche minimale : aucun indicateur", minimal["indicateurs"] == {})
check("texte au lieu d'une date -> None", atypique["date_premiere_session"] is None)
check("'TRUE' en texte ou 1 ne valent pas une case cochee",
      etape(atypique, "rdv_qualifie")["fait"] is False and etape(atypique, "questionnaire_envoye")["fait"] is False)
check("decision renseignee -> fait + valeur",
      etape(atypique, "decision")["fait"] is True and etape(atypique, "decision")["valeur"] == "Continuer")
check("etape terminee (n=8)", atypique["etape_numero"] == 8)
check("KPI a 0 conserve, KPI vide omis, texte libre conserve",
      atypique["indicateurs"] == {"leads": 0, "panier_moyen": "à confirmer"})
check("numero de ligne du cockpit", [f["ligne"] for f in fiches] == [5, 7, 8])

# --- 4. Colonnes retrouvees par en-tete, pas par lettre -----------------------------

print("4. Colonnes identifiees par leurs en-tetes")
deplaces = ["Colonne ajoutée"] + EN_TETES
code, reponse = appeler(FauxClasseur([ligne_complete()], en_tetes=deplaces))
check("colonne inseree : meme resultat",
      code == 200 and reponse["clients"][0]["nom"] == "Jean Dupont"
      and reponse["clients"][0]["indicateurs"]["reachat"] == "Oui"
      and "jean.dupont@exemple.test" not in json.dumps(reponse))

for nom_cas, en_tetes in (
    ("en-tete manquant", [h for h in EN_TETES if h != "☐ J+7 fait"]),
    ("en-tete en double", EN_TETES + ["Prochaine action"]),
    ("en-tetes vides", []),
):
    classeur = FauxClasseur([ligne_complete()], en_tetes=en_tetes)
    code, detail = appeler(classeur)
    check(f"{nom_cas} -> 503 generique", code == 503 and detail == portal_main._MESSAGE_SERVICE_INDISPONIBLE)
    check(f"{nom_cas} -> aucune donnee lue", not any("batchGet" in p for p in classeur.plages_lues) and len(classeur.plages_lues) == 1)

# --- 5. Autorisation -------------------------------------------------------------

print("5. Autorisation")
for libelle, cle in (("code faux", "mauvais"), ("code vide", ""), ("prefixe du code", CLE[:-1]), ("code + suffixe", CLE + "x")):
    classeur = FauxClasseur([ligne_complete()])
    code, detail = appeler(classeur, cle=cle)
    check(f"{libelle} -> 401", code == 401)
    check(f"{libelle} -> Google jamais appele", classeur.appels == 0)
    check(f"{libelle} -> aucune donnee", "Jean" not in json.dumps(detail, ensure_ascii=False))

classeur = FauxClasseur([ligne_complete()])
code, detail = appeler(classeur, env={"COACH_ONBOARD_KEY": None})
check("COACH_ONBOARD_KEY absent -> 503, aucun appel Google", code == 503 and classeur.appels == 0)

classeur = FauxClasseur([ligne_complete()])
code, detail = appeler(classeur, env={"COCKPIT_SPREADSHEET_ID": None})
check("COCKPIT_SPREADSHEET_ID absent -> 503 generique",
      code == 503 and detail == portal_main._MESSAGE_SERVICE_INDISPONIBLE and classeur.appels == 0)

with patch.dict(os.environ, {"COACH_ONBOARD_KEY": CLE, "COCKPIT_SPREADSHEET_ID": SHEET_ID}), \
     patch.object(sheets_service, "enabled", return_value=False):
    code, _ = statut(portal_main.coach_suivi_clients, x_coach_key=CLE)
check("acces Google non configure -> 503", code == 503)

# --- 6. Pannes Google : reseau, HTTP, sans fuite --------------------------------

print("6. Feuille indisponible")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


capture = Capture()
logging.getLogger("uvicorn.error").addHandler(capture)

for panne in ("reseau", "http"):
    capture.messages.clear()
    code, detail = appeler(FauxClasseur([ligne_complete()], panne=panne))
    check(f"panne {panne} -> 503 generique", code == 503 and detail == portal_main._MESSAGE_SERVICE_INDISPONIBLE)
    journal = "\n".join(capture.messages)
    check(f"panne {panne} -> journalisee", "coach_suivi_clients" in journal)
    check(f"panne {panne} -> ni URL, ni secret, ni donnee client dans les logs",
          "key=secret" not in journal and "://" not in journal
          and "Jean" not in journal and "@" not in journal)

capture.messages.clear()
appeler(FauxClasseur([ligne_complete()]))
check("lecture reussie -> aucune donnee client dans les logs",
      not any(s in m for m in capture.messages for s in SENSIBLES + ["Jean Dupont"]))
logging.getLogger("uvicorn.error").removeHandler(capture)

# --- 7. Les onglets existants fonctionnent toujours ------------------------------

print("7. Onglets Onboarding et Diagnostics inchanges")
with patch.dict(os.environ, {"COACH_ONBOARD_KEY": CLE}):
    with patch.object(ns, "list_diagnostics_fiche8", return_value=[{"fiche_client_id": "f1", "client_nom": "X", "etat": "En cours"}]):
        code, rep = statut(portal_main.coach_diagnostics, x_coach_key=CLE)
        check("Diagnostics : 200 avec le bon code", code == 200 and rep["diagnostics"][0]["fiche_client_id"] == "f1")
        code, _ = statut(portal_main.coach_diagnostics, x_coach_key="mauvais")
        check("Diagnostics : 401 avec un code faux", code == 401)

    with patch.object(systeme_io_service, "search_contacts", return_value=[{"id": 1}]):
        code, rep = statut(portal_main.coach_leads_systeme_io, query="", x_coach_key=CLE)
        check("Onboarding (recherche) : 200 avec le bon code", code == 200 and rep["leads"] == [{"id": 1}])
        code, _ = statut(portal_main.coach_leads_systeme_io, query="", x_coach_key=CLE + " ")
        check("Onboarding (recherche) : 401 avec un code modifie", code == 401)

    with patch.object(ns, "onboard_client", return_value={"fiches_creees": 3}) as onboard:
        requete = portal_main.CoachClientOnboardRequest(nom="Test", email="t@exemple.test")
        code, rep = statut(portal_main.coach_onboard_client, requete, x_coach_key=CLE)
        check("Onboarding (creation) : 200 avec le bon code", code == 200 and rep == {"fiches_creees": 3})
        code, _ = statut(portal_main.coach_onboard_client, requete, x_coach_key="")
        check("Onboarding (creation) : 401 sans code", code == 401)
        check("Onboarding : aucune creation sans code", onboard.call_count == 1)

print(f"\n{passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
