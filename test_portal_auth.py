# Tests de backend/services/portal_auth_service.py (issue #4, P0 : cycle de
# vie du jeton de lien magique) : expiration deja couverte par itsdangerous
# (max_age), ce fichier couvre ce qui manquait - usage unique et invalidation
# d'un ancien jeton des qu'un renvoi en emet un nouveau pour le meme client.
# Meme style que test_onboarding.py.
#
# Lancer : PORTAL_SECRET_KEY=test python test_portal_auth.py

import os
import sys
import threading

os.environ.setdefault("PORTAL_SECRET_KEY", "test-secret-key-for-tests-only")

from backend.services import portal_auth_service as auth  # noqa: E402

auth.SECRET_KEY = os.environ["PORTAL_SECRET_KEY"]

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


def reset():
    auth._active_jti_by_client.clear()
    auth._consumed_jti.clear()


print("=" * 80)
print("TEST 1/4 : usage unique - un jeton verifie une fois est refuse la 2e fois")
print("=" * 80)

reset()
token = auth.create_magic_link_token("client@test.com", "page-1")

data = auth.verify_magic_link_token(token)
check("1ere verification reussit", data["email"] == "client@test.com" and data["client_page_id"] == "page-1")

try:
    auth.verify_magic_link_token(token)
    check("2e verification du meme jeton est refusee", False)
except ValueError as error:
    check("2e verification du meme jeton est refusee", True)
    check("message explicite (deja utilise)", "deja" in str(error))


print("\n" + "=" * 80)
print("TEST 2/4 : renvoi - un nouveau jeton invalide l'ancien pour le meme client")
print("=" * 80)

reset()
old_token = auth.create_magic_link_token("client@test.com", "page-1")
new_token = auth.create_magic_link_token("client@test.com", "page-1")  # renvoi

try:
    auth.verify_magic_link_token(old_token)
    check("l'ancien jeton (avant renvoi) est refuse", False)
except ValueError as error:
    check("l'ancien jeton (avant renvoi) est refuse", True)
    check("message explicite (lien plus recent envoye)", "plus recent" in str(error))

data = auth.verify_magic_link_token(new_token)
check("le nouveau jeton (apres renvoi) reste valide", data["client_page_id"] == "page-1")


print("\n" + "=" * 80)
print("TEST 3/4 : deux clients differents ont des jetons independants")
print("=" * 80)

reset()
token_a = auth.create_magic_link_token("a@test.com", "page-a")
token_b = auth.create_magic_link_token("b@test.com", "page-b")

data_a = auth.verify_magic_link_token(token_a)
data_b = auth.verify_magic_link_token(token_b)
check("jeton du client A verifie independamment", data_a["client_page_id"] == "page-a")
check("jeton du client B verifie independamment (non affecte par A)", data_b["client_page_id"] == "page-b")


print("\n" + "=" * 80)
print("TEST 4/4 : concurrence - deux verifications simultanees du meme jeton,")
print("une seule doit reussir (protection par verrou, pas de double-consommation)")
print("=" * 80)

reset()
concurrent_token = auth.create_magic_link_token("concurrent@test.com", "page-c")

successes = []
failures = []
start_barrier = threading.Barrier(2)


def try_verify():
    start_barrier.wait()  # les 2 threads entrent dans verify_magic_link_token au meme instant
    try:
        auth.verify_magic_link_token(concurrent_token)
        successes.append(True)
    except ValueError:
        failures.append(True)


threads = [threading.Thread(target=try_verify) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()

check("exactement 1 des 2 verifications simultanees reussit", len(successes) == 1)
check("exactement 1 des 2 verifications simultanees echoue (deja consomme)", len(failures) == 1)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
