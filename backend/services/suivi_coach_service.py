# Suivi premium cote coach (decision de Rony du 29/10/2026, « Idris prepare,
# Rony signe ») :
# - preparation() : avant chaque point, ce que l'eleve a fait depuis le dernier
#   point (fiches, bilans, engagements, questions posees a Idris et a Rony,
#   carnet), plus une synthese et 3 questions a lui poser redigees par Idris.
# - alertes() : les eleves qui ont besoin de Rony (decrochage, chiffres en
#   baisse, engagements pas tenus, bilan oublie, fiches en retard, question
#   sans reponse), chacun avec un message WhatsApp pret a envoyer.
#   Coaching et Atelier : l'Autonome n'a pas de suivi individuel.

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from backend.services import comptes_rendus_service, ia_service, prospects_service, questions_rony_service
from backend.services import notion_service as ns

logger = logging.getLogger(__name__)

_POOL = ThreadPoolExecutor(max_workers=4)
JOURS_INACTIF = 7
_JOURS_SANS_BILAN = 9
_JOURS_ENGAGEMENTS = 5
_HEURES_QUESTION = 24
_TTL_ALERTES = 300
_NOM_QUESTION_IDRIS = "Question à Idris"


def _parse(iso) -> datetime | None:
    try:
        quand = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return quand if quand.tzinfo else quand.replace(tzinfo=timezone.utc)


def _jours(iso, maintenant: datetime) -> int | None:
    quand = _parse(iso)
    return None if quand is None else max((maintenant - quand).days, 0)


def _jour_fr(iso) -> str:
    return "/".join(reversed(str(iso or "")[:10].split("-")))


def _prenom(dashboard: dict) -> str:
    return (dashboard.get("nom") or "").split(" ")[0] or "toi"


def _lien_whatsapp(telephone, message: str) -> str:
    # Numero international seulement (+590..., 00590...) : sinon WhatsApp
    # demande de choisir le contact, plutot que de deviner un indicatif.
    chiffres = re.sub(r"\D", "", str(telephone or ""))
    texte = quote(message)

    if str(telephone or "").strip().startswith("+") and len(chiffres) >= 8:
        return f"https://wa.me/{chiffres}?text={texte}"

    if chiffres.startswith("00") and len(chiffres) >= 10:
        return f"https://wa.me/{chiffres[2:]}?text={texte}"

    return f"https://wa.me/?text={texte}"


def _entrees(client_page_id: str) -> list[dict]:
    return ns._query_data_source(
        ns.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Client", "relation": {"contains": client_page_id}},
        sorts=[{"timestamp": "created_time", "direction": "descending"}],
    )


def _saisies_eleve(entrees: list[dict]) -> list[dict]:
    # Ce que l'eleve a ecrit lui-meme : ni les comptes rendus de Rony, ni les
    # questions a Idris (conversation, pas une saisie de travail).
    return [
        e for e in entrees
        if not comptes_rendus_service.est_compte_rendu(e)
        and _NOM_QUESTION_IDRIS not in str(ns._prop_value(ns._prop(e.get("properties", {}), "Nom")) or "")
    ]


def _historique(dashboard: dict) -> list[dict]:
    fiche = next((f for f in dashboard.get("fiches") or [] if f.get("master_id") == ns._BILAN_HEBDO_MASTER_ID), None)

    if not fiche or "Bloqué" in str(fiche.get("acces") or ""):
        return []

    try:
        return ns._historique_bilans(fiche["id"])
    except Exception as error:
        logger.warning("Bilans illisibles (%s)", error)
        return []


# --- Alertes ------------------------------------------------------------------------

def _detecter(dashboard: dict, entrees: list[dict], historique: list[dict], compte_rendu: dict | None,
              questions: list[dict], maintenant: datetime) -> list[dict]:
    prenom = _prenom(dashboard)
    alertes = []

    for q in questions_rony_service.en_attente(questions):
        heures = (maintenant - (_parse(q["posee_le"]) or maintenant)).total_seconds() / 3600

        if heures >= _HEURES_QUESTION:
            alertes.append({
                "type": "question",
                "titre": f"Question sans réponse depuis {int(heures // 24) or 1} j" if heures >= 48 else "Question sans réponse depuis hier",
                "detail": q["question"][:160],
                "message": None,
            })
            break

    saisies = _saisies_eleve(entrees)
    coches = [comptes_rendus_service.derniere_coche(e) for e in entrees if comptes_rendus_service.est_compte_rendu(e)]
    derniere = max([e.get("created_time") or "" for e in saisies] + coches, default="") or None
    sans_saisie = _jours(derniere, maintenant)
    jour = ns._jour_parcours(dashboard.get("date_demarrage"))

    if (sans_saisie is None and (jour or 0) >= JOURS_INACTIF) or (sans_saisie is not None and sans_saisie >= JOURS_INACTIF):
        duree = f"{sans_saisie} jours" if sans_saisie is not None else "le démarrage"
        alertes.append({
            "type": "inactif",
            "titre": f"Rien saisi depuis {duree}",
            "detail": "Ni fiche, ni bilan, ni prospect, ni engagement coché.",
            "message": (
                f"Salut {prenom}, je n'ai rien vu passer dans ton espace depuis {duree}. Tout va bien ? "
                "Dis-moi ce qui te bloque, on regarde ça ensemble en 10 minutes."
            ),
        })

    if len(historique) >= 3:
        derniere_semaine = historique[-1]
        precedentes = historique[-4:-1]
        moyenne = sum(s["contacts"] for s in precedentes) / len(precedentes)

        if moyenne >= 4 and derniere_semaine["contacts"] < moyenne / 2:
            alertes.append({
                "type": "baisse",
                "titre": "Contacts en forte baisse",
                "detail": f"{derniere_semaine['contacts']:.0f} contacts la semaine du {_jour_fr(derniere_semaine['semaine_du'])}, contre {moyenne:.0f} en moyenne avant.",
                "message": (
                    f"Salut {prenom}, j'ai vu ton bilan : {derniere_semaine['contacts']:.0f} contacts cette semaine, "
                    f"contre {moyenne:.0f} d'habitude. Ça arrive à tout le monde. Qu'est-ce qui t'a freiné ? "
                    "On ajuste ton plan ensemble."
                ),
            })

    if compte_rendu and compte_rendu["engagements"]:
        age = (maintenant.date() - date.fromisoformat(str(compte_rendu["date_point"])[:10])).days if compte_rendu.get("date_point") else 0
        restants = [e for e in compte_rendu["engagements"] if not e["fait"]]

        if age >= _JOURS_ENGAGEMENTS and len(restants) * 2 > len(compte_rendu["engagements"]):
            alertes.append({
                "type": "engagements",
                "titre": f"{len(restants)} engagement{'s' if len(restants) > 1 else ''} sur {len(compte_rendu['engagements'])} pas encore tenu{'s' if len(restants) > 1 else ''}",
                "detail": f"Point du {_jour_fr(compte_rendu['date_point'])} : {restants[0]['texte']}",
                "message": (
                    f"Salut {prenom}, où en es-tu de ce qu'on s'est dit au dernier point ? "
                    f"Il te reste notamment : {restants[0]['texte']}. Sur quoi je peux t'aider pour le boucler ?"
                ),
            })

    regularite = dashboard.get("regularite")

    if regularite is not None:
        sans_bilan = _jours(regularite.get("derniere"), maintenant) if regularite.get("derniere") else None

        if (sans_bilan is None and (jour or 0) >= 14) or (sans_bilan is not None and sans_bilan >= _JOURS_SANS_BILAN):
            alertes.append({
                "type": "bilan",
                "titre": "Bilan de la semaine pas rempli",
                "detail": f"Dernier bilan : semaine du {_jour_fr(regularite['derniere'])}." if regularite.get("derniere") else "Aucun bilan encore.",
                "message": (
                    f"Salut {prenom}, ton bilan de la semaine n'est pas encore rempli. 5 minutes suffisent, "
                    "et ça me permet de préparer notre prochain point. Tu me le fais aujourd'hui ?"
                ),
            })

    en_retard = (dashboard.get("rythme") or {}).get("en_retard") or 0

    if en_retard >= 2:
        prochaine = next(
            (f["nom"].split(" - ", 1)[-1] for f in dashboard.get("fiches") or []
             if f.get("etat") != "Terminé" and "Bloqué" not in str(f.get("acces") or "")),
            None,
        )
        alertes.append({
            "type": "retard",
            "titre": f"{en_retard} fiches en retard",
            "detail": f"Prochaine : {prochaine}." if prochaine else "",
            "message": (
                f"Salut {prenom}, tu as pris un peu de retard sur tes fiches. On fait simple : "
                + (f"commence par « {prochaine} » aujourd'hui, " if prochaine else "choisis une fiche aujourd'hui, ")
                + "20 minutes, et envoie-moi un message quand c'est fait."
            ),
        })

    return alertes


def alertes_eleve(client_page_id: str, dashboard: dict | None = None, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    dashboard = dashboard or ns.get_client_dashboard(client_page_id)
    entrees = _entrees(client_page_id)
    alertes = _detecter(
        dashboard,
        entrees,
        _historique(dashboard),
        comptes_rendus_service.dernier(client_page_id),
        questions_rony_service.depuis_entrees(entrees),
        maintenant,
    )
    telephone = (dashboard.get("identite") or {}).get("telephone")

    for alerte in alertes:
        if alerte["message"]:
            alerte["whatsapp"] = _lien_whatsapp(telephone, alerte["message"])

    return {"client_page_id": client_page_id, "nom": dashboard.get("nom"), "parcours": ns._nom_parcours(dashboard.get("parcours")), "alertes": alertes}


def alertes(frais: bool = False, maintenant: datetime | None = None) -> list[dict]:
    """Eleves en cours (Coaching et Atelier) qui ont au moins une alerte, les
    plus urgents en premier. Memorise 5 min (n8n du matin + onglet Eleves)."""
    cle = "alertes_coach"
    en_cache = None if frais else ns._cache_get(cle)

    if en_cache is not None:
        return en_cache

    rows = [
        row for row in ns._query_data_source(ns.CLIENTS_DATA_SOURCE_ID)
        if ns._prop_value(ns._prop(row.get("properties", {}), "État")) == "En cours"
        and not ns._est_parcours_autonome(ns._prop_value(ns._prop(row.get("properties", {}), "Parcours")))
    ]

    def _sans_echec(row):
        try:
            return alertes_eleve(row["id"], maintenant=maintenant)
        except Exception as error:
            logger.warning("Alertes de %s illisibles (%s)", row.get("id"), ns._resume_erreur(error))
            return None

    ordre = {"question": 0, "inactif": 1, "baisse": 2, "engagements": 3, "bilan": 4, "retard": 5}
    resultat = [r for r in _POOL.map(_sans_echec, rows) if r and r["alertes"]]
    resultat.sort(key=lambda r: (min(ordre.get(a["type"], 9) for a in r["alertes"]), -len(r["alertes"])))
    return ns._cache_set(cle, resultat, _TTL_ALERTES)


def resume_du_matin(liste: list[dict]) -> tuple[str, str] | None:
    if not liste:
        return None

    noms = ", ".join(f"{(r['nom'] or '').split(' ')[0]} ({r['alertes'][0]['titre'].lower()})" for r in liste[:3])
    plus = f" et {len(liste) - 3} autre{'s' if len(liste) > 4 else ''}" if len(liste) > 3 else ""
    titre = f"{len(liste)} élève{'s' if len(liste) > 1 else ''} à surveiller"
    return titre, f"{noms}{plus}. Un message est prêt pour chacun."


# --- Preparation d'un point --------------------------------------------------------------

def preparation(client_page_id: str, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(timezone.utc)
    dashboard = ns.get_client_dashboard(client_page_id)
    entrees = _entrees(client_page_id)
    compte_rendu = comptes_rendus_service.dernier(client_page_id)
    depuis = str(compte_rendu["date_point"])[:10] if compte_rendu and compte_rendu.get("date_point") else (maintenant - timedelta(days=14)).date().isoformat()
    noms_fiches = {f["id"].replace("-", ""): f["nom"].split(" - ", 1)[-1] for f in dashboard.get("fiches") or []}

    fiches_travaillees = {}
    questions_idris = []

    for entree in entrees:
        cree = str(entree.get("created_time") or "")[:10]

        if cree < depuis:
            continue

        props = entree.get("properties", {})
        nom = str(ns._prop_value(ns._prop(props, "Nom")) or "")

        if _NOM_QUESTION_IDRIS in nom:
            try:
                question = json.loads(ns._prop_value(ns._prop(props, "Données (JSON)")) or "{}").get("question")
            except (json.JSONDecodeError, AttributeError):
                question = None
            if question:
                questions_idris.append({"date": cree, "question": str(question)[:300]})
            continue

        fiche_id = ns._relation_id(props, "Fiche Client")

        if fiche_id and fiche_id.replace("-", "") in noms_fiches:
            fiches_travaillees.setdefault(noms_fiches[fiche_id.replace("-", "")], cree)

    historique = _historique(dashboard)
    questions = questions_rony_service.depuis_entrees(entrees)
    carnet = prospects_service.vue_client(prospects_service.lire(client_page_id, dashboard))
    perso = dashboard.get("personnalisation") or {}
    detecte = _detecter(dashboard, entrees, historique, compte_rendu, questions, maintenant)

    return {
        "client_page_id": client_page_id,
        "nom": dashboard.get("nom"),
        "depuis": depuis,
        "depuis_dernier_point": bool(compte_rendu),
        "jour": ns._jour_parcours(dashboard.get("date_demarrage")),
        "objectif_90j": dashboard.get("objectif_90j"),
        "zones_prioritaires": [z.get("zone") for z in perso.get("zones_prioritaires") or []],
        "fiches_travaillees": [{"fiche": nom, "date": quand} for nom, quand in sorted(fiches_travaillees.items(), key=lambda x: x[1])],
        "fiches_en_retard": (dashboard.get("rythme") or {}).get("en_retard") or 0,
        "bilans": [b for b in historique if b["semaine_du"] >= depuis][-4:] or historique[-2:],
        "engagements": compte_rendu["engagements"] if compte_rendu else [],
        "questions_idris": questions_idris[:8],
        "questions_rony": [q for q in questions if (q["posee_le"] or "")[:10] >= depuis][:5],
        "carnet": {"par_statut": carnet.get("par_statut") or {}, "a_relancer": len(carnet.get("a_relancer") or [])},
        "alertes": [{"type": a["type"], "titre": a["titre"], "detail": a["detail"]} for a in detecte],
    }


_PREPARATION_SYSTEME = """Tu aides Rony, coach commercial de RL-eVolution (indépendants et TPE des Antilles-Guyane), à préparer son prochain point individuel avec un élève. Tu reçois ce que l'élève a fait depuis le dernier point.

RÈGLES
- Appuie-toi UNIQUEMENT sur les données fournies. N'invente aucun chiffre ni fait. S'il manque des données, dis-le.
- Tu t'adresses à Rony (tu le tutoies), en français simple, sans jargon.
- "synthese" : 2 à 3 phrases sur où en est l'élève.
- "questions" : exactement 3 questions ouvertes que Rony peut poser à l'élève, reliées aux données (ses blocages, ses engagements, ses questions à Idris).
- "vigilance" : 1 phrase sur le point à ne pas laisser passer, ou "" s'il n'y en a pas.

Réponds uniquement avec un objet JSON : {"synthese": "...", "questions": ["...", "...", "..."], "vigilance": "..."}"""


def _texte_preparation(prep: dict) -> str:
    lignes = [
        f"Élève : {prep['nom']} (J{prep['jour']})" if prep.get("jour") is not None else f"Élève : {prep['nom']}",
        f"Objectif 90 jours : {prep['objectif_90j']}" if prep.get("objectif_90j") else "Objectif 90 jours : non écrit",
        f"Zones prioritaires du diagnostic : {', '.join(prep['zones_prioritaires']) or 'aucune'}",
        f"Période : depuis le {prep['depuis']}" + (" (dernier point)" if prep["depuis_dernier_point"] else " (pas encore de compte rendu)"),
        "Fiches travaillées : " + ("; ".join(f"{f['fiche']} ({f['date']})" for f in prep["fiches_travaillees"]) or "aucune"),
        f"Fiches en retard : {prep['fiches_en_retard']}",
    ]
    lignes.extend(ns._lignes_historique_bilans(prep["bilans"]) if prep["bilans"] else ["Aucun bilan hebdomadaire."])

    if prep["engagements"]:
        lignes.append("Engagements du dernier point : " + "; ".join(f"{e['texte']} ({'tenu' if e['fait'] else 'pas encore'})" for e in prep["engagements"]))

    if prep["questions_idris"]:
        lignes.append("Questions posées à Idris : " + " | ".join(q["question"] for q in prep["questions_idris"]))

    if prep["questions_rony"]:
        lignes.append("Questions posées à Rony : " + " | ".join(q["question"] for q in prep["questions_rony"]))

    statuts = prep["carnet"]["par_statut"]
    lignes.append("Carnet de prospects : " + (", ".join(f"{s} {n}" for s, n in statuts.items()) or "vide") + f", {prep['carnet']['a_relancer']} à relancer")

    if prep["alertes"]:
        lignes.append("Signaux : " + "; ".join(a["titre"] for a in prep["alertes"]))

    return "\n".join(lignes)


def preparation_idris(prep: dict) -> dict:
    texte = ia_service.generer(_PREPARATION_SYSTEME, [{"role": "user", "texte": _texte_preparation(prep)}], temperature=0.4, max_tokens=700)
    debut, fin = texte.find("{"), texte.rfind("}")

    try:
        donnees = json.loads(texte[debut:fin + 1]) if debut >= 0 and fin > debut else {}
    except json.JSONDecodeError:
        donnees = {}

    if not isinstance(donnees, dict) or not donnees.get("synthese"):
        raise RuntimeError("Préparation illisible")

    return {
        "synthese": ia_service.humaniser(str(donnees.get("synthese"))),
        "questions": [ia_service.humaniser(str(q)) for q in donnees.get("questions") or [] if str(q).strip()][:3],
        "vigilance": ia_service.humaniser(str(donnees.get("vigilance") or "")),
    }
