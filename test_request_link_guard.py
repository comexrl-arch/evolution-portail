# Tests de backend/services/request_link_guard.py (P1-E) : cooldown, limite par
# email, plafond global, purge, normalisation, absence d'email brut en memoire,
# concurrence. Horloge simulee (time.monotonic), aucun reseau. Le test de
# concurrence utilise une courte pause pour rendre la course deterministe sous
# le GIL. Meme style que test_onboarding.py (script simple, pas de framework de
# test, aucune dependance supplementaire).
#
# Lancer : python test_request_link_guard.py

import ast
import re
import sys
import threading
import time
from unittest.mock import patch

from backend.services import request_link_guard as guard

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


class Horloge:
    # Remplace time.monotonic : le test avance le temps a la main.
    def __init__(self, depart=1000.0):
        self.t = depart

    def __call__(self):
        return self.t

    def avancer(self, secondes):
        self.t += secondes


def horloge_simulee(depart=1000.0):
    h = Horloge(depart)
    return h, patch.object(guard.time, "monotonic", side_effect=h)


def demander(email="client@exemple.test"):
    return guard.verifier_et_enregistrer(email)


print("=" * 80)
print("TEST 1/9 : constantes validees (cooldown 60 s, 5 / 15 min par email, 100 / 15 min global, 1 000 entrees)")
print("=" * 80)

check("cooldown de 60 secondes", guard.COOLDOWN_SECONDS == 60)
check("5 demandes par email", guard.EMAIL_MAX_REQUESTS == 5)
check("fenetre email de 15 minutes", guard.EMAIL_WINDOW_SECONDS == 15 * 60)
check("plafond global de 100 demandes", guard.GLOBAL_MAX_REQUESTS == 100)
check("fenetre globale de 15 minutes", guard.GLOBAL_WINDOW_SECONDS == 15 * 60)
check("memoire bornee a 1 000 entrees", guard.MAX_EMAIL_ENTRIES == 1000)


print("\n" + "=" * 80)
print("TEST 2/9 : cooldown par email (60 s)")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    premiere = demander()
    check("1ere demande acceptee (ok)", premiere.autorise and premiere.raison == "ok")

    h.avancer(1)
    check("renvoi 1 s plus tard : refuse (cooldown)", demander() == guard.Decision(False, "cooldown"))

    h.avancer(58.9)  # 59,9 s apres la 1ere demande
    check("a 59,9 s : toujours refuse (cooldown)", demander() == guard.Decision(False, "cooldown"))

    h.avancer(0.1)  # 60,0 s exactement
    check("a 60,0 s : accepte", demander().autorise)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    demander()
    h.avancer(30)
    refuse = demander()
    h.avancer(30)  # 60 s apres la 1ere demande acceptee
    check("une demande refusee ne prolonge pas le cooldown", not refuse.autorise and demander().autorise)


print("\n" + "=" * 80)
print("TEST 3/9 : limite par email (5 demandes / 15 minutes)")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    resultats = []

    for _ in range(guard.EMAIL_MAX_REQUESTS):
        resultats.append(demander().autorise)
        h.avancer(guard.COOLDOWN_SECONDS)

    check("les 5 premieres demandes (hors cooldown) passent", all(resultats))
    sixieme = demander()
    check("la 6e demande dans la fenetre est refusee (limite_email)", sixieme == guard.Decision(False, "limite_email"))
    check("la 6e demande refusee n'est pas enregistree", len(guard._par_email[guard._cle("client@exemple.test")]) == 5)

    h.avancer(guard.EMAIL_WINDOW_SECONDS)
    check("apres la fenetre de 15 minutes, une nouvelle demande est acceptee", demander().autorise)


print("\n" + "=" * 80)
print("TEST 4/9 : plafond global (100 demandes / 15 minutes, tous emails confondus)")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    acceptes = [demander(f"client{i}@exemple.test").autorise for i in range(guard.GLOBAL_MAX_REQUESTS)]
    check("les 100 premieres demandes (emails differents) passent", all(acceptes))
    cent_unieme = demander("un-de-plus@exemple.test")
    check("la 101e demande est refusee (limite_globale)", cent_unieme == guard.Decision(False, "limite_globale"))
    check("un email deja connu est aussi refuse par le plafond global", demander("client0@exemple.test").raison == "limite_globale")

    h.avancer(guard.GLOBAL_WINDOW_SECONDS)
    check("apres la fenetre, les demandes repassent", demander("un-de-plus@exemple.test").autorise)


print("\n" + "=" * 80)
print("TEST 5/9 : purge des entrees expirees et memoire bornee")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    for i in range(10):
        demander(f"purge{i}@exemple.test")

    check("10 entrees en memoire apres 10 demandes", len(guard._par_email) == 10 and len(guard._global) == 10)
    h.avancer(guard.EMAIL_WINDOW_SECONDS + 1)
    demander("nouveau@exemple.test")
    check("apres la fenetre, les entrees expirees sont purgees (1 seule entree)", len(guard._par_email) == 1)
    check("la file globale est purgee aussi", len(guard._global) == 1)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with patch.object(guard, "MAX_EMAIL_ENTRIES", 3), patch.object(guard, "GLOBAL_MAX_REQUESTS", 10_000), p:
    for i in range(3):
        check(f"entree {i + 1}/3 acceptee", demander(f"borne{i}@exemple.test").autorise)

    refuse = demander("borne-de-trop@exemple.test")
    check("au-dela du plafond d'entrees : refus (fail-closed)", refuse == guard.Decision(False, "limite_globale"))
    check("la memoire ne depasse jamais le plafond", len(guard._par_email) <= 3)

    h.avancer(guard.COOLDOWN_SECONDS)
    check("un email deja present reste utilisable (hors cooldown)", demander("borne0@exemple.test").autorise)

    h.avancer(guard.EMAIL_WINDOW_SECONDS)
    check("apres purge, un nouvel email est accepte", demander("borne-de-trop@exemple.test").autorise)


print("\n" + "=" * 80)
print("TEST 6/9 : normalisation de l'email")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()

with p:
    check("'Client@Exemple.test' accepte", demander("Client@Exemple.test").autorise)
    check("' client@exemple.test ' (espaces, minuscules) = meme email : cooldown",
          demander("  client@exemple.test  ") == guard.Decision(False, "cooldown"))
    check("'CLIENT@EXEMPLE.TEST' = meme email : cooldown", demander("CLIENT@EXEMPLE.TEST").raison == "cooldown")
    check("un email different est independant", demander("autre@exemple.test").autorise)
    check("un email vide ou None ne plante pas", demander("").autorise and demander(None).raison == "cooldown")


print("\n" + "=" * 80)
print("TEST 7/9 : aucun email brut en memoire")
print("=" * 80)

guard._reinitialiser_pour_tests()
h, p = horloge_simulee()
BRUT = "marie.martin@exemple.test"

with p:
    demander(BRUT)
    demander("  " + BRUT.upper() + "  ")
    contenu = repr(guard._par_email) + repr(guard._global)
    check("l'email brut n'apparait pas dans la memoire de la garde", BRUT not in contenu and "marie" not in contenu.lower())
    check("les cles sont des empreintes SHA-256 de 64 caracteres hexadecimaux",
          all(re.fullmatch(r"[0-9a-f]{64}", cle) for cle in guard._par_email))
    check("une cle de taille arbitraire est ramenee a 64 caracteres", len(guard._cle("x" * 100_000)) == 64)
    check("la decision n'expose que autorise et raison", guard.Decision._fields == ("autorise", "raison"))


print("\n" + "=" * 80)
print("TEST 8/9 : concurrence (threads simultanes, horloge reelle)")
print("=" * 80)

# Intervalle de bascule minimal et pause entre la lecture et l'ecriture de l'etat
# (get() dort apres avoir lu) : si le verrou saute, la course est reproductible.
intervalle_initial = sys.getswitchinterval()
sys.setswitchinterval(1e-6)


class DictLent(dict):
    def get(self, cle, defaut=None):
        valeur = super().get(cle, defaut)
        time.sleep(0.0005)
        return valeur


dict_reel = guard._par_email
guard._par_email = DictLent()

guard._reinitialiser_pour_tests()
resultats = []
barriere = threading.Barrier(50)


def meme_email():
    barriere.wait()
    resultats.append(demander("course@exemple.test").autorise)


threads = [threading.Thread(target=meme_email) for _ in range(50)]
[t.start() for t in threads]
[t.join() for t in threads]
check("50 demandes simultanees pour un meme email : exactement 1 acceptee", resultats.count(True) == 1)
guard._par_email = dict_reel
sys.setswitchinterval(intervalle_initial)

guard._reinitialiser_pour_tests()
resultats = []
barriere = threading.Barrier(250)


def emails_distincts(i):
    barriere.wait()
    resultats.append(demander(f"course{i}@exemple.test").autorise)


threads = [threading.Thread(target=emails_distincts, args=(i,)) for i in range(250)]
[t.start() for t in threads]
[t.join() for t in threads]
check("250 emails distincts simultanes : exactement 100 acceptes (plafond global)",
      resultats.count(True) == guard.GLOBAL_MAX_REQUESTS)
check("la memoire reste coherente (100 entrees)", len(guard._par_email) == 100 and len(guard._global) == 100)


print("\n" + "=" * 80)
print("TEST 9/9 : la garde est independante de l'existence du compte et du reseau")
print("=" * 80)

arbre = ast.parse(open("backend/services/request_link_guard.py", encoding="utf-8").read())
imports = set()

for n in ast.walk(arbre):
    if isinstance(n, ast.Import):
        imports |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.module:
        imports.add(n.module.split(".")[0])

check("le module n'importe que la bibliotheque standard (aucun Notion, requests, reseau)",
      imports <= {"hashlib", "threading", "time", "collections", "typing"})
check("la fonction ne prend que l'email (aucune donnee client)", guard.verifier_et_enregistrer.__code__.co_varnames[:1] == ("email",))

guard._reinitialiser_pour_tests()
check("la reinitialisation vide l'etat", not guard._par_email and not guard._global)


print("\n" + "=" * 80)
print(f"RESULTAT FINAL : {passed}/{passed + failed} assertions reussies")
print("=" * 80)

sys.exit(0 if failed == 0 else 1)
