# Idris au quotidien (decision de Rony du 25/10/2026, lot 2) :
# - "Demande à Idris" : questions libres de strategie commerciale, cadrees sur
#   la methode eVolution 2.0 et les donnees du client. Coaching : illimite
#   (garde-fou par jour). Autonome et Atelier : quota mensuel. Chaque question
#   est gardee dans [DB] Entrees Portail ("Question à Idris"), ce qui fait le
#   compte du quota et permet a Rony de les relire dans Notion.
# - Messages prets a envoyer (WhatsApp, LinkedIn, relances), pour tous.
# - Preparation de rendez-vous, reservee au Coaching 90 jours.
# Appels Gemini directs, comme l'entrainement et les brouillons.

import json
import threading
from datetime import datetime, timezone

from backend.services import ia_service, notion_service
from backend.services.brouillon_service import _lire_json
from backend.services.entrainement_service import _contexte_client

_N = notion_service._NUMERO_TO_MASTER_ID

# Seuils de travail, a ajuster avec l'experience (hypotheses du 25/10/2026).
QUESTIONS_PAR_MOIS = 20
_MAX_QUESTIONS_JOUR_COACHING = 30
_MAX_REDACTIONS_JOUR = 20
_MAX_HISTORIQUE = 8
_MAX_CARACTERES = 800
_NOM_QUESTION = "Question à Idris"

# Offre, cible, positionnement, script : la matiere de ses reponses.
_FICHES_SOURCES = [_N["9"], _N["10"], _N["11"], _N["15"]]

TYPES_MESSAGES = {
    "whatsapp_premier_contact": {
        "titre": "Premier contact WhatsApp",
        "consigne": "Un premier message WhatsApp à un prospect qu'il ne connaît pas ou peu : 3 à 5 lignes, chaleureux, une raison claire de le contacter, une question simple pour ouvrir l'échange. Pas de prix, pas de lien.",
    },
    "linkedin_premier_contact": {
        "titre": "Premier contact LinkedIn",
        "consigne": "Une invitation ou un premier message LinkedIn : 300 caractères au plus, personnalisé, sans pitch de vente, qui donne envie de répondre.",
    },
    "relance_devis": {
        "titre": "Relance après un devis",
        "consigne": "Une relance courte d'un prospect qui a reçu une proposition ou un devis et n'a pas répondu : rappeler le résultat attendu, lever un frein possible, proposer un court échange.",
    },
    "relance_sans_reponse": {
        "titre": "Relance sans réponse",
        "consigne": "Une relance d'un prospect qui n'a pas répondu à un premier message : 2 à 3 lignes, légère, sans culpabiliser, avec une porte de sortie polie.",
    },
    "demande_recommandation": {
        "titre": "Demande de recommandation",
        "consigne": "Un message à un client satisfait pour lui demander s'il connaît une ou deux personnes à qui le service pourrait être utile : remercier, être précis sur le type de personne, rendre la demande facile.",
    },
}

_METHODE = """LA MÉTHODE eVolution 2.0 (programme de 90 jours de RL-eVolution, coach : Rony)
- Diagnostic en 5 zones notées sur 3 : Offre, Visibilité, Prospection, Conversion, Suivi commercial (total sur 15).
- Clarifier (J4 à J18) : une offre claire, une cible prioritaire précise, une phrase de positionnement « J'aide [cible] à obtenir [résultat] sans [frustration] grâce à [méthode] », un pitch de 30 secondes.
- Prospecter (dès J31) : un tableau de prospects, un script d'approche, une routine chaque semaine (plan le lundi, bilan le vendredi : contacts, RDV, propositions, ventes).
- Convertir (dès J61) : une trame de rendez-vous découverte (écouter, questionner, reformuler, proposer), la gestion des objections, le prix et la proposition, le suivi des propositions jusqu'au closing.
- Stabiliser (J75 à J90) : recommandations et fidélisation, bilan J90.
- Esprit : des actions simples, régulières et mesurables, adaptées aux indépendants et TPE des Antilles-Guyane (bouche-à-oreille, réseau, WhatsApp, terrain)."""

_SYSTEME_QUESTION = f"""Tu es Idris, l'assistant IA et coach commercial du programme eVolution 2.0 (RL-eVolution), aux côtés de Rony. Tu réponds aux questions de stratégie commerciale d'un client indépendant ou TPE des Antilles-Guyane.

{_METHODE}

CE QUE TU FAIS
- Tu réponds sur l'offre, la cible, le prix, la prospection, le choix des canaux, les rendez-vous, les objections, les relances, le suivi des chiffres.
- Tu t'appuies sur la méthode ci-dessus et sur SES données (fiches, diagnostic, chiffres). Quand une de ses fiches traite le sujet, tu l'y renvoies par son nom.
- Format : une réponse directe en une ou deux phrases, puis 2 ou 3 étapes concrètes, puis UNE action pour cette semaine, seule dans le dernier paragraphe. 150 mots au plus. Paragraphes séparés par une ligne vide, pas de markdown, pas de titre, pas de signature.
- Français, tutoiement, chaleureux, pédagogue, sans jargon (pas de "funnel", "mindset", "scaler").

CE QUE TU NE FAIS PAS
- Juridique, fiscalité, comptabilité, statut, aides publiques au cas par cas : dis que ce n'est pas ton rôle et oriente vers un professionnel ou vers Rony.
- Grandes décisions (changer de métier, embaucher, investir, s'endetter) : donne les questions à se poser, puis dis que c'est à voir avec Rony.
- N'invente aucun chiffre, aucun fait, aucun résultat ; ne promets jamais de chiffre d'affaires. S'il te manque une information, pose UNE question.
- Hors du commercial et de son activité : réponds poliment que tu es là pour son développement commercial."""

_SYSTEME_MESSAGE = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-eVolution). Tu rédiges des messages commerciaux prêts à envoyer pour un indépendant ou une TPE des Antilles-Guyane, à partir de SES fiches (offre, cible, positionnement, script).
Reprends ses mots et sa cible. Vouvoiement par défaut, ton simple, humain et chaleureux, sans jargon ni formule creuse. N'invente aucun chiffre, aucun client, aucune référence. Laisse [Prénom] à la place du nom du destinataire.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour : {"variantes": ["...", "..."]} avec exactement 2 versions différentes (l'une plus directe, l'autre plus chaleureuse)."""

_SYSTEME_RDV = """Tu es Idris, l'assistant IA et coach commercial du programme eVolution 2.0 (RL-eVolution). Tu prépares un rendez-vous découverte pour un indépendant ou une TPE des Antilles-Guyane, d'après son offre et ce qu'il sait de son prospect.
Méthode : écouter d'abord, questionner pour comprendre la vraie situation, reformuler, puis proposer une prochaine étape précise. N'invente aucun fait sur le prospect ni aucun chiffre. Français, tutoiement pour t'adresser au client, phrases courtes.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, avec exactement ces clés :
{"objectif": "l'objectif du rendez-vous en une phrase",
 "questions": ["5 questions de découverte, ouvertes, adaptées à ce prospect"],
 "objections": [{"objection": "...", "reponse": "une réponse à dire mot pour mot"}, 3 objections probables au total],
 "prochaine_etape": "la prochaine étape à proposer en fin de rendez-vous"}"""

_compteurs: dict[str, tuple[str, int]] = {}
_verrou = threading.Lock()


def _quota_jour_ok(cle: str, maximum: int) -> bool:
    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with _verrou:
        jour_compte, nombre = _compteurs.get(cle, (jour, 0))

        if jour_compte != jour:
            nombre = 0

        if nombre >= maximum:
            return False

        _compteurs[cle] = (jour, nombre + 1)
        return True


def est_coaching(dashboard: dict) -> bool:
    parcours = dashboard.get("parcours")
    return not notion_service._est_parcours_autonome(parcours) and not notion_service._est_parcours_atelier(parcours)


def questions_du_mois(client_page_id: str, maintenant: datetime | None = None) -> int:
    debut_mois = (maintenant or datetime.now(timezone.utc)).strftime("%Y-%m-01")
    pages = notion_service._query_data_source(
        notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={
            "and": [
                {"property": "Client", "relation": {"contains": client_page_id}},
                {"property": "Nom", "title": {"contains": _NOM_QUESTION}},
                {"property": "Date", "date": {"on_or_after": debut_mois}},
            ]
        },
    )
    return len(pages)


def questions_restantes(client_page_id: str, dashboard: dict) -> int | None:
    """None = illimite (Coaching). Si le compte est illisible, on n'empeche
    pas le client de poser sa question."""
    if est_coaching(dashboard):
        return None

    try:
        return max(QUESTIONS_PAR_MOIS - questions_du_mois(client_page_id), 0)
    except Exception as error:
        notion_service.logger.warning("Quota Idris illisible (%s) : question autorisee.", error)
        return QUESTIONS_PAR_MOIS


def etat(client_page_id: str, dashboard: dict) -> dict:
    disponible = ia_service.enabled()
    return {
        "disponible": disponible,
        "coaching": est_coaching(dashboard),
        "questions_par_mois": None if est_coaching(dashboard) else QUESTIONS_PAR_MOIS,
        "questions_restantes": questions_restantes(client_page_id, dashboard) if disponible else 0,
        "rdv_disponible": disponible and est_coaching(dashboard),
        "types_messages": [{"id": cle, "titre": t["titre"]} for cle, t in TYPES_MESSAGES.items()],
    }


def _contexte(client_page_id: str, dashboard: dict, avec_chiffres: bool = True) -> str:
    """Tout ce qu'Idris sait du client : profil, formule, objectif, diagnostic,
    chiffres, et ses reponses aux fiches de clarification."""
    lignes = [_contexte_client(client_page_id)]
    prenom = (dashboard.get("nom") or "").split(" ")[0]

    if prenom:
        lignes.append(f"Prénom : {prenom}")

    lignes.append("Formule : " + ("Coaching 90 jours (avec Rony)" if est_coaching(dashboard) else "eVolution Autonome"))

    if dashboard.get("objectif_90j"):
        lignes.append(f"Objectif 90 jours : {dashboard['objectif_90j']}")

    jour = notion_service._jour_parcours(dashboard.get("date_demarrage"))

    if jour is not None:
        lignes.append(f"Jour du parcours : J{jour}")

    perso = dashboard.get("personnalisation") or {}

    if perso.get("scores"):
        lignes.append("Diagnostic actuel : " + ", ".join(f"{zone} {score}/3" for zone, score in perso["scores"].items()))
        lignes.append("Zones prioritaires : " + (", ".join(z["zone"] for z in perso.get("zones_prioritaires", [])) or "aucune"))

    fiches = dashboard.get("fiches") or []

    if avec_chiffres:
        bilan = next((f for f in fiches if f.get("master_id") == notion_service._BILAN_HEBDO_MASTER_ID), None)

        if bilan:
            try:
                historique = notion_service._historique_bilans(bilan["id"])
            except Exception:
                historique = []

            if historique:
                lignes.extend(notion_service._lignes_historique_bilans(historique))

        noms = [f["nom"].split(" - ", 1)[-1] for f in fiches if f.get("nom") and "Bloqué" not in str(f.get("acces") or "")]

        if noms:
            lignes.append("Ses fiches ouvertes : " + " ; ".join(noms))

    try:
        sources = notion_service.reponses_des_fiches(client_page_id, fiches, _FICHES_SOURCES)
    except Exception:
        sources = []

    for source in sources:
        lignes.append(f"Ses réponses dans « {source['nom'].split(' - ', 1)[-1]} » :")
        lignes.extend(f"- {libelle} {valeur[:400]}" for libelle, valeur in source["reponses"])

    return "\n".join(lignes)


def _enregistrer_question(client_page_id: str, client_nom: str, question: str, reponse: str) -> None:
    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contenu = json.dumps({"question": question, "reponse": reponse}, ensure_ascii=False)
    notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{client_nom} — {_NOM_QUESTION} — {jour}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Date": {"date": {"start": jour}},
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, min(len(contenu), 6000), 2000)]},
    })


def _alterner(echanges: list[dict]) -> list[dict]:
    # Gemini attend des tours user / model alternes : deux messages de suite
    # du meme role sont fusionnes.
    resultat = []

    for echange in echanges:
        if resultat and resultat[-1]["role"] == echange["role"]:
            resultat[-1] = {"role": echange["role"], "texte": resultat[-1]["texte"] + "\n\n" + echange["texte"]}
        else:
            resultat.append(dict(echange))

    return resultat


def repondre_question(client_page_id: str, dashboard: dict, messages: list[dict]) -> dict:
    """messages : [{"role": "client" | "idris", "texte"}], la derniere est la
    question. Leve ValueError (requete invalide), PermissionError (quota)."""
    if not messages or messages[-1].get("role") != "client":
        raise ValueError("Pas de question")

    if any(len(str(m.get("texte") or "")) > 2000 for m in messages):
        raise ValueError("Message trop long")

    question = str(messages[-1].get("texte") or "").strip()

    if not question or len(question) > _MAX_CARACTERES:
        raise ValueError("Question vide ou trop longue")

    restantes = questions_restantes(client_page_id, dashboard)

    if restantes is not None and restantes <= 0:
        raise PermissionError("Quota mensuel atteint")

    if not _quota_jour_ok(f"q:{client_page_id}", _MAX_QUESTIONS_JOUR_COACHING):
        raise PermissionError("Limite du jour atteinte")

    historique = messages[-(_MAX_HISTORIQUE + 1):-1]
    echanges = [{"role": "user", "texte": "Voici ce que tu sais de moi :\n" + _contexte(client_page_id, dashboard)}]
    echanges.append({"role": "model", "texte": "Merci, j'ai bien tout lu. Quelle est ta question ?"})
    echanges += [
        {"role": "model" if m.get("role") == "idris" else "user", "texte": str(m.get("texte") or "")[:2000]}
        for m in historique
    ]
    echanges.append({"role": "user", "texte": question})
    texte = ia_service.generer(_SYSTEME_QUESTION, _alterner(echanges), temperature=0.5, max_tokens=600)

    try:
        _enregistrer_question(client_page_id, dashboard.get("nom") or "Client", question, texte)
    except Exception as error:
        notion_service.logger.warning("Question à Idris non enregistree (%s)", error)

    return {"texte": texte, "questions_restantes": None if restantes is None else restantes - 1}


def rediger_message(client_page_id: str, dashboard: dict, type_id: str, precision: str = "") -> dict:
    type_message = TYPES_MESSAGES.get(type_id)

    if not type_message or len(precision or "") > 500:
        raise ValueError("Type de message inconnu ou précision trop longue")

    if not _quota_jour_ok(f"m:{client_page_id}", _MAX_REDACTIONS_JOUR):
        raise PermissionError("Limite du jour atteinte")

    demande = _contexte(client_page_id, dashboard, avec_chiffres=False) + f"\n\nMessage à rédiger : {type_message['consigne']}"

    if precision and precision.strip():
        demande += f"\nPrécision du client sur le destinataire ou la situation : {precision.strip()}"

    valeurs = _lire_json(ia_service.generer(_SYSTEME_MESSAGE, [{"role": "user", "texte": demande}], temperature=0.8, max_tokens=800))
    variantes = [v.strip() for v in valeurs.get("variantes") or [] if isinstance(v, str) and v.strip()][:2]

    if not variantes:
        raise RuntimeError("Message IA vide")

    return {"variantes": variantes}


def preparer_rdv(client_page_id: str, dashboard: dict, prospect: str, besoin: str = "", objectif: str = "") -> dict:
    if not est_coaching(dashboard):
        raise LookupError("Réservé au Coaching 90 jours")

    prospect = (prospect or "").strip()

    if not prospect or any(len(t or "") > 600 for t in (prospect, besoin, objectif)):
        raise ValueError("Prospect manquant ou texte trop long")

    if not _quota_jour_ok(f"r:{client_page_id}", _MAX_REDACTIONS_JOUR):
        raise PermissionError("Limite du jour atteinte")

    demande = _contexte(client_page_id, dashboard, avec_chiffres=False) + f"\n\nLe prospect : {prospect}"

    if (besoin or "").strip():
        demande += f"\nCe qu'il sait de son besoin : {besoin.strip()}"

    if (objectif or "").strip():
        demande += f"\nCe qu'il veut obtenir de ce rendez-vous : {objectif.strip()}"

    valeurs = _lire_json(ia_service.generer(_SYSTEME_RDV, [{"role": "user", "texte": demande}], temperature=0.6, max_tokens=1200))
    questions = [q.strip() for q in valeurs.get("questions") or [] if isinstance(q, str) and q.strip()][:6]
    objections = [
        {"objection": str(o.get("objection") or "").strip(), "reponse": str(o.get("reponse") or "").strip()}
        for o in valeurs.get("objections") or []
        if isinstance(o, dict) and o.get("objection") and o.get("reponse")
    ][:3]

    if not questions:
        raise RuntimeError("Préparation IA vide")

    return {
        "objectif": str(valeurs.get("objectif") or "").strip(),
        "questions": questions,
        "objections": objections,
        "prochaine_etape": str(valeurs.get("prochaine_etape") or "").strip(),
    }


# --- Bilan J90 redige par Idris (lot 3, 25/10/2026) ---
# Disponible a partir de J80, ou des que toutes les fiches sont terminees.
JOUR_BILAN_FINAL = 80
_BILAN_J90_MASTER_ID = "3f0faffd87588137927fda435c873a9f"

_SYSTEME_BILAN_J90 = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-eVolution), aux côtés de Rony. Le client arrive au terme de ses 90 jours. Tu lui écris son bilan de parcours.

RÈGLES
- Français, tutoiement, chaleureux, fier de son travail sans flatterie, concret.
- Appuie-toi UNIQUEMENT sur les données fournies (parcours, avant / après, chiffres, ses réponses au bilan J90). N'invente aucun chiffre ni résultat ; si une donnée manque, n'en parle pas.
- 180 à 250 mots, 4 paragraphes séparés par une ligne vide, pas de titre, pas de markdown, pas de signature.

STRUCTURE
1. Le chemin parcouru : ce qu'il a construit (fiches, modules, régularité).
2. Ses progrès en chiffres : avant / maintenant, tels que fournis.
3. Ce qui a marché pour lui et ce qui reste à travailler, avec ses mots.
4. Ses 3 priorités pour les 90 prochains jours, en une phrase chacune, puis un mot de fin."""


def bilan_final_disponible(dashboard: dict) -> bool:
    fiches = dashboard.get("fiches") or []
    jour = notion_service._jour_parcours(dashboard.get("date_demarrage"))
    return bool(fiches) and (all(f.get("etat") == "Terminé" for f in fiches) or (jour is not None and jour >= JOUR_BILAN_FINAL))


def _lignes_avant_apres(dashboard: dict) -> list[str]:
    fiches = dashboard.get("fiches") or []
    lignes = [f"Fiches validées : {sum(1 for f in fiches if f.get('etat') == 'Terminé')} sur {len(fiches)}"]
    perso = dashboard.get("personnalisation") or {}

    if perso.get("scores_diagnostic"):
        lignes.append(f"Diagnostic : {perso['total']}/15 au départ, {perso.get('total_actuel', perso['total'])}/15 aujourd'hui")

    for kpi in dashboard.get("kpi") or []:
        depart = kpi.get("valeur_j0")
        derniere = next(((p, kpi.get(c)) for c, p in (("valeur_j90", "J90"), ("valeur_j60", "J60"), ("valeur_j30", "J30")) if kpi.get(c) is not None), None)

        if depart is not None and derniere:
            nombre = notion_service._nombre
            lignes.append(f"{kpi.get('nom')} : {nombre(depart):g} à J0, {nombre(derniere[1]):g} à {derniere[0]}")

    regularite = dashboard.get("regularite") or {}

    if regularite.get("semaines"):
        lignes.append(f"Bilans hebdomadaires remplis : {regularite['semaines']}")

    return lignes


def rediger_bilan_j90(client_page_id: str, dashboard: dict) -> dict:
    if not bilan_final_disponible(dashboard):
        raise LookupError("Bilan pas encore disponible")

    if not _quota_jour_ok(f"b:{client_page_id}", 5):
        raise PermissionError("Limite du jour atteinte")

    blocs = [_contexte(client_page_id, dashboard), "Avant / maintenant :", *_lignes_avant_apres(dashboard)]

    try:
        sources = notion_service.reponses_des_fiches(client_page_id, dashboard.get("fiches") or [], [_BILAN_J90_MASTER_ID])
    except Exception:
        sources = []

    for source in sources:
        blocs.append("Ses réponses au bilan J90 :")
        blocs.extend(f"- {libelle} {valeur[:400]}" for libelle, valeur in source["reponses"])

    texte = ia_service.generer(_SYSTEME_BILAN_J90, [{"role": "user", "texte": "\n".join(blocs)}], temperature=0.5, max_tokens=900)
    return {"texte": texte}
