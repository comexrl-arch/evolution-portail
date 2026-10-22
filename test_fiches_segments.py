# Tests du rendu des fiches (audit du 22/10/2026), entierement mockes :
# questions sans zone "Ecris ici..." devenues champs, options "A | B | C"
# devenues un choix (et non une seule case), fiches de suivi hebdomadaire
# avec les champs places sous chaque question.
#
# Lancer : python test_fiches_segments.py

import sys
from unittest.mock import patch

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


def rt(*parts):
    return [
        {"plain_text": texte, "annotations": {"bold": gras}}
        for texte, gras in parts
    ]


def puce(bid, *parts, enfants=False):
    return {"id": bid, "type": "bulleted_list_item", "has_children": enfants,
            "bulleted_list_item": {"rich_text": rt(*parts)}}


def todo(bid, texte):
    return {"id": bid, "type": "to_do", "has_children": False, "to_do": {"rich_text": rt((texte, False))}}


def para(bid, texte):
    return {"id": bid, "type": "paragraph", "has_children": False, "paragraph": {"rich_text": rt((texte, False))}}


PLAN = [
    para("p1", "Fixons tes objectifs d'action pour les 7 prochains jours."),
    puce("q1", ("Score d'Offre :", True), ("  / 3", False)),
    puce("q1b", ("Combien de prospects vas-tu contacter ?", True)),
    puce("q2", ("Le canal de contact principal sera :", True), enfants=True),
    puce("q3", ("Le segment ciblé en priorité :", True), (" ", False)),
    puce("q4", ("Créneau bloqué dans mon agenda :", True), enfants=True),
    puce("x1", ("Introduction :", True), (" rappeler le contexte.", False)),
]

ENFANTS = {
    "q2": [todo("t2", "Téléphone | WhatsApp | LinkedIn | Email | Physique (terrain)")],
    "q4": [puce("e4", ("Écris ici...", False))],
}


def enfants_de(bid):
    return PLAN if bid == "page" else ENFANTS.get(bid, [])


print("Segments d'une fiche")

with patch.object(ns, "_list_children", side_effect=enfants_de):
    segments = ns._page_segments("page")

champs = {s["champ"]["cle"]: s["champ"] for s in segments if s["type"] == "champ"}
check("'**Score :**  / 3' (fiche 8, rempli par le coach) reste du texte", "q1" not in champs)
check("options A | B -> choix a 5 options", champs.get("q2", {}).get("type") == "choix" and len(champs["q2"]["options"]) == 5)
check("question en gras finissant par ':' -> champ", champs.get("q3", {}).get("type") == "texte")
check("question avec 'Ecris ici' -> champ", champs.get("q4", {}).get("type") == "texte")
check("'**Label :** phrase.' reste du texte", "x1" not in champs)

print("Case a options dans le contenu a cocher")
ligne = ns._block_lines(todo("t9", "Oui | Non"), checks=True)
check("pas de case pour 'Oui | Non'", ligne == ["Oui | Non"])
check("vraie case gardee", ns._block_lines(todo("t8", "J'ai fini"), checks=True)[0].startswith(ns._CHECK_LINE_PREFIX))

print("Fiche de suivi hebdomadaire")
SCHEMA = {
    "mode": "recurrent",
    "champs": [
        {"cle": "semaine_du", "libelle": "Semaine du", "type": "date", "ordre": 1},
        {"cle": "nb", "libelle": "Nb", "type": "nombre", "ordre": 2},
        {"cle": "canal", "libelle": "Canal", "type": "choix", "options": ["A"], "ordre": 3},
        {"cle": "segment", "libelle": "Segment", "type": "texte", "ordre": 4},
        {"cle": "creneau", "libelle": "Créneau", "type": "texte", "ordre": 5},
    ],
}

with patch.object(ns, "_segments_master_cache", return_value=segments):
    suivi = ns._segments_recurrents("m", SCHEMA)

cles = [s["champ"]["cle"] for s in suivi or [] if s["type"] == "champ"]
check("champs places dans l'ordre", cles == ["nb", "canal", "segment", "creneau"])
check("libelle de la fiche affiche", suivi and suivi[2]["champ"]["libelle_affiche"].startswith("Combien"))

with patch.object(ns, "_list_children", side_effect=enfants_de):
    coach = ns._page_segments("page", questions_libres=False)
check("fiche coach : aucune question libre", not any(s["type"] == "champ" and s["champ"]["cle"] in ("q1b", "q3") for s in coach))

with patch.object(ns, "_segments_master_cache", return_value=segments[:2]):
    check("modele different -> affichage classique", ns._segments_recurrents("m", SCHEMA) is None)

print("Question reformulee dans Notion")
CH = [{"cle": "a", "libelle": "Ton activité / Ton métier :"}, {"cle": "b", "libelle": "Qui sont tes clients actuels ?"}]
cles = ns._donnees_vers_cles({"Votre activité / Votre métier :": "Plombier", "Qui sont tes clients actuels ?": "TPE", "__checklist__": {}}, CH)
check("ancienne reponse 'vous' retrouvee", cles.get("a") == "Plombier" and cles.get("b") == "TPE")
check("etat des cases intact", "__checklist__" in cles)

print(f"\n{passed} PASS, {failed} FAIL")
sys.exit(1 if failed else 0)
