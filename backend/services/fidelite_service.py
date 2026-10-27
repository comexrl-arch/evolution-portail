# Fidelite et preuves (lot 4, decision de Rony du 25/10/2026) :
# - objectif 90 jours saisi par le client a l'accueil guide ;
# - lien de partage en lecture seule de sa progression (banquier, associe...) ;
# - avis du client a J90, cite seulement avec son accord ;
# - recap hebdomadaire « ta semaine en 3 chiffres », envoye par n8n le lundi.
#   Depuis le 27/10/2026 (decision de Rony), il part par WhatsApp quand le
#   client a un numero, avec le lien direct vers son bilan hebdo ; l'email
#   reste pour les clients sans numero ou qui ont refuse WhatsApp.

import json
import os
import re
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.services import ia_service, notion_service, portal_auth_service

_MAX_OBJECTIF = 300
_MAX_AVIS = 1500
_NOM_AVIS = "Avis J90"
PARTAGE_JOURS = 30
_SEL_PARTAGE = "partage-progression"
URL_PORTAIL = os.getenv("PORTAL_FRONTEND_URL", "https://portail.rl-evolution.fr").split(",")[0].strip().rstrip("/")


# --- Objectif 90 jours -------------------------------------------------------

def enregistrer_objectif(client_page_id: str, objectif: str) -> str:
    texte = " ".join(str(objectif or "").split())

    if not texte or len(texte) > _MAX_OBJECTIF:
        raise ValueError("Objectif vide ou trop long")

    notion_service._update_page(client_page_id, {"Objectif 90j": {"rich_text": [{"text": {"content": texte}}]}})
    notion_service._cache_clear(f"dashboard:{client_page_id}")
    return texte


# --- Lien de partage ---------------------------------------------------------

def _serializer() -> URLSafeTimedSerializer:
    if not portal_auth_service.SECRET_KEY:
        raise RuntimeError("PORTAL_SECRET_KEY manquant.")

    return URLSafeTimedSerializer(portal_auth_service.SECRET_KEY, salt=_SEL_PARTAGE)


def creer_lien_partage(client_page_id: str) -> dict:
    jeton = _serializer().dumps({"client_page_id": client_page_id, "type": "partage"})
    return {"jeton": jeton, "url": f"{URL_PORTAIL}/?partage={jeton}", "jours": PARTAGE_JOURS}


def client_du_partage(jeton: str) -> str:
    try:
        donnees = _serializer().loads(jeton, max_age=PARTAGE_JOURS * 24 * 3600)
    except SignatureExpired as error:
        raise ValueError("Ce lien de partage a expiré.") from error
    except BadSignature as error:
        raise ValueError("Lien de partage invalide.") from error

    if donnees.get("type") != "partage" or not donnees.get("client_page_id"):
        raise ValueError("Lien de partage invalide.")

    return donnees["client_page_id"]


def progression_publique(dashboard: dict) -> dict:
    """Ce qu'un tiers voit : prenom, formule, avancement et chiffres. Jamais
    les reponses aux fiches, l'email, le telephone ni le nom de famille."""
    perso = dashboard.get("personnalisation") or {}
    kpi_champs = ("valeur_j0", "valeur_j30", "valeur_j60", "valeur_j90")

    return {
        "prenom": (dashboard.get("nom") or "").split(" ")[0],
        "parcours": dashboard.get("parcours"),
        "date_demarrage": dashboard.get("date_demarrage"),
        "fiches": [{"etat": f.get("etat"), "module": f.get("module")} for f in dashboard.get("fiches") or []],
        "kpi": [{"nom": k.get("nom"), **{c: k.get(c) for c in kpi_champs}} for k in dashboard.get("kpi") or []],
        "personnalisation": {c: perso.get(c) for c in ("scores_diagnostic", "scores", "total", "total_actuel", "chiffres")} if perso else None,
        "regularite": dashboard.get("regularite"),
    }


# --- Avis J90 ----------------------------------------------------------------

def enregistrer_avis(client_page_id: str, dashboard: dict, note: int, avis: str, accord_publication: bool, signature: str = "") -> None:
    from backend.services.idris_service import bilan_final_disponible

    if not bilan_final_disponible(dashboard):
        raise LookupError("Avis pas encore ouvert")

    avis = str(avis or "").strip()

    if not 0 <= int(note) <= 10 or not avis or len(avis) > _MAX_AVIS or len(signature or "") > 120:
        raise ValueError("Avis invalide")

    jour = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contenu = json.dumps({
        "note_sur_10": int(note),
        "avis": avis,
        "accord_publication": bool(accord_publication),
        "signature_souhaitee": (signature or "").strip() if accord_publication else "",
    }, ensure_ascii=False)
    notion_service._create_page(notion_service.ENTREES_PORTAIL_DATA_SOURCE_ID, {
        "Nom": {"title": [{"text": {"content": f"{dashboard.get('nom') or 'Client'} — {_NOM_AVIS} — {jour}"}}]},
        "Client": {"relation": [{"id": client_page_id}]},
        "Date": {"date": {"start": jour}},
        "Données (JSON)": {"rich_text": [{"text": {"content": contenu[i:i + 2000]}} for i in range(0, len(contenu), 2000)]},
    })


# --- Recap hebdomadaire --------------------------------------------------------

_SYSTEME_RECAP = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-eVolution). Tu écris UNE ou DEUX phrases (35 mots au plus) que Rony glisse dans son e-mail du lundi à un client, à partir de ses chiffres de la semaine. Tutoiement, ton d'un coach qui connaît son client : chaleureux, concret, sans flatterie. Commente ce que les chiffres disent (un progrès, un déséquilibre entre contacts et rendez-vous...) et propose une petite action pour la semaine. Ne répète pas les chiffres un par un, n'en invente aucun. Ne commence pas par le prénom ni par « Bravo ». Réponds uniquement avec le texte."""


def _pluriel(nombre: float, mot: str) -> str:
    return f"{nombre:g} {mot}{'s' if nombre >= 2 else ''}"


def _phrase_idris(semaine: dict, serie: int) -> str:
    secours = (
        f"Ça fait {serie} semaines que tu tiens ton bilan, c'est ce rythme qui finit par payer. Cette semaine, garde le même cap."
        if serie > 1 else
        "Ton premier bilan est fait, c'est la base. Refais-le vendredi et on pourra comparer."
    )

    if not ia_service.enabled():
        return secours

    try:
        donnees = f"Semaine : {semaine['contacts']:g} contacts, {semaine['rdv']:g} rendez-vous, {semaine['ventes']:g} ventes. Semaines de bilan d'affilée : {serie}."
        phrase = ia_service.generer(_SYSTEME_RECAP, [{"role": "user", "texte": donnees}], temperature=0.7, max_tokens=150).strip()
        return phrase or secours
    except Exception as error:
        notion_service.logger.warning("Phrase du recap indisponible (%s)", error)
        return secours


def _prochaine_fiche(dashboard: dict) -> str | None:
    for fiche in dashboard.get("fiches") or []:
        if fiche.get("master_id") == notion_service._BILAN_HEBDO_MASTER_ID:
            continue

        if fiche.get("etat") != "Terminé" and "Bloqué" not in str(fiche.get("acces") or ""):
            return (fiche.get("nom") or "").split(" - ", 1)[-1] or None

    return None


def _fiche_lisible(nom: str) -> str:
    """« 9. MON OFFRE ACTUELLE » devient « la fiche 9, « Mon offre actuelle » »."""
    numero, _, titre = nom.partition(". ")

    if not numero.isdigit() or not titre:
        numero, titre = "", nom

    titre = titre.strip().lower()
    titre = titre[:1].upper() + titre[1:]
    return f"la fiche {numero}, « {titre} »" if numero else f"« {titre} »"


def _date_courte(jour: str) -> str:
    try:
        return datetime.strptime(str(jour)[:10], "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return str(jour)


# Indicatifs des numeros a 10 chiffres commencant par 0 : Antilles-Guyane,
# Reunion, Mayotte, sinon France metropolitaine.
_INDICATIFS = [
    (("0690", "0691", "0590"), "590"),
    (("0696", "0697", "0596"), "596"),
    (("0694", "0594"), "594"),
    (("0692", "0693", "0262"), "262"),
    (("0639", "0269"), "262"),
]
LIEN_BILAN = f"{URL_PORTAIL}/?ouvrir=bilan"


def numero_whatsapp(telephone) -> str | None:
    """Numero au format attendu par l'API WhatsApp (indicatif sans « + »),
    ou None s'il n'est pas exploitable."""
    brut = str(telephone or "").strip()

    if not brut:
        return None

    international = brut.startswith("+") or brut.startswith("00")
    chiffres = re.sub(r"\D", "", brut)

    if brut.startswith("00"):
        chiffres = chiffres[2:]

    if not international:
        if len(chiffres) != 10 or not chiffres.startswith("0"):
            return None

        indicatif = next((code for prefixes, code in _INDICATIFS if chiffres.startswith(prefixes)), "33")
        chiffres = indicatif + chiffres[1:]

    return chiffres if 10 <= len(chiffres) <= 15 else None


def _ligne_whatsapp(texte: str) -> str:
    # Parametre de modele WhatsApp : une seule ligne, sans tabulation ni
    # suite de plus de 4 espaces (regle Meta).
    return re.sub(r"\s+", " ", texte or "").strip()


def _bilan_semaine_derniere_fait(semaine: dict | None, aujourd_hui=None) -> bool:
    if not semaine:
        return False

    aujourd_hui = aujourd_hui or datetime.now(timezone.utc).date()
    lundi_precedent = aujourd_hui - timedelta(days=aujourd_hui.weekday() + 7)
    return str(semaine.get("semaine_du") or "") >= lundi_precedent.isoformat()


def recap_du_client(client_page_id: str, email: str, telephone=None, whatsapp_refuse: bool = False) -> dict | None:
    dashboard = notion_service.get_client_dashboard(client_page_id)
    jour = notion_service._jour_parcours(dashboard.get("date_demarrage"))

    if jour is None or jour < 7:
        return None

    prenom = (dashboard.get("nom") or "").split(" ")[0] or "Bonjour"
    bilan = next((f for f in dashboard.get("fiches") or [] if f.get("master_id") == notion_service._BILAN_HEBDO_MASTER_ID), None)
    historique = notion_service._historique_bilans(bilan["id"]) if bilan else []
    semaine = historique[-1] if historique else None
    serie = (dashboard.get("regularite") or {}).get("serie") or 0
    prochaine = _prochaine_fiche(dashboard)
    chiffres = None if semaine is None else {
        "semaine_du": semaine["semaine_du"], "contacts": semaine["contacts"], "rdv": semaine["rdv"], "ventes": semaine["ventes"],
    }
    lignes = [f"Bonjour {prenom},", ""]
    phrase_idris = _phrase_idris(semaine, serie) if chiffres else ""

    if chiffres:
        lignes += [
            f"Tu es à J{jour} de ton parcours. Ta semaine du {_date_courte(chiffres['semaine_du'])}, c'est "
            f"{_pluriel(chiffres['contacts'], 'contact')}, {chiffres['rdv']:g} rendez-vous "
            f"et {_pluriel(chiffres['ventes'], 'vente')}.",
            "",
            phrase_idris,
        ]
    else:
        lignes += [
            f"Tu es à J{jour} de ton parcours, et je n'ai pas encore vu passer ton bilan de la semaine.",
            "Prends 5 minutes vendredi pour le remplir : lundi prochain, tu recevras ici tes chiffres et ce qu'ils disent de ta prospection.",
        ]

    if prochaine:
        lignes += ["", f"Ta prochaine étape : {_fiche_lisible(prochaine)}. C'est elle qui te fera avancer le plus vite maintenant."]

    lignes += ["", f"Tout est dans ton espace : {URL_PORTAIL}", "", "Bonne semaine,", "Rony", "RL-eVolution"]

    numero = None if whatsapp_refuse else numero_whatsapp(telephone)

    if chiffres and _bilan_semaine_derniere_fait(semaine):
        phrase = (
            f"Ta semaine du {_date_courte(chiffres['semaine_du'])} : {_pluriel(chiffres['contacts'], 'contact')}, "
            f"{chiffres['rdv']:g} rendez-vous et {_pluriel(chiffres['ventes'], 'vente')}. {phrase_idris}"
        )
    else:
        phrase = "Ton bilan de la semaine dernière n'est pas encore fait : 2 minutes suffisent pour garder ton rythme."

    whatsapp = None if not numero else {
        "numero": numero,
        "parametres": [_ligne_whatsapp(prenom), _ligne_whatsapp(phrase), LIEN_BILAN],
        "texte": f"Bonjour {prenom}, c'est lundi. {_ligne_whatsapp(phrase)}\n\nTon bilan de la semaine t'attend ici : {LIEN_BILAN}\n\nBonne semaine,\nRony, RL-eVolution",
    }

    return {
        "client_page_id": client_page_id,
        "email": email,
        "prenom": prenom,
        "jour": jour,
        "chiffres": chiffres,
        "serie": serie,
        "prochaine_etape": prochaine,
        "objet": f"{prenom}, ta semaine en 3 chiffres" if chiffres else f"{prenom}, on fait le point sur ta semaine ?",
        "texte": "\n".join(lignes),
        "canal": "whatsapp" if whatsapp else "email",
        "lien_bilan": LIEN_BILAN,
        "whatsapp": whatsapp,
    }


def recaps_hebdo() -> list[dict]:
    """Clients en cours, avec un email, et qui n'ont pas coche « Récap hebdo
    désactivé » dans [DB] Clients (propriete facultative)."""
    recaps = []

    for row in notion_service._query_data_source(notion_service.CLIENTS_DATA_SOURCE_ID):
        props = row.get("properties", {})
        email = notion_service._prop_value(notion_service._prop(props, "E-mail"))

        if notion_service._prop_value(notion_service._prop(props, "État")) != "En cours" or not email:
            continue

        if notion_service._prop_value(notion_service._prop(props, "Récap hebdo désactivé")):
            continue

        telephone = notion_service._prop_value(notion_service._prop(props, "Téléphone"))
        refuse = bool(notion_service._prop_value(notion_service._prop(props, "Récap WhatsApp désactivé")))

        try:
            recap = recap_du_client(row["id"], email, telephone, refuse)
        except Exception as error:
            notion_service.logger.warning("Recap %s impossible (%s)", row.get("id"), error)
            recap = None

        if recap:
            recaps.append(recap)

    return recaps
