# Tests du report d'un contrat DocuSeal signe dans le cockpit Google Sheets
# (backend/services/cockpit_service.py + tache de fond du webhook DocuSeal).
#
# Entierement mockes : l'API Google Sheets est remplacee par un faux classeur en
# memoire, aucun appel reseau reel. Toutes les valeurs sont fictives. Meme style
# que test_docuseal_webhook.py (script simple, sans framework de test).
#
# Lancer : python test_cockpit_signature.py

import logging
import os
import sys
from datetime import date, datetime
from unittest.mock import patch

import requests
from fastapi import BackgroundTasks

import portal_main
from backend.services import cockpit_service as cs
from backend.services import notion_service as ns
from backend.services import sheets_service

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


SHEET_ID = "classeur-factice"
EMAIL = "jean.dupont@exemple.test"
NOM = "Jean Dupont"
SECRET = "secret-factice-test"
TEMPLATE_COACHING = next(k for k, v in portal_main._DOCUSEAL_PARCOURS.items() if v == "Coaching 90 jours")


def serie(jour):
    return (jour - date(1899, 12, 30)).days


# --- Faux classeur Google Sheets ----------------------------------------------------

def _col_index(lettres):
    n = 0

    for c in lettres:
        n = n * 26 + ord(c) - 64

    return n


def _parse(plage):
    onglet, a1 = plage.rsplit("!", 1)
    onglet = onglet.strip("'").replace("''", "'")
    debut = a1.split(":")[0]
    lettres = "".join(c for c in debut if c.isalpha())
    ligne = int("".join(c for c in debut if c.isdigit()))
    fin = int("".join(c for c in a1.split(":")[-1] if c.isdigit()))
    return onglet, lettres, ligne, fin


class Reponse:
    def __init__(self, donnees, status=200):
        self.status_code = status
        self._donnees = donnees
        self.text = "erreur factice"

    def json(self):
        return self._donnees


class FauxClasseur:
    def __init__(self, cellules=None, statut_ecriture=200):
        self.cellules = dict(cellules or {})  # (onglet, colonne, ligne) -> valeur
        self.ecritures = []
        self.statut_ecriture = statut_ecriture

    def get(self, url, params=None, timeout=None):
        assert url.endswith(f"/{SHEET_ID}/values:batchGet"), url
        assert params["majorDimension"] == "COLUMNS"
        plages = []

        for plage in params["ranges"]:
            onglet, col, debut, fin = _parse(plage)
            valeurs = [self.cellules.get((onglet, col, l), "") for l in range(debut, fin + 1)]

            while valeurs and valeurs[-1] == "":
                valeurs.pop()

            plages.append({"range": plage, "values": [valeurs]} if valeurs else {"range": plage})

        return Reponse({"valueRanges": plages})

    def post(self, url, json=None, timeout=None):
        assert url.endswith(f"/{SHEET_ID}/values:batchUpdate"), url
        self.ecritures.append(json)

        if self.statut_ecriture >= 300:
            return Reponse({}, self.statut_ecriture)

        for bloc in json["data"]:
            onglet, col, ligne, _ = _parse(bloc["range"])
            self.cellules[(onglet, col, ligne)] = bloc["values"][0][0]

        return Reponse({})

    def ecrit(self):
        return {bloc["range"]: bloc["values"][0][0] for e in self.ecritures for bloc in e["data"]}


def infos(**autres):
    base = {"nom": NOM, "email": EMAIL, "parcours": "Coaching 90 jours", "telephone": "",
            "date_demarrage": "", "completed_at": "2026-10-09T15:00:00Z", "modalite_paiement": ""}
    base.update(autres)
    return base


def lancer(classeur, donnees):
    with patch.dict(os.environ, {"COCKPIT_SPREADSHEET_ID": SHEET_ID}), \
         patch.object(sheets_service, "_http", return_value=classeur), \
         patch.object(requests, "post", side_effect=AssertionError("reseau interdit")):
        return cs.enregistrer_signature(donnees)


C, K = cs.ONGLET_CLIENTS, cs.ONGLET_CONTRATS
SIGNE = serie(date(2026, 10, 9))


print("=" * 80)
print("TEST 1 : activation")
print("=" * 80)

with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("COCKPIT_SPREADSHEET_ID", None)
    with patch.object(sheets_service, "enabled", return_value=True):
        check("desactive sans COCKPIT_SPREADSHEET_ID", cs.enabled() is False)
    os.environ["COCKPIT_SPREADSHEET_ID"] = SHEET_ID
    with patch.object(sheets_service, "enabled", return_value=False):
        check("desactive sans acces Google", cs.enabled() is False)
    with patch.object(sheets_service, "enabled", return_value=True):
        check("active avec identifiant + acces Google", cs.enabled() is True)


print("=" * 80)
print("TEST 2 : nouveau client Coaching, classeur vide")
print("=" * 80)

classeur = FauxClasseur()
resultat = lancer(classeur, infos())
ecrit = classeur.ecrit()
check("resultat 'cree'", resultat == "cree")
check("une seule ecriture groupee, en mode RAW",
      len(classeur.ecritures) == 1 and classeur.ecritures[0]["valueInputOption"] == "RAW")
check("Suivi clients ligne 5 : nom, offre, email", classeur.cellules.get((C, "A", 5)) == NOM
      and classeur.cellules.get((C, "B", 5)) == "Coaching 90 j" and classeur.cellules.get((C, "AD", 5)) == EMAIL)
check("Contrats ligne 5 : client, formule, statut, email", classeur.cellules.get((K, "A", 5)) == NOM
      and classeur.cellules.get((K, "B", 5)) == "Coaching 90 jours" and classeur.cellules.get((K, "J", 5)) == "En cours"
      and classeur.cellules.get((K, "M", 5)) == EMAIL)
check("signe le = date de completed_at (numero de serie)", classeur.cellules.get((K, "O", 5)) == SIGNE)
check("demarrage Coaching = date de signature", classeur.cellules.get((K, "D", 5)) == SIGNE)
check("montant Coaching inconnu : F vide + note pour le coach",
      (K, "F", 5) not in classeur.cellules and "1 720" in classeur.cellules.get((K, "L", 5), ""))
colonnes_ecrites = {r.rsplit("!", 1)[1].rstrip("0123456789") for r in ecrit}
check("aucune colonne calculee ecrite (E, H, P, Q-T, AB-AN sauf AD)",
      not colonnes_ecrites & {"E", "H", "P", "Q", "R", "S", "T", "AB", "AC", "AE", "AM", "AN"})


print("=" * 80)
print("TEST 3 : Atelier avec date de session 1, montant 390")
print("=" * 80)

classeur = FauxClasseur()
lancer(classeur, infos(parcours="Atelier", date_demarrage="2026-10-20"))
check("Suivi clients offre 'Atelier'", classeur.cellules.get((C, "B", 5)) == "Atelier")
check("Contrats formule 'Atelier Collectif'", classeur.cellules.get((K, "B", 5)) == "Atelier Collectif")
check("demarrage = date de session 1", classeur.cellules.get((K, "D", 5)) == serie(date(2026, 10, 20)))
check("montant 390 et pas de note", classeur.cellules.get((K, "F", 5)) == 390 and (K, "L", 5) not in classeur.cellules)


print("=" * 80)
print("TEST 4 : webhook rejoue -> aucun doublon")
print("=" * 80)

classeur = FauxClasseur()
lancer(classeur, infos())
avant = dict(classeur.cellules)
resultat = lancer(classeur, infos(email="  JEAN.Dupont@exemple.test "))
check("resultat 'deja_enregistre' (email compare sans casse ni espaces)", resultat == "deja_enregistre")
check("aucune nouvelle ecriture", len(classeur.ecritures) == 1 and classeur.cellules == avant)


print("=" * 80)
print("TEST 5 : contrat saisi a la main sans date de signature -> seule O est completee")
print("=" * 80)

classeur = FauxClasseur({(C, "A", 5): "Jean D.", (C, "AD", 5): EMAIL, (K, "A", 5): "Jean D.",
                         (K, "M", 5): EMAIL, (K, "F", 5): 1720})
resultat = lancer(classeur, infos())
check("resultat 'signature_completee'", resultat == "signature_completee")
check("seule la cellule O5 est ecrite", list(classeur.ecrit()) == [f"'{K}'!O5"] and classeur.cellules[(K, "O", 5)] == SIGNE)
check("montant saisi conserve", classeur.cellules[(K, "F", 5)] == 1720)


print("=" * 80)
print("TEST 6 : client deja dans Suivi clients (par email) -> nom existant reutilise")
print("=" * 80)

classeur = FauxClasseur({(C, "A", 5): "Autre", (C, "AD", 5): "autre@exemple.test",
                         (C, "A", 6): "Jean D.", (C, "AD", 6): EMAIL})
lancer(classeur, infos())
check("Suivi clients non reecrit", not any(r.startswith(f"'{C}'") for r in classeur.ecrit()))
check("Contrats!A reprend le nom existant", classeur.cellules.get((K, "A", 5)) == "Jean D.")


print("=" * 80)
print("TEST 7 : premiere ligne libre (lignes occupees sautees)")
print("=" * 80)

classeur = FauxClasseur({(C, "A", 5): "Client 1", (C, "A", 6): "Client 2", (C, "AD", 7): "x@exemple.test",
                         (K, "A", 5): "Client 1", (K, "M", 6): "y@exemple.test"})
lancer(classeur, infos())
check("Suivi clients : ligne 8 (A ou AD deja remplis avant)", classeur.cellules.get((C, "A", 8)) == NOM)
check("Contrats : ligne 7", classeur.cellules.get((K, "A", 7)) == NOM and classeur.cellules.get((K, "O", 7)) == SIGNE)
check("lignes existantes intactes", classeur.cellules[(C, "A", 5)] == "Client 1" and classeur.cellules[(K, "M", 6)] == "y@exemple.test")


print("=" * 80)
print("TEST 8 : nom deja pris par un autre client -> rien n'est ecrit")
print("=" * 80)

classeur = FauxClasseur({(C, "A", 5): "jean dupont", (C, "AD", 5): "homonyme@exemple.test"})

try:
    lancer(classeur, infos())
    leve = False
except cs.NomDejaPris:
    leve = True

check("NomDejaPris leve", leve)
check("aucune ecriture", classeur.ecritures == [])


print("=" * 80)
print("TEST 9 : cockpit plein -> rien n'est ecrit")
print("=" * 80)

plein = {(K, "A", l): f"Client {l}" for l in range(5, 41)}
classeur = FauxClasseur(plein)

try:
    lancer(classeur, infos())
    leve = False
except cs.CockpitPlein:
    leve = True

check("CockpitPlein leve (Contrats lignes 5 a 40 occupees)", leve)
check("aucune ecriture", classeur.ecritures == [])


print("=" * 80)
print("TEST 10 : un nom commencant par '=' n'est jamais une formule")
print("=" * 80)

classeur = FauxClasseur()
nom_piege = '=IMPORTRANGE("https://exemple.test";"A1")'
lancer(classeur, infos(nom=nom_piege))
check("ecriture en mode RAW", classeur.ecritures[0]["valueInputOption"] == "RAW")
check("texte stocke tel quel", classeur.cellules.get((C, "A", 5)) == nom_piege)


print("=" * 80)
print("TEST 11 : date de signature et montant")
print("=" * 80)

with patch.dict(os.environ, {}, clear=False):
    os.environ.pop("COCKPIT_TIMEZONE", None)
    check("02:30 UTC le 10/10 -> 09/10 en Guadeloupe", cs.date_signature("2026-10-10T02:30:00Z") == date(2026, 10, 9))
    check("15:00 UTC le 09/10 -> 09/10", cs.date_signature("2026-10-09T15:00:00.000Z") == date(2026, 10, 9))
    from zoneinfo import ZoneInfo
    aujourd_hui = datetime.now(ZoneInfo("America/Guadeloupe")).date()
    check("date absente ou illisible -> aujourd'hui", cs.date_signature("") == aujourd_hui
          and cs.date_signature("pas une date") == aujourd_hui)

check("Atelier : 390", cs.montant("Atelier", "")[0] == 390)
check("Coaching comptant : 1720 + mode 'Comptant'", cs.montant("Coaching 90 jours", "Paiement comptant")[:2] == (1720, "Comptant"))
check("Coaching 3 x 600 : 1800 + note", cs.montant("Coaching 90 jours", "3 x 600 €")[0] == 1800
      and "3 × 600" in cs.montant("Coaching 90 jours", "3 x 600 €")[2])
check("Coaching '3 fois' : 1800", cs.montant("Coaching 90 jours", "En 3 fois")[0] == 1800)
check("Coaching sans indication : montant vide", cs.montant("Coaching 90 jours", "")[0] is None)


print("=" * 80)
print("TEST 11b : retours de revue (email vide, nom vide sur ligne existante, date impossible)")
print("=" * 80)

classeur = FauxClasseur({(K, "A", 5): "Client 1", (K, "F", 5): 500})

try:
    lancer(classeur, infos(email="  "))
    leve = False
except ValueError:
    leve = True

check("email vide : refuse, rien n'est ecrit (pas de correspondance avec une cellule vide)",
      leve and classeur.ecritures == [] and (K, "O", 5) not in classeur.cellules)

classeur = FauxClasseur({(C, "A", 5): "Jean Dupont", (C, "AD", 5): "homonyme@exemple.test", (C, "AD", 6): EMAIL})

try:
    lancer(classeur, infos())
    leve = False
except cs.NomDejaPris:
    leve = True

check("email connu sans nom, nom deja pris par un autre client : NomDejaPris, rien n'est ecrit",
      leve and classeur.ecritures == [])

classeur = FauxClasseur({(C, "AD", 6): EMAIL})
lancer(classeur, infos())
check("email connu sans nom, nom libre : nom complete sur la meme ligne", classeur.cellules.get((C, "A", 6)) == NOM)

classeur = FauxClasseur()
resultat = lancer(classeur, infos(parcours="Atelier", date_demarrage="2026-02-31"))
check("date de demarrage impossible : ecriture faite, demarrage = date de signature",
      resultat == "cree" and classeur.cellules.get((K, "D", 5)) == SIGNE)


print("=" * 80)
print("TEST 12 : webhook DocuSeal -> tache cockpit (activee / desactivee / en echec)")
print("=" * 80)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


capture = Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.DEBUG)

payload = {"event_type": "form.completed", "data": {
    "email": EMAIL, "name": NOM, "template": {"id": TEMPLATE_COACHING}, "completed_at": "2026-10-09T15:00:00Z",
    "values": [{"field": "Nom", "value": NOM}, {"field": "Modalité de paiement", "value": "Comptant"}]}}
RESULTAT_OK = {"client_id": "page-1", "fiches_creees": 22, "kpi_crees": 4, "invite_envoyee": True, "invite_erreur": None}

with patch.dict(os.environ, {"DOCUSEAL_WEBHOOK_SECRET": SECRET}), \
     patch.object(requests, "post", side_effect=AssertionError("reseau interdit")):
    os.environ.pop("COCKPIT_SPREADSHEET_ID", None)
    bt = BackgroundTasks()
    portal_main.webhook_docuseal(payload, bt, x_webhook_secret=SECRET)
    check("cockpit desactive : une seule tache (onboarding)", len(bt.tasks) == 1)

    os.environ["COCKPIT_SPREADSHEET_ID"] = SHEET_ID
    classeur = FauxClasseur()

    with patch.object(sheets_service, "enabled", return_value=True), \
         patch.object(sheets_service, "_http", return_value=classeur), \
         patch.object(ns, "onboard_client", return_value=RESULTAT_OK) as onboard, \
         patch.object(ns, "alerter_coach_onboarding") as alerte:
        bt = BackgroundTasks()
        reponse = portal_main.webhook_docuseal(payload, bt, x_webhook_secret=SECRET)
        check("reponse inchangee", reponse == {"status": "accepte", "parcours": "Coaching 90 jours"})
        check("cockpit active : deux taches (onboarding + cockpit)", len(bt.tasks) == 2)

        for tache in bt.tasks:
            tache.func(*tache.args, **tache.kwargs)

        check("onboarding Notion toujours appele", onboard.call_count == 1)
        check("contrat ecrit avec date et mode comptant", classeur.cellules.get((K, "O", 5)) == SIGNE
              and classeur.cellules.get((K, "F", 5)) == 1720 and classeur.cellules.get((K, "I", 5)) == "Comptant")
        check("aucune alerte en cas de succes", alerte.call_count == 0)

    classeur_ko = FauxClasseur(statut_ecriture=500)
    debut = len(capture.records)

    with patch.object(sheets_service, "enabled", return_value=True), \
         patch.object(sheets_service, "_http", return_value=classeur_ko), \
         patch.object(ns, "onboard_client", return_value=RESULTAT_OK) as onboard, \
         patch.object(ns, "alerter_coach_onboarding") as alerte:
        bt = BackgroundTasks()
        portal_main.webhook_docuseal(payload, bt, x_webhook_secret=SECRET)

        for tache in bt.tasks:
            tache.func(*tache.args, **tache.kwargs)

        check("echec Google : onboarding Notion quand meme appele", onboard.call_count == 1)
        check("echec Google : une alerte coach 'cockpit_signature_echec'",
              alerte.call_count == 1 and alerte.call_args.kwargs.get("event") == "cockpit_signature_echec")
        message = " ".join(str(a) for a in alerte.call_args.args)
        logs = "\n".join(r.getMessage() for r in capture.records[debut:])
        check("ni email ni nom dans l'alerte", EMAIL not in message and NOM not in message)
        check("ni email ni nom dans les logs", EMAIL not in logs and NOM not in logs and "[cockpit]" in logs)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
