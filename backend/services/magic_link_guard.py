# Tests de backend/services/magic_link_guard.py (issue #4, P0 : idempotence
# des renvois + rate limiting par email normalise et par IP). Meme style que
# test_onboarding.py : script simple, pas de framework de test, horloge
# monkeypatchee (time.monotonic) pour rester deterministe sans vrais sleep().
#
# Lancer : python test_magic_link_guard.py

import sys
from unittest.mock import patch

from backend.services import magic_link_guard as guard

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


print("=" * 80)
print("TEST 1/4 : idempotence - un renvoi immediat (double-clic) est filtre")
print("=" * 80)

guard._reset_for_tests()
clock = {"t": 1000.0}

with patch.object(guard.time, "monotonic", side_effect=lambda: clock["t"]):
    first = guard.check_and_register("client@test.com", "1.2.3.4")
    check("1ere demande acceptee", first.should_send and first.reason == "ok")

    clock["t"] += 1  # 1s plus tard, dans la fenetre de cooldown (30s)
    second = guard.check_and_register("client@test.com", "1.2.3.4")
    check("renvoi immediat filtre (cooldown)", not second.should_send and second.reason == "cooldown")

    clock["t"] += guard.COOLDOWN_SECONDS + 1  # apres le cooldown
    third = guard.check_and_register("client@test.com", "1.2.3.4")
    check("apres le cooldown, un nouveau renvoi est de nouveau accepte", third.should_send and third.reason == "ok")


print("\n" + "=" * 80)
print("TEST 2/4 : rate limiting par email normalise sur la fenetre glissante")
print("=" * 80)

guard._reset_for_tests()
clock = {"t": 2000.0}

with patch.object(guard.time, "monotonic", side_effect=lambda: clock["t"]):
    results = []
    for _ in range(guard.EMAIL_MAX_REQUESTS):
        results.append(guard.check_and_register("quota@test.com", "9.9.9.9").should_send)
        clock["t"] += guard.COOLDOWN_SECONDS + 1  # hors cooldown a chaque fois

    check(f"les {guard.EMAIL_MAX_REQUESTS} premieres demandes (hors cooldown) passent", all(results))

    over_quota = guard.check_and_register("quota@test.com", "9.9.9.9")
    check("la demande suivante est rate-limitee (email)", not over_quota.should_send and over_quota.reason == "rate_limited_email")

    clock["t"] += guard.EMAIL_WINDOW_SECONDS + 1  # fenetre expiree
    after_window = guard.check_and_register("quota@test.com", "9.9.9.9")
    check("apres expiration de la fenetre, une nouvelle demande passe", after_window.should_send)


print("\n" + "=" * 80)
print("TEST 3/4 : rate limiting par IP, independant de l'email")
print("=" * 80)

guard._reset_for_tests()
clock = {"t": 3000.0}

with patch.object(guard.time, "monotonic", side_effect=lambda: clock["t"]):
    results = []
    for i in range(guard.IP_MAX_REQUESTS):
        results.append(guard.check_and_register(f"user{i}@test.com", "5.5.5.5").should_send)
        clock["t"] += guard.COOLDOWN_SECONDS + 1

    check(f"les {guard.IP_MAX_REQUESTS} premieres demandes (emails differents, meme IP) passent", all(results))

    over_quota = guard.check_and_register("un-de-plus@test.com", "5.5.5.5")
    check("la demande suivante depuis la meme IP est rate-limitee", not over_quota.should_send and over_quota.reason == "rate_limited_ip")


print("\n" + "=" * 80)
print("TEST 4/4 : ne revele jamais l'existence de l'email - meme forme de decision partout")
print("=" * 80)

guard._reset_for_tests()

decision = guard.check_and_register("inconnu@test.com", "8.8.8.8")
check(
    "la decision expose uniquement should_send/reason, aucune donnee client",
    set(vars(decision).keys()) == {"should_send", "reason"},
)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
