# Tests du parcours "eVolution Autonome" (decision du 21/10/2026), entierement
# mockes (aucun appel reseau) : ouverture des fiches sans verrou coach,
# remplissage automatique de la fiche 8, aiguillage alerte coach / fiche 8
# automatique, syntheses mensuelles (axe, echeance, doublon), protection des
# routes /automation et onboarding avec Parcours = Autonome.
#
# Lancer : python test_autonome.py

import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import portal_main
from backend.services import notion_service as ns

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


FICHE7 = "39ffaffd87588086b588e7a82738c7b1"
FICHE8 = ns._DIAGNOSTIC_FICHE8_MASTER_ID
FICHE9 = "39ffaffd8758805ebebfd5f5c3914a56"


def fiches_diagnostic():
    return [
        {"master_id": FICHE7, "etat": "Terminé"},
        {"master_id": FICHE8, "etat": "Pas commencé"},
        {"master_id": FICHE9, "etat": "Pas commencé"},
    ]


print("=" * 80)
print("TEST 1 : ouverture de la fiche 8 avec et sans verrou coach")
print("=" * 80)

fiches = fiches_diagnostic()
ns._apply_acces(fiches, None)
check("coaching : fiche 8 bloquee tant que le coach ne l'a pas validee", fiches[1]["acces"] == "🔒 Bloqué")
check("coaching : fiche 9 bloquee derriere la fiche 8", fiches[2]["acces"] == "🔒 Bloqué")

fiches = fiches_diagnostic()
ns._apply_acces(fiches, None, verrou_coach=False)
check("autonome : fiche 8 ouverte des que la fiche 7 est terminee", fiches[1]["acces"] == "🚀 En cours")
check("autonome : fiche 9 attend toujours la fiche 8", fiches[2]["acces"] == "🔒 Bloqué")


print("\n" + "=" * 80)
print("TEST 2 : remplissage automatique de la fiche 8")
print("=" * 80)

rapport = {
    "complet": True,
    "fiche_8": {"fiche_client_id": "f8"},
    "zones": [
        {"zone": "Offre", "score": 2},
        {"zone": "Visibilité", "score": 1},
        {"zone": "Prospection", "score": 1},
        {"zone": "Conversion", "score": 3},
        {"zone": "Suivi commercial", "score": 2},
    ],
    "propositions": [
        {"label": "Score d'Offre", "valeur": "2 / 3"},
        {"label": "SCORE TOTAL", "valeur": "9 / 15"},
        {"label": "Priorité 1", "valeur": "Gagner en visibilité"},
    ],
}
champs = [
    {"block_id": "b1", "type": "bulleted_list_item", "label": "Score d'Offre", "valeur": "/ 3"},
    {"block_id": "b2", "type": "bulleted_list_item", "label": "SCORE TOTAL", "valeur": "/ 15"},
    {"block_id": "b3", "type": "numbered_list_item", "label": "Priorité 1", "valeur": ""},
    {"block_id": "b4", "type": "numbered_list_item", "label": "Autre", "valeur": ""},
]
reponse = MagicMock()

with patch.object(ns, "get_diagnostic_rapport", return_value=rapport), \
        patch.object(ns, "get_diagnostic_fiche8", return_value=champs), \
        patch.object(ns, "update_diagnostic_fiche8") as maj, \
        patch.object(ns._http, "patch", return_value=reponse) as http_patch, \
        patch.object(ns, "_headers", return_value={}), \
        patch.object(ns, "validate_fiche") as valider:
    resultat = ns.remplir_fiche8_autonome("client-1")
    ecrits = {u["label"]: u["valeur"] for u in maj.call_args[0][0]}
    enfants = http_patch.call_args.kwargs["json"]["children"]
    textes = " ".join(
        part["text"]["content"]
        for bloc in enfants
        for part in bloc.get(bloc["type"], {}).get("rich_text", [])
    )

check("renvoie True quand le diagnostic est complet", resultat is True)
check("ecrit les scores et priorites calcules", ecrits == {"Score d'Offre": "2 / 3", "SCORE TOTAL": "9 / 15", "Priorité 1": "Gagner en visibilité"})
check("a egalite, la zone la plus faible suit l'ordre du parcours (Visibilite)", ns._RECOMMANDATION_AUTONOME["Visibilité"] in textes)
check("ajoute la mention du Coaching 90 jours", "Coaching 90 jours" in textes)
check("valide la fiche 8", valider.call_args[0][0] == "f8")

with patch.object(ns, "get_diagnostic_rapport", return_value={**rapport, "complet": False}), \
        patch.object(ns, "update_diagnostic_fiche8") as maj, \
        patch.object(ns, "validate_fiche") as valider:
    resultat = ns.remplir_fiche8_autonome("client-1")

check("diagnostic incomplet : renvoie False", resultat is False)
check("diagnostic incomplet : n'ecrit rien et ne valide rien", not maj.called and not valider.called)


print("\n" + "=" * 80)
print("TEST 3 : aiguillage fin de diagnostic (alerte coach ou fiche 8 automatique)")
print("=" * 80)

infos_autonome = {"client_nom": "A", "client_email": "a@test.com", "parcours": "Autonome"}
infos_coaching = {"client_nom": "C", "client_email": "c@test.com", "parcours": "Coaching 90 jours"}

with patch.object(ns, "diagnostic_vient_de_se_terminer", return_value=infos_autonome), \
        patch.object(ns, "remplir_fiche8_autonome") as remplir, \
        patch.object(ns, "alerter_coach_diagnostic") as alerter:
    portal_main._alerter_si_diagnostic_termine("client-a", "fiche")

check("autonome : fiche 8 remplie automatiquement", remplir.called)
check("autonome : aucune alerte coach", not alerter.called)

with patch.object(ns, "diagnostic_vient_de_se_terminer", return_value=infos_coaching), \
        patch.object(ns, "remplir_fiche8_autonome") as remplir, \
        patch.object(ns, "alerter_coach_diagnostic") as alerter:
    portal_main._alerter_si_diagnostic_termine("client-c", "fiche")

check("coaching : alerte coach envoyee", alerter.called)
check("coaching : fiche 8 jamais remplie automatiquement", not remplir.called)

with patch.object(ns, "diagnostic_vient_de_se_terminer", return_value=infos_autonome), \
        patch.object(ns, "remplir_fiche8_autonome", side_effect=RuntimeError("Notion")), \
        patch.object(ns, "alerter_coach_diagnostic"):
    try:
        portal_main._alerter_si_diagnostic_termine("client-a", "fiche")
        check("autonome : un echec du remplissage ne fait pas planter la validation", True)
    except Exception:
        check("autonome : un echec du remplissage ne fait pas planter la validation", False)


print("\n" + "=" * 80)
print("TEST 4 : axe de la synthese")
print("=" * 80)

check("aucune nouvelle fiche -> reprise", ns._axe_synthese(5, 5) == "reprise")
check("1 ou 2 nouvelles fiches -> a_faire", ns._axe_synthese(7, 5) == "a_faire")
check("3 nouvelles fiches ou plus -> encouragement", ns._axe_synthese(8, 5) == "encouragement")
check("mois 1 sans synthese precedente : compare a 0", ns._axe_synthese(4, None) == "encouragement")


print("\n" + "=" * 80)
print("TEST 5 : echeance des syntheses (J30, pas J29, pas de doublon)")
print("=" * 80)


def client_row(cid, debut, etat="En cours"):
    return {
        "id": cid,
        "properties": {
            "État": {"type": "status", "status": {"name": etat}},
            "Date de démarrage": {"type": "date", "date": {"start": debut}},
        },
    }


rows = [
    client_row("j30", "2026-09-21"),
    client_row("j29", "2026-09-22"),
    client_row("deja", "2026-09-21"),
    client_row("pause", "2026-09-21", etat="Terminé"),
]


def fake_syntheses(cid):
    return [{"mois": 1, "fiches_terminees": 3, "texte": "x"}] if cid == "deja" else []


with patch.object(ns, "_query_data_source", return_value=rows), \
        patch.object(ns, "_syntheses_brutes", side_effect=fake_syntheses), \
        patch.object(ns, "donnees_synthese_autonome", side_effect=lambda cid, mois, s: {"client_page_id": cid, "numero_mois": mois}) as donnees:
    dus = ns.clients_autonome_synthese_due(date(2026, 10, 21))

ids = [d["client_page_id"] for d in dus]
check("client a J30 : synthese due", "j30" in ids)
check("client a J29 : pas encore", "j29" not in ids)
check("synthese du mois deja faite : pas de doublon", "deja" not in ids)
check("client qui n'est plus En cours : ignore", "pause" not in ids)
check("numero de mois = 1 a J30", dus and dus[0]["numero_mois"] == 1)


print("\n" + "=" * 80)
print("TEST 6 : routes /automation protegees par la cle technique")
print("=" * 80)

with patch.dict(os.environ, {"COACH_DIAGNOSTIC_API_KEY": "cle-test"}):
    for label, appel in [
        ("syntheses-dues", lambda: portal_main.automation_syntheses_dues(authorization="")),
        ("enregistrer", lambda: portal_main.automation_enregistrer_synthese(
            portal_main.SyntheseAutonomeRequest(client_page_id="c", mois=1, axe="a_faire", texte="t"),
            authorization="Bearer mauvaise",
        )),
        ("statut", lambda: portal_main.automation_statut_synthese(
            "s", portal_main.SyntheseStatutRequest(statut="Envoyée"), authorization="",
        )),
    ]:
        try:
            appel()
            check(f"{label} : refuse sans cle valide", False)
        except HTTPException as error:
            check(f"{label} : refuse sans cle valide (401)", error.status_code == 401)

    with patch.object(ns, "clients_autonome_synthese_due", return_value=[{"client_page_id": "c"}]):
        reponse = portal_main.automation_syntheses_dues(authorization="Bearer cle-test")
    check("syntheses-dues : repond avec la bonne cle", reponse == {"clients": [{"client_page_id": "c"}]})

    try:
        portal_main.automation_statut_synthese(
            "s", portal_main.SyntheseStatutRequest(statut="À relire"), authorization="Bearer cle-test"
        )
        check("statut : refuse une valeur hors Envoyee/Bloquee", False)
    except HTTPException as error:
        check("statut : refuse une valeur hors Envoyee/Bloquee (422)", error.status_code == 422)


print("\n" + "=" * 80)
print("TEST 7 : onboarding avec Parcours = Autonome")
print("=" * 80)

crees = []


def fake_create_page(data_source_id, properties):
    crees.append((data_source_id, properties))
    return {"id": f"page-{len(crees)}"}


with patch.object(ns, "find_client_by_email", return_value=None), \
        patch.object(ns, "_create_page", side_effect=fake_create_page), \
        patch.object(ns, "send_magic_link", return_value=None, create=True), \
        patch.object(ns, "_cache_clear"):
    try:
        ns.onboard_client("Test Auto", "auto@test.com", parcours="Autonome")
    except Exception:
        pass

client_props = crees[0][1] if crees else {}
fiches_creees = [p for ds, p in crees if ds == ns.FICHES_CLIENT_DATA_SOURCE_ID]
check("Parcours ecrit = Autonome", client_props.get("Parcours") == {"select": {"name": "Autonome"}})
check("toutes les fiches sont creees (comme le coaching)", len(fiches_creees) == len(ns.FICHE_SCHEMAS))
check("nom de parcours inconnu -> Coaching 90 jours", ns._nom_parcours("") == "Coaching 90 jours")


print("\n" + "=" * 80)
print("TEST 8 : jauge de realisation des syntheses affichees")
print("=" * 80)

brutes = [
    {"mois": 2, "date": "2026-11-20", "axe": "a_faire", "texte": "t2", "statut": "Envoyée", "fiches_terminees": 18},
    {"mois": 1, "date": "2026-10-21", "axe": "encouragement", "texte": "t1", "statut": "Envoyée", "fiches_terminees": 15},
    {"mois": 3, "date": "2026-12-20", "axe": "reprise", "texte": "t3", "statut": "À relire", "fiches_terminees": 18},
]

with patch.object(ns, "_syntheses_brutes", return_value=brutes):
    affichees = ns.syntheses_du_client("c")

check("seules les syntheses Envoyee sont affichees", [a["mois"] for a in affichees] == [2, 1])
check("mois 1 : 15 fiches prevues a J30", affichees[1]["fiches_prevues"] == ns._fiches_prevues(30) == 15)
check("mois 1 : toutes les fiches comptent pour le mois", affichees[1]["fiches_du_mois"] == 15)
check("mois 2 : progression calculee depuis le mois 1", affichees[0]["fiches_du_mois"] == 3)
check("total du parcours = 24 fiches", affichees[0]["fiches_total"] == 24)

with patch.object(ns, "_syntheses_brutes", side_effect=RuntimeError("Notion")):
    check("Notion en panne : liste vide, pas d'erreur", ns.syntheses_du_client("c") == [])


print("\n" + "=" * 80)
print(f"{passed} PASS / {failed} FAIL")
print("=" * 80)
sys.exit(1 if failed else 0)
