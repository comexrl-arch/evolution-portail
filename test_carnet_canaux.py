# Tests du 27/10/2026 : carnet de prospects vivant, recap du lundi par
# WhatsApp, passerelle Autonome vers Coaching, notifications sur le telephone.
#
# Entierement mockes (ni Notion, ni Gemini, ni service de notifications),
# meme style que test_lot4.py.
#
# Lancer : python test_carnet_canaux.py

import json
import sys
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import fidelite_service as fidelite
from backend.services import ia_service, notion_service as ns
from backend.services import portal_auth_service, prospects_service as carnet, push_service as push

portal_auth_service.SECRET_KEY = "cle-de-test-carnet"

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


CLIENT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
BEARER = "Bearer " + portal_auth_service.create_session_token("client@test.com", CLIENT)
J = lambda jours: (date.today() - timedelta(days=jours)).isoformat()
FICHE11 = {"id": "f11", "master_id": carnet.TABLEAU_PROSPECTION_MASTER_ID, "nom": "Marie - 11. MON TABLEAU DE PROSPECTION", "etat": "En cours"}
BILAN = {"id": "fb", "master_id": ns._BILAN_HEBDO_MASTER_ID, "nom": "Marie - 16. BILAN HEBDOMADAIRE : PROSPECTION", "etat": "En cours"}
DASHBOARD = {
    "nom": "Marie Test",
    "parcours": "Autonome",
    "date_demarrage": J(40),
    "identite": {"email": "client@test.com", "telephone": "0690 12 34 56"},
    "fiches": [FICHE11, BILAN],
    "rythme": {"jour": 40, "en_retard": 4},
    "objectif_90j": "10 nouveaux clients",
}


def entree(nom, statut_fiche, quand, action=""):
    donnees = {"Date": quand, "Nom du prospect": nom, "Canal": "WhatsApp", "Statut": statut_fiche, "Prochaine action": action}
    return {"id": f"e-{nom}-{quand}", "created_time": f"{quand}T10:00:00.000Z", "properties": {
        "Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": json.dumps(donnees, ensure_ascii=False)}]},
        "Date": {"type": "date", "date": {"start": quand}},
    }}


class FauxNotion:
    """Entrees Portail en memoire : la page du carnet et les lignes de la fiche 11."""

    def __init__(self, lignes_fiche=None):
        self.lignes_fiche = lignes_fiche or []
        self.page = None
        self.crees = 0
        self.maj = 0

    def query(self, data_source_id, filter_=None):
        texte = json.dumps(filter_ or {})

        if carnet.NOM_CARNET in texte:
            return [self.page] if self.page else []

        if "f11" in texte:
            return self.lignes_fiche

        return []

    def _props(self, properties):
        texte = "".join(m["text"]["content"] for m in properties["Données (JSON)"]["rich_text"])
        return {"Données (JSON)": {"type": "rich_text", "rich_text": [{"plain_text": texte}]}}

    def create(self, data_source_id, properties):
        self.crees += 1
        self.page = {"id": "page-carnet", "last_edited_time": "2026-10-27T10:00:00Z", "properties": self._props(properties)}
        self.titre = properties["Nom"]["title"][0]["text"]["content"]
        return self.page

    def update(self, page_id, properties):
        self.maj += 1
        self.page = {"id": page_id, "last_edited_time": "2026-10-27T11:00:00Z", "properties": self._props(properties)}
        return self.page


def avec_faux(faux):
    ns._cache_clear("carnet:")
    return [
        patch.object(ns, "_query_data_source", side_effect=faux.query),
        patch.object(ns, "_create_page", side_effect=faux.create),
        patch.object(ns, "_update_page", side_effect=faux.update),
    ]


def run(patches, fonction):
    for p in patches:
        p.start()
    try:
        return fonction()
    finally:
        for p in patches:
            p.stop()


print("\n=== Carnet : import depuis la fiche 11 ===")
faux = FauxNotion([
    entree("Garage Lubin", "Relance", J(10), "Rappeler jeudi"),
    entree("Garage Lubin", "RdV", J(3)),
    entree("Boulangerie Céleste", "Non", J(5)),
    entree("Mme Jean", "", J(2)),
])
vue = run(avec_faux(faux), lambda: carnet.vue_client(carnet.lire(CLIENT, DASHBOARD)))
noms = {p["nom"]: p for p in vue["prospects"]}
check("le « Non » de la fiche n'est pas repris", "Boulangerie Céleste" not in noms)
check("la ligne la plus récente l'emporte (RdV -> RDV)", noms.get("Garage Lubin", {}).get("statut") == "RDV")
check("sans statut : À contacter, sans événement", noms.get("Mme Jean", {}).get("statut") == "À contacter" and noms["Mme Jean"]["evenements"] == [])
check("importe = True et rien n'est écrit à la lecture", vue["importe"] is True and faux.crees == 0)

print("\n=== Carnet : actions ===")
faux = FauxNotion()
patches = avec_faux(faux)


def scenario():
    v = carnet.vue_client(carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "ajouter", None, {"nom": "  Hôtel   Bel Air ", "contact": "0690112233", "relance": date.today().isoformat()}))
    check("ajout : page créée une fois, nom nettoyé", faux.crees == 1 and v["prospects"][0]["nom"] == "Hôtel Bel Air")
    check("titre de la page : <client> — Carnet de prospects", faux.titre == "Marie Test — Carnet de prospects")
    pid = v["prospects"][0]["id"]
    check("relance du jour comptée", v["a_relancer"] == [pid])

    v = carnet.vue_client(carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "relance", pid, {"relance": (date.today() + timedelta(days=3)).isoformat()}))
    p = v["prospects"][0]
    check("« J'ai relancé » : statut Contacté, 1 contact cette semaine", p["statut"] == "Contacté" and v["semaine"]["contacts"] == 1)
    check("la relance passe dans 3 jours, plus à faire aujourd'hui", v["a_relancer"] == [])
    check("la page existante est mise à jour, pas recréée", faux.crees == 1 and faux.maj == 1)

    v = carnet.vue_client(carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "modifier", pid, {"statut": "RDV"}))
    v = carnet.vue_client(carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "modifier", pid, {"statut": "Client"}))
    check("RDV puis Client : 1 RDV, 1 vente cette semaine", v["semaine"]["rdv"] == 1 and v["semaine"]["ventes"] == 1)
    check("passer Client efface la date de relance", v["prospects"][0]["relance"] is None)
    check("compteurs par statut", v["par_statut"]["Client"] == 1 and v["par_statut"]["À contacter"] == 0)

    for erreur, args in [
        ("statut inconnu refusé", ("modifier", pid, {"statut": "Gagné"})),
        ("date invalide refusée", ("modifier", pid, {"relance": "31/12/2026"})),
        ("nom vide refusé", ("ajouter", None, {"nom": "   "})),
        ("action inconnue refusée", ("archiver", pid, {})),
    ]:
        try:
            carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, *args)
            check(erreur, False)
        except ValueError:
            check(erreur, True)

    try:
        carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "supprimer", "inconnu", None)
        check("prospect inconnu : LookupError", False)
    except LookupError:
        check("prospect inconnu : LookupError", True)

    v = carnet.vue_client(carnet.appliquer(CLIENT, "Marie Test", DASHBOARD, "supprimer", pid, None))
    check("suppression", v["prospects"] == [])


run(patches, scenario)

print("\n=== Carnet : totaux de la semaine ===")
lundi = date(2026, 10, 19)
prospects = [{"id": "a", "evenements": [
    {"date": "2026-10-18", "statut": "Contacté"},
    {"date": "2026-10-19", "statut": "Contacté"},
    {"date": "2026-10-25", "statut": "RDV"},
    {"date": "2026-10-26", "statut": "Client"},
]}]
check("du lundi au dimanche inclus", carnet.totaux_semaine(prospects, lundi) == {"contacts": 1, "rdv": 1, "ventes": 0})

print("\n=== Carnet : endpoints ===")
faux = FauxNotion()
patches = avec_faux(faux) + [patch.object(ns, "get_client_dashboard", return_value=DASHBOARD)]
code, vue = run(patches, lambda: statut(portal_main.portal_prospects, authorization=BEARER))
check("GET /portal/prospects : 200 et statuts", code == 200 and vue["statuts"] == carnet.STATUTS)
code, detail = run(patches, lambda: statut(portal_main.portal_prospects_action, portal_main.ProspectRequest(action="ajouter", prospect={"nom": ""}), authorization=BEARER))
check("POST invalide : 422 avec un message lisible", code == 422 and "nom" in detail)
code, _ = run(patches, lambda: statut(portal_main.portal_prospects_action, portal_main.ProspectRequest(action="supprimer", id="x"), authorization=BEARER))
check("POST prospect inconnu : 404", code == 404)
code, _ = statut(portal_main.portal_prospects, authorization="Bearer faux")
check("sans session : 401", code == 401)

print("\n=== WhatsApp : numéros ===")
for brut, attendu in [
    ("0690 12 34 56", "590690123456"),
    ("0696.11.22.33", "596696112233"),
    ("0594 30 00 00", "594594300000"),
    ("06 12 34 56 78", "33612345678"),
    ("+590 690 12 34 56", "590690123456"),
    ("0033612345678", "33612345678"),
    ("12345", None),
    ("", None),
    (None, None),
]:
    check(f"{brut!r} -> {attendu}", fidelite.numero_whatsapp(brut) == attendu)

print("\n=== WhatsApp : récap du lundi ===")
lundi_dernier = date.today() - timedelta(days=date.today().weekday() + 7)
semaine = {"semaine_du": lundi_dernier.isoformat(), "contacts": 12.0, "rdv": 3.0, "propositions": 1.0, "ventes": 1.0}
dash = {**DASHBOARD, "regularite": {"serie": 3}}

with patch.object(ns, "get_client_dashboard", return_value=dash), \
     patch.object(ns, "_historique_bilans", return_value=[semaine]), \
     patch.object(ia_service, "enabled", return_value=False):
    recap = fidelite.recap_du_client(CLIENT, "client@test.com", "0690 12 34 56")
    refuse = fidelite.recap_du_client(CLIENT, "client@test.com", "0690 12 34 56", whatsapp_refuse=True)
    sans_numero = fidelite.recap_du_client(CLIENT, "client@test.com", None)

check("canal whatsapp avec un numéro", recap["canal"] == "whatsapp" and recap["whatsapp"]["numero"] == "590690123456")
check("3 paramètres : prénom, phrase, lien du bilan", recap["whatsapp"]["parametres"][0] == "Marie" and recap["whatsapp"]["parametres"][2].endswith("/?ouvrir=bilan"))
check("phrase sur une ligne, avec les chiffres", "\n" not in recap["whatsapp"]["parametres"][1] and "12 contacts" in recap["whatsapp"]["parametres"][1])
check("WhatsApp refusé : e-mail", refuse["canal"] == "email" and refuse["whatsapp"] is None)
check("sans numéro : e-mail, texte de l'e-mail inchangé", sans_numero["canal"] == "email" and sans_numero["texte"].startswith("Bonjour Marie,"))

ancienne = {**semaine, "semaine_du": (lundi_dernier - timedelta(days=14)).isoformat()}
with patch.object(ns, "get_client_dashboard", return_value=dash), \
     patch.object(ns, "_historique_bilans", return_value=[ancienne]), \
     patch.object(ia_service, "enabled", return_value=False):
    retard = fidelite.recap_du_client(CLIENT, "client@test.com", "0690123456")
check("bilan de la semaine dernière absent : rappel", "pas encore fait" in retard["whatsapp"]["parametres"][1])

rows = [{"id": CLIENT, "properties": {
    "E-mail": {"type": "email", "email": "client@test.com"},
    "État": {"type": "select", "select": {"name": "En cours"}},
    "Téléphone": {"type": "phone_number", "phone_number": "0690123456"},
    "Récap WhatsApp désactivé": {"type": "checkbox", "checkbox": True},
}}]
with patch.object(ns, "_query_data_source", return_value=rows), \
     patch.object(fidelite, "recap_du_client", return_value={"ok": 1}) as appel:
    fidelite.recaps_hebdo()
check("recaps_hebdo lit le téléphone et la case « Récap WhatsApp désactivé »", appel.call_args.args[2:] == ("0690123456", True))

print("\n=== Passerelle Autonome vers Coaching ===")
check("avant J30 : rien", ns._passerelle_coaching({"jour": 29, "en_retard": 8}, []) is None)
check("J30, 2 fiches de retard, synthèse encourageante : rien", ns._passerelle_coaching({"jour": 30, "en_retard": 2}, [{"axe": "encouragement"}]) is None)
p = ns._passerelle_coaching({"jour": 35, "en_retard": 3}, [])
check("3 fiches de retard : proposée (période 1)", p and p["raison"] == "retard" and p["periode"] == 1)
p = ns._passerelle_coaching({"jour": 61, "en_retard": 0}, [{"axe": "reprise"}])
check("synthèse « reprise » : proposée (période 2)", p and p["raison"] == "reprise" and p["periode"] == 2)
check("l'adresse de réservation est fournie", p["url"].startswith("https://"))

with patch.object(ns, "get_client_dashboard", return_value={**DASHBOARD, "passerelle_coaching": None}):
    code, _ = statut(portal_main.portal_passerelle_coaching, portal_main.BackgroundTasks(), authorization=BEARER)
check("clic sans proposition ouverte : 403", code == 403)

taches = portal_main.BackgroundTasks()
with patch.object(ns, "get_client_dashboard", return_value={**DASHBOARD, "passerelle_coaching": p}):
    code, reponse = statut(portal_main.portal_passerelle_coaching, taches, authorization=BEARER)
check("clic : 200 et adresse renvoyée", code == 200 and reponse["url"] == p["url"])

envois = []
with patch.dict("os.environ", {"N8N_WEBHOOK_COACH_ALERT": "https://n8n.test/alerte"}), \
     patch.object(ns, "_historique_bilans", return_value=[semaine]), \
     patch.object(ns.requests, "post", side_effect=lambda url, json, timeout: envois.append(json) or type("R", (), {"raise_for_status": lambda self: None})()):
    for tache in taches.tasks:
        tache.func(*tache.args, **tache.kwargs)
check("Rony est prévenu avec les chiffres du client", envois and envois[0]["event"] == "passerelle_coaching" and "12 contacts" in envois[0]["message"])
check("et son téléphone", envois and "0690 12 34 56" in envois[0]["message"])

print("\n=== Notifications ===")
for invalide in [{}, {"endpoint": "http://x", "keys": {"p256dh": "a", "auth": "b"}}, {"endpoint": "https://x", "keys": {}}]:
    try:
        push.abonnement_valide(invalide)
        check(f"abonnement refusé {invalide}", False)
    except ValueError:
        check(f"abonnement refusé {str(invalide)[:30]}", True)

ecrits = []
abonnes = [{"endpoint": f"https://push.test/{i}", "keys": {"p256dh": "k", "auth": "a"}} for i in range(5)]
with patch.object(push, "abonnements", return_value=abonnes), patch.object(push, "_ecrire", side_effect=lambda c, l: ecrits.append(l)):
    push.abonner(CLIENT, {"endpoint": "https://push.test/nouveau", "keys": {"p256dh": "k", "auth": "a"}})
check("5 appareils au plus, le plus récent gardé", len(ecrits[0]) == 5 and ecrits[0][-1]["endpoint"].endswith("nouveau") and ecrits[0][0]["endpoint"].endswith("/1"))

with patch.dict("os.environ", {"VAPID_PUBLIC_KEY": "", "VAPID_PRIVATE_KEY": ""}):
    code, cle = statut(portal_main.portal_push_cle, authorization=BEARER)
    check("sans clés VAPID : pas de notifications proposées", code == 200 and cle["cle"] is None)
    check("sans clés VAPID : aucun envoi", push.envoyer(CLIENT, "t", "x") == 0)
    code, _ = statut(portal_main.portal_push_abonner, portal_main.PushAbonnementRequest(abonnement={}), authorization=BEARER)
    check("sans clés VAPID : abonnement 404", code == 404)

with patch.dict("os.environ", {"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv"}), \
     patch.object(push, "_envoyer_un", side_effect=[True, False]), \
     patch.object(push, "_ecrire", side_effect=lambda c, l: ecrits.append(l)):
    n = push.envoyer(CLIENT, "Titre", "Texte", "/", liste=abonnes[:2])
check("un abonnement expiré est retiré", n == 1 and len(ecrits[-1]) == 1)

fiche_du_jour = next(m for m, j in ns._FICHE_JOUR.items() if j == 40) if 40 in ns._FICHE_JOUR.values() else None
jour_test = 40 if fiche_du_jour else next(iter(sorted(set(ns._FICHE_JOUR.values()) - {0})))
fiche_du_jour = fiche_du_jour or next(m for m, j in ns._FICHE_JOUR.items() if j == jour_test)
dash_jour = {**DASHBOARD, "date_demarrage": J(jour_test), "parcours": "Coaching", "fiches": [
    {"id": "fx", "master_id": fiche_du_jour, "nom": "Marie - 12. MON PITCH", "etat": "À faire", "acces": "Ouvert"},
]}
message = push.message_du_jour(dash_jour, {"prospects": [
    {"id": "1", "nom": "Garage Lubin", "statut": "Contacté", "relance": J(1)},
    {"id": "2", "nom": "Mme Jean", "statut": "Client", "relance": J(1)},
]})
check("message du matin : fiche du jour", message and "Mon pitch" in message["texte"])
check("message du matin : relances (sans les clients)", message and "1 relance prévue" in message["texte"] and "Mme Jean" not in message["texte"])
check("le clic ouvre le carnet", message and message["url"] == "/?ouvrir=prospects")
check("rien à dire : pas de notification", push.message_du_jour({**dash_jour, "fiches": []}, {"prospects": []}) is None)

with patch.object(portal_main, "_require_diagnostic_api_key", return_value=None), \
     patch.dict("os.environ", {"VAPID_PUBLIC_KEY": "", "VAPID_PRIVATE_KEY": ""}):
    code, resultat = statut(portal_main.automation_notifications_du_jour, authorization="Bearer x")
check("endpoint du matin sans clés : inactif, sans erreur", code == 200 and resultat["actif"] is False)

print("\n=== Retour d'Idris : notification ===")
with patch.object(ns, "demander_retour_ia", return_value=True), \
     patch.object(ns, "generer_retour_ia_immediat", return_value=True), \
     patch.object(push, "retour_idris_pret") as notif:
    portal_main._demander_retour_ia("fiche-1", "entree-1", CLIENT)
check("retour Autonome rédigé : notification au client", notif.call_args.args == (CLIENT, "fiche-1"))

with patch.object(ns, "demander_retour_ia", return_value=True), \
     patch.object(ns, "generer_retour_ia_immediat", return_value=False), \
     patch.object(push, "retour_idris_pret") as notif:
    portal_main._demander_retour_ia("fiche-1", "entree-1", CLIENT)
check("retour Coaching (relu par Rony) : pas de notification", not notif.called)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
