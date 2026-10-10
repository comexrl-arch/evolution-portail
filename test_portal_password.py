# Tests du parcours mot de passe du portail client :
# - le lien recu par email (ouverture / mot de passe oublie) sert uniquement a
#   creer le mot de passe, une seule fois ;
# - la connexion habituelle se fait par email + mot de passe ;
# - trop d'echecs bloquent temporairement l'email (anti force brute).
#
# Entierement mockes (aucun appel reseau reel vers Notion) : la propriete
# "Mot de passe portail" de la page client est simulee par un dictionnaire.
#
# Lancer : python test_portal_password.py

import sys
from unittest.mock import patch

from fastapi import HTTPException

import portal_main
from backend.services import login_guard
from backend.services import notion_service as ns
from backend.services import portal_auth_service

portal_auth_service.SECRET_KEY = "cle-de-test-mot-de-passe"
portal_auth_service._PBKDF2_ITERATIONS = 1000  # tests rapides

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


CLIENT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
EMAIL = "client@test.com"
STOCKAGE = {}


def page_client(*_args, **_kwargs):
    proprietes = {
        "Nom": {"type": "title", "title": [{"plain_text": "Client Test"}]},
        "E-mail": {"type": "email", "email": EMAIL},
    }

    if CLIENT_ID in STOCKAGE:
        proprietes[ns.PASSWORD_PROPERTY] = {"type": "rich_text", "rich_text": [{"plain_text": STOCKAGE[CLIENT_ID]}]}

    return {"id": CLIENT_ID, "properties": proprietes}


def trouver(email):
    return page_client() if (email or "").strip().lower() == EMAIL else None


def enregistrer(client_page_id, empreinte):
    STOCKAGE[client_page_id] = empreinte


def lien():
    return portal_auth_service.create_magic_link_token(EMAIL, CLIENT_ID)


def connexion(email, mot_de_passe):
    return statut(portal_main.portal_login, portal_main.PortalPasswordLoginRequest(email=email, password=mot_de_passe))


with patch.object(ns, "get_client_page", side_effect=page_client), \
     patch.object(ns, "find_client_by_email", side_effect=trouver), \
     patch.object(ns, "definir_mot_de_passe_client", side_effect=enregistrer) as ecriture, \
     patch.object(ns, "log_portal_connection", return_value=None):

    print("=" * 80)
    print("TEST 1 : empreinte du mot de passe")
    print("=" * 80)

    empreinte = portal_auth_service.hash_password("motdepasse-solide")
    check("[1] jamais le mot de passe en clair", "motdepasse-solide" not in empreinte)
    check("[1] bon mot de passe accepte", portal_auth_service.verify_password("motdepasse-solide", empreinte))
    check("[1] mauvais mot de passe refuse", not portal_auth_service.verify_password("autre-chose", empreinte))
    check("[1] empreinte vide ou illisible refusee", not portal_auth_service.verify_password("x", "") and
          not portal_auth_service.verify_password("x", "n-importe-quoi"))
    check("[1] deux empreintes du meme mot de passe different (sel)",
          empreinte != portal_auth_service.hash_password("motdepasse-solide"))

    print("\n" + "=" * 80)
    print("TEST 2 : premiere ouverture via le lien")
    print("=" * 80)

    STOCKAGE.clear()
    login_guard._reinitialiser_pour_tests()
    jeton = lien()

    code, rep = connexion(EMAIL, "peu-importe")
    check("[2] sans mot de passe defini, connexion refusee (401 generique)",
          (code, rep) == (401, portal_main._MESSAGE_IDENTIFIANTS_INVALIDES))

    code, rep = statut(portal_main.portal_verify, portal_main.PortalVerifyRequest(token=jeton))
    check("[2] verify : lien valide, aucune session ouverte",
          code == 200 and rep["email"] == EMAIL and rep["nom"] == "Client Test"
          and rep["mot_de_passe_existant"] is False and "session_token" not in rep)

    code, rep = statut(portal_main.portal_set_password,
                       portal_main.PortalSetPasswordRequest(token=jeton, password="court"))
    check("[2] mot de passe trop court refuse (400) sans ecriture", code == 400 and ecriture.call_count == 0)

    code, rep = statut(portal_main.portal_set_password,
                       portal_main.PortalSetPasswordRequest(token=jeton, password="mon-mot-de-passe"))
    check("[2] creation du mot de passe : session ouverte", code == 200 and rep.get("session_token"))
    check("[2] session valide pour ce client",
          portal_auth_service.verify_session_token(rep["session_token"])["client_page_id"] == CLIENT_ID)
    check("[2] seule l'empreinte est stockee", "mon-mot-de-passe" not in STOCKAGE[CLIENT_ID])

    code, rep = statut(portal_main.portal_set_password,
                       portal_main.PortalSetPasswordRequest(token=jeton, password="un-autre-mot-de-passe"))
    check("[2] le meme lien ne sert pas deux fois", (code, rep) == (401, portal_main._MESSAGE_LIEN_UTILISE))
    code, _ = statut(portal_main.portal_verify, portal_main.PortalVerifyRequest(token=jeton))
    check("[2] verify refuse aussi le lien deja utilise", code == 401)

    print("\n" + "=" * 80)
    print("TEST 3 : connexion par email + mot de passe")
    print("=" * 80)

    code, rep = connexion("  Client@Test.com ", "mon-mot-de-passe")
    check("[3] bon mot de passe (email nettoye) : session ouverte", code == 200 and rep.get("session_token"))
    code, rep = connexion(EMAIL, "mauvais-mot-de-passe")
    check("[3] mauvais mot de passe : 401 generique", (code, rep) == (401, portal_main._MESSAGE_IDENTIFIANTS_INVALIDES))
    code, rep = connexion("inconnu@test.com", "mon-mot-de-passe")
    check("[3] email inconnu : meme 401 generique", (code, rep) == (401, portal_main._MESSAGE_IDENTIFIANTS_INVALIDES))
    code, _ = statut(portal_main.portal_get_fiche, "x", authorization="Bearer " + lien())
    check("[3] le lien email n'est pas une session", code == 401)

    print("\n" + "=" * 80)
    print("TEST 4 : mot de passe oublie (nouveau lien)")
    print("=" * 80)

    STOCKAGE[CLIENT_ID] = portal_auth_service.hash_password("ancien-mot-de-passe", defini_le=1000.0)
    nouveau = lien()
    code, rep = statut(portal_main.portal_verify, portal_main.PortalVerifyRequest(token=nouveau))
    check("[4] lien emis apres le mot de passe actuel : accepte", code == 200 and rep["mot_de_passe_existant"] is True)
    code, _ = statut(portal_main.portal_set_password,
                     portal_main.PortalSetPasswordRequest(token=nouveau, password="nouveau-mot-de-passe"))
    check("[4] nouveau mot de passe enregistre", code == 200)
    check("[4] ancien mot de passe refuse", connexion(EMAIL, "ancien-mot-de-passe")[0] == 401)
    check("[4] nouveau mot de passe accepte", connexion(EMAIL, "nouveau-mot-de-passe")[0] == 200)

    print("\n" + "=" * 80)
    print("TEST 5 : anti force brute")
    print("=" * 80)

    login_guard._reinitialiser_pour_tests()

    for _ in range(login_guard.EMAIL_MAX_ECHECS):
        connexion(EMAIL, "mauvais")

    code, _ = connexion(EMAIL, "nouveau-mot-de-passe")
    check("[5] apres trop d'echecs, meme le bon mot de passe est bloque (429)", code == 429)
    code, _ = connexion("autre@test.com", "x")
    check("[5] un autre email n'est pas bloque", code == 401)

    jeton = lien()
    statut(portal_main.portal_set_password, portal_main.PortalSetPasswordRequest(token=jeton, password="apres-blocage-1"))
    check("[5] redefinir le mot de passe via le lien debloque l'email", connexion(EMAIL, "apres-blocage-1")[0] == 200)

    print("\n" + "=" * 80)
    print("TEST 6 : Notion indisponible")
    print("=" * 80)

    login_guard._reinitialiser_pour_tests()

    with patch.object(ns, "find_client_by_email", side_effect=RuntimeError("Erreur Notion https://api.notion.com")):
        code, rep = connexion(EMAIL, "x")
        check("[6] login : 503 generique", (code, rep) == (503, portal_main._MESSAGE_SERVICE_INDISPONIBLE))

    with patch.object(ns, "definir_mot_de_passe_client", side_effect=RuntimeError("Erreur Notion")):
        code, rep = statut(portal_main.portal_set_password,
                           portal_main.PortalSetPasswordRequest(token=lien(), password="encore-un-autre"))
        check("[6] set-password : 503 generique", (code, rep) == (503, portal_main._MESSAGE_SERVICE_INDISPONIBLE))


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
