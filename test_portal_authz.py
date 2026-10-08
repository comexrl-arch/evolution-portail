# Tests d'autorisation de GET /portal/fiches/{id} et GET /portal/livrables/{id}.
#
# Entierement mockes (aucun appel reseau reel vers Notion) : les fonctions de
# route sont appelees directement avec de vrais jetons de session, et seuls
# les acces Notion (dashboard, fiche, page de livrable, contenu) sont
# remplaces. Meme style que test_onboarding.py (script simple, pas de
# framework de test, aucune dependance supplementaire).
#
# Lancer : python test_portal_authz.py

import sys
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-autorisation"

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
    # Renvoie (code HTTP, resultat ou detail). 200 si la route repond sans erreur.
    try:
        return 200, fonction(*args, **kwargs)
    except HTTPException as error:
        return error.status_code, error.detail


def bearer(client_page_id, email="client@test.com"):
    return "Bearer " + portal_auth_service.create_session_token(email, client_page_id)


# --- Jeu de donnees : deux clients, chacun avec ses fiches --------------------

CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

FICHE_A_OUVERTE = "a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1"
FICHE_A_BLOQUEE = "a2a2a2a2-a2a2-a2a2-a2a2-a2a2a2a2a2a2"
FICHE_B = "b1b1b1b1-b1b1-b1b1-b1b1-b1b1b1b1b1b1"

MASTER_OUVERTE = "11111111111111111111111111111111"
MASTER_BLOQUEE = "22222222222222222222222222222222"
MASTER_B = "33333333333333333333333333333333"

DASHBOARDS = {
    CLIENT_A: {
        "nom": "Client A",
        "parcours": "Coaching 90 jours",
        "fiches": [
            {"id": FICHE_A_OUVERTE, "master_id": MASTER_OUVERTE, "acces": "🚀 En cours"},
            {"id": FICHE_A_BLOQUEE, "master_id": MASTER_BLOQUEE, "acces": "🔒 Bloqué"},
        ],
    },
    CLIENT_B: {
        "nom": "Client B",
        "parcours": "Coaching 90 jours",
        "fiches": [{"id": FICHE_B, "master_id": MASTER_B, "acces": "🚀 En cours"}],
    },
}


def fake_dashboard(client_page_id):
    return DASHBOARDS[client_page_id]


def relation(*ids):
    return {"type": "relation", "relation": [{"id": i} for i in ids]}


def page_livrable(client=(), master=()):
    return {
        "id": "livrable-page",
        "properties": {
            "Nom": {"type": "title", "title": [{"plain_text": "Mon livrable"}]},
            "Fiche Client": relation(*client),
            "Fiche Master (référence)": relation(*master),
        },
    }


def dash_with(parcours, fiches):
    return {"nom": "X", "parcours": parcours, "fiches": fiches}


# --- Fiches --------------------------------------------------------------------

print("=" * 80)
print("TEST 1/4 : GET /portal/fiches/{id} - fiche ouverte, bloquee, autre client")
print("=" * 80)

appels_get_fiche = []


def fake_get_fiche(fiche_client_id, client_page_id):
    appels_get_fiche.append((fiche_client_id, client_page_id))
    return {"fiche_client_id": fiche_client_id, "nom": "Fiche", "mode": "unique"}


with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
     patch.object(ns, "get_fiche", side_effect=fake_get_fiche):

    appels_get_fiche.clear()
    code, corps = statut(portal_main.portal_get_fiche, FICHE_A_OUVERTE, authorization=bearer(CLIENT_A))
    check("[1] client A -> sa fiche ouverte : 200", code == 200)
    check("[1] la fiche est lue avec l'id canonique et le bon client", appels_get_fiche == [(FICHE_A_OUVERTE, CLIENT_A)])

    appels_get_fiche.clear()
    code, _ = statut(portal_main.portal_get_fiche, FICHE_A_BLOQUEE, authorization=bearer(CLIENT_A))
    check("[2] client A -> sa fiche bloquee : 403", code == 403)
    check("[2] get_fiche n'est pas appelee", appels_get_fiche == [])

    appels_get_fiche.clear()
    code, _ = statut(portal_main.portal_get_fiche, FICHE_B, authorization=bearer(CLIENT_A))
    check("[3] client A -> fiche du client B : 404", code == 404)
    check("[3] get_fiche n'est pas appelee", appels_get_fiche == [])

    code, _ = statut(portal_main.portal_get_fiche, "00000000-0000-0000-0000-000000000000", authorization=bearer(CLIENT_A))
    check("[3] client A -> fiche inconnue : 404", code == 404)

    appels_get_fiche.clear()
    sans_tirets = FICHE_A_OUVERTE.replace("-", "")
    code, _ = statut(portal_main.portal_get_fiche, sans_tirets, authorization=bearer(CLIENT_A))
    check("[R2] id sans tirets accepte : 200", code == 200)
    check("[R2] get_fiche recoit l'id canonique du dashboard (avec tirets)", appels_get_fiche == [(FICHE_A_OUVERTE, CLIENT_A)])


# --- Livrables -----------------------------------------------------------------

print("\n" + "=" * 80)
print("TEST 2/4 : GET /portal/livrables/{id} - livrable du client, d'un autre client")
print("=" * 80)

contenus_lus = []


def fake_contenu(page_id, checks=False):
    contenus_lus.append(page_id)
    return "contenu du livrable"


def route_livrable(client_page_id, page):
    with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
         patch.object(ns, "_get_page", return_value=page), \
         patch.object(ns, "_get_page_content", side_effect=fake_contenu):
        return statut(portal_main.portal_get_livrable, "livrable-page", authorization=bearer(client_page_id))


contenus_lus.clear()
code, corps = route_livrable(CLIENT_A, page_livrable(master=[ns._add_dashes(MASTER_OUVERTE)]))
check("[4] client A -> livrable lie au master de sa fiche ouverte : 200", code == 200)
check("[4] le contenu est renvoye", code == 200 and corps["contenu"] == "contenu du livrable" and corps["nom"] == "Mon livrable")

contenus_lus.clear()
code, corps = route_livrable(CLIENT_A, page_livrable(client=[FICHE_A_OUVERTE]))
check("[5] client A -> livrable lie via Fiche Client a sa fiche ouverte : 200", code == 200)

contenus_lus.clear()
code, _ = route_livrable(CLIENT_A, page_livrable(client=[FICHE_B], master=[ns._add_dashes(MASTER_B)]))
check("[6] client A -> livrable du client B : 404", code == 404)
check("[6] le contenu n'est jamais lu", contenus_lus == [])


print("\n" + "=" * 80)
print("TEST 3/4 : session absente ou invalide -> 401 sur les deux routes")
print("=" * 80)

with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard) as dash_mock, \
     patch.object(ns, "get_fiche", side_effect=fake_get_fiche), \
     patch.object(ns, "_get_page", return_value=page_livrable(master=[ns._add_dashes(MASTER_OUVERTE)])):

    jeton_lien = "Bearer " + portal_auth_service.create_magic_link_token("client@test.com", CLIENT_A)

    for libelle, entete in (
        ("sans en-tete", ""),
        ("jeton invalide", "Bearer n-importe-quoi"),
        ("jeton de lien magique (mauvais type)", jeton_lien),
    ):
        code, _ = statut(portal_main.portal_get_fiche, FICHE_A_OUVERTE, authorization=entete)
        check(f"[7] fiche, {libelle} : 401", code == 401)
        code, _ = statut(portal_main.portal_get_livrable, "livrable-page", authorization=entete)
        check(f"[7] livrable, {libelle} : 401", code == 401)

    check("[7] aucun acces Notion avant l'authentification", dash_mock.call_count == 0)


print("\n" + "=" * 80)
print("TEST 4/4 : regressions - livrable lie a une fiche bloquee, Atelier, page sans relation, erreurs Notion")
print("=" * 80)

contenus_lus.clear()
code, _ = route_livrable(CLIENT_A, page_livrable(master=[ns._add_dashes(MASTER_BLOQUEE)]))
check("[R1] livrable lie seulement a une fiche bloquee : 404", code == 404)
code, _ = route_livrable(CLIENT_A, page_livrable(client=[FICHE_A_BLOQUEE]))
check("[R1] idem via Fiche Client : 404", code == 404)
check("[R1] le contenu n'est jamais lu", contenus_lus == [])

fiche_sans_livrable = next(iter(ns._ATELIER_SANS_LIVRABLES))
fiche_atelier_ok = "cccccccccccccccccccccccccccccccc"
dash_atelier = dash_with("Atelier", [
    {"id": "f1111111-1111-1111-1111-111111111111", "master_id": fiche_sans_livrable, "acces": "🚀 En cours"},
    {"id": "f2222222-2222-2222-2222-222222222222", "master_id": fiche_atelier_ok, "acces": "🚀 En cours"},
])
dash_90j = dash_with("Coaching 90 jours", dash_atelier["fiches"])
props_8_14 = page_livrable(master=[ns._add_dashes(fiche_sans_livrable)])["properties"]
props_autre = page_livrable(master=[ns._add_dashes(fiche_atelier_ok)])["properties"]

check("[R3] Atelier : livrable de la fiche 8/14 refuse", ns._livrable_autorise(props_8_14, dash_atelier) is False)
check("[R3] Atelier : livrable d'une autre fiche ouverte accepte", ns._livrable_autorise(props_autre, dash_atelier) is True)
check("[R3] hors Atelier : le meme livrable de la fiche 8/14 reste accepte", ns._livrable_autorise(props_8_14, dash_90j) is True)

contenus_lus.clear()
page_vide = {"id": "autre-page", "properties": {"Nom": {"type": "title", "title": [{"plain_text": "Pas un livrable"}]}}}
code, _ = route_livrable(CLIENT_A, page_vide)
check("[R4] page sans relation Fiche Client/Master : 404", code == 404)
check("[R4] le contenu n'est jamais lu", contenus_lus == [])

check("[R4] dashboard sans fiches / ids absents : refus sans exception",
      ns._livrable_autorise(page_livrable(master=[ns._add_dashes(MASTER_OUVERTE)])["properties"],
                            {"fiches": [{"acces": "🚀 En cours"}, {}]}) is False)

# Une erreur Notion n'est jamais transformee en 404.
with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
     patch.object(ns, "_get_page", side_effect=RuntimeError("Erreur Notion (page x) : boom")):
    code, _ = statut(portal_main.portal_get_livrable, "livrable-page", authorization=bearer(CLIENT_A))
    check("[E1] erreur Notion sur la page du livrable : 503 (pas 404)", code == 503)

with patch.object(ns, "get_client_dashboard", side_effect=RuntimeError("Erreur Notion (dashboard)")):
    code, _ = statut(portal_main.portal_get_livrable, "livrable-page", authorization=bearer(CLIENT_A))
    check("[E1] erreur Notion sur le dashboard (livrable) : 503", code == 503)
    code, _ = statut(portal_main.portal_get_fiche, FICHE_A_OUVERTE, authorization=bearer(CLIENT_A))
    check("[E1] erreur Notion sur le dashboard (fiche) : 503", code == 503)

with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
     patch.object(ns, "get_fiche", side_effect=RuntimeError("Erreur Notion (fiche)")):
    code, _ = statut(portal_main.portal_get_fiche, FICHE_A_OUVERTE, authorization=bearer(CLIENT_A))
    check("[E1] erreur Notion sur get_fiche : 503", code == 503)

with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
     patch.object(ns, "_get_page", return_value=page_livrable(master=[ns._add_dashes(MASTER_OUVERTE)])), \
     patch.object(ns, "_get_page_content", side_effect=RuntimeError("Erreur Notion (blocs)")):
    code, _ = statut(portal_main.portal_get_livrable, "livrable-page", authorization=bearer(CLIENT_A))
    check("[E1] erreur Notion sur le contenu du livrable : 503", code == 503)

# Un bug interne (KeyError = sous-classe de LookupError) n'est jamais un 404.
check("[E2] LivrableNonAutorise reste un LookupError", issubclass(ns.LivrableNonAutorise, LookupError))

for libelle, patches in (
    ("KeyError dans le contenu du livrable", {"_get_page_content": KeyError("bloc")}),
    ("KeyError dans la lecture de la page", {"_get_page": KeyError("id")}),
):
    with patch.object(ns, "get_client_dashboard", side_effect=fake_dashboard), \
         patch.object(ns, "_get_page", return_value=page_livrable(master=[ns._add_dashes(MASTER_OUVERTE)])), \
         patch.object(ns, "_get_page_content", return_value="x"):
        cible, erreur = next(iter(patches.items()))

        with patch.object(ns, cible, side_effect=erreur):
            try:
                portal_main.portal_get_livrable("livrable-page", authorization=bearer(CLIENT_A))
                resultat = "aucune erreur"
            except HTTPException as error:
                resultat = f"HTTP {error.status_code}"
            except KeyError:
                resultat = "KeyError propagee"

        check(f"[E2] {libelle} : jamais converti en 404", resultat == "KeyError propagee")

with patch.object(ns, "get_client_dashboard", side_effect=KeyError("fiches")):
    try:
        portal_main.portal_get_livrable("livrable-page", authorization=bearer(CLIENT_A))
        resultat = "aucune erreur"
    except HTTPException as error:
        resultat = f"HTTP {error.status_code}"
    except KeyError:
        resultat = "KeyError propagee"

    check("[E2] KeyError dans get_client_dashboard : jamais converti en 404", resultat == "KeyError propagee")


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
