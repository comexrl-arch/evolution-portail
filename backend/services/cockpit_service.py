# cockpit_service.py - Report d'un contrat DocuSeal signe dans le cockpit Google
# Sheets du coach ("Cockpit RL-eVolution").
#
# Appele en tache de fond par le webhook DocuSeal (portal_main.py), independamment
# de l'onboarding Notion. Ecrit uniquement des cellules de saisie, jamais une
# colonne calculee du cockpit :
#   - "Suivi clients"            : A (client), B (offre), AD (email)
#   - "Contrats & encaissements" : A, B, D, F, I, J, L, M (email), O (signe le)
#
# Garde-fous :
#   - recherche par email (Suivi clients!AD, Contrats!M) : un webhook rejoue ne
#     cree jamais de doublon et aucune donnee existante n'est ecrasee ;
#   - un nom deja utilise par un autre client bloque l'ecriture (la validation
#     anti-doublon de Suivi clients!A ne s'applique pas aux ecritures API) ;
#   - ecriture en mode RAW : un nom venant de DocuSeal n'est jamais interprete
#     comme une formule ; les dates sont envoyees en numero de serie.
#
# Configuration : COCKPIT_SPREADSHEET_ID (identifiant du classeur) + l'acces
# Google deja utilise par sheets_service. Sans identifiant, tout est desactive.

import logging
import os
import re
import threading
from datetime import date, datetime, timedelta, timezone

from backend.services import sheets_service

logger = logging.getLogger("uvicorn.error")

_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"

ONGLET_CLIENTS = "Suivi clients"
ONGLET_CONTRATS = "Contrats & encaissements"

# Lignes de donnees : celles ou le cockpit porte ses formules et validations.
PREMIERE_LIGNE = 5
DERNIERE_LIGNE_CLIENTS = 100
DERNIERE_LIGNE_CONTRATS = 40

# Parcours DocuSeal -> (offre dans Suivi clients!B, formule dans Contrats!B).
# Libelles exacts des listes deroulantes du cockpit.
_OFFRES = {
    "Atelier": ("Atelier", "Atelier Collectif"),
    "Coaching 90 jours": ("Coaching 90 j", "Coaching 90 jours"),
}

MONTANT_ATELIER = 390
MONTANT_COACHING_COMPTANT = 1720
MONTANT_COACHING_3_FOIS = 1800  # 3 x 600 EUR
MONTANT_COACHING_REDUIT = 1520  # ancien participant Atelier ou filleul

_FUSEAU_DEFAUT = "America/Guadeloupe"

# Deux signatures traitees en meme temps ne doivent pas viser la meme ligne libre.
_verrou = threading.Lock()


class NomDejaPris(RuntimeError):
    pass


class CockpitPlein(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.getenv("COCKPIT_SPREADSHEET_ID", "").strip()) and sheets_service.enabled()


def _plage(onglet: str, a1: str) -> str:
    return "'" + onglet.replace("'", "''") + "'!" + a1


def _serie(jour: date) -> int:
    # Numero de serie Google Sheets : la cellule (deja au format date) l'affiche
    # en jj/mm/aaaa quelle que soit la langue du classeur.
    return (jour - date(1899, 12, 30)).days


def date_signature(completed_at: str | None) -> date:
    # completed_at DocuSeal est en UTC : converti dans le fuseau du coach pour
    # qu'une signature tardive le soir ne tombe pas le lendemain.
    try:
        from zoneinfo import ZoneInfo

        fuseau = ZoneInfo(os.getenv("COCKPIT_TIMEZONE", _FUSEAU_DEFAUT))
    except Exception:
        fuseau = timezone.utc

    texte = str(completed_at or "").strip()

    if texte:
        try:
            instant = datetime.fromisoformat(texte.replace("Z", "+00:00"))

            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)

            return instant.astimezone(fuseau).date()

        except ValueError:
            pass

    return datetime.now(fuseau).date()


def montant(parcours: str, modalite: str = "") -> tuple[int | None, str, str]:
    # Renvoie (montant, mode de paiement, note). Le montant du coaching depend du
    # mode de paiement choisi sur systeme.io : sans indication fiable dans le
    # contrat, il reste vide avec une note pour le coach.
    if parcours == "Atelier":
        return MONTANT_ATELIER, "", ""

    texte = (modalite or "").lower()

    # Option du contrat Coaching "Ancien participant Atelier ou filleul : 1 520 €
    # (comptant ou 3 × 506,67 €)" : testee en premier, elle contient "comptant".
    if "filleul" in texte or "ancien participant" in texte or re.search(r"1[\s\u00a0\u202f.]?520\b", texte):
        return MONTANT_COACHING_REDUIT, "", "Tarif ancien participant / filleul : comptant ou 3 × 506,67 € (à confirmer)"

    if "comptant" in texte:
        return MONTANT_COACHING_COMPTANT, "Comptant", ""

    if re.search(r"\b3\s*(x|fois|×|mensualit)", texte):
        return MONTANT_COACHING_3_FOIS, "", "Paiement en 3 × 600 €"

    return None, "", "Montant à confirmer : 1 720 € comptant ou 1 800 € en 3 × 600 €"


def _lire_colonnes(sheet_id: str, plages: list[str]) -> list[list]:
    reponse = sheets_service._check(
        sheets_service._http().get(
            f"{_SHEETS}/{sheet_id}/values:batchGet",
            params={"ranges": plages, "majorDimension": "COLUMNS", "valueRenderOption": "UNFORMATTED_VALUE"},
            timeout=30,
        ),
        "lecture cockpit",
    )
    colonnes = []

    for plage in reponse.json().get("valueRanges", []):
        valeurs = plage.get("values") or [[]]
        colonnes.append(valeurs[0])

    return colonnes


def _cellule(colonne: list, index: int) -> str:
    return str(colonne[index]).strip() if index < len(colonne) and colonne[index] is not None else ""


def _index_email(colonne: list, email: str) -> int | None:
    if not email:
        return None

    for index, valeur in enumerate(colonne):
        if str(valeur or "").strip().lower() == email:
            return index

    return None


def _nom_pris(noms: list, nom: str, sauf: int | None = None) -> bool:
    return any(i != sauf and _cellule(noms, i).lower() == nom.lower() for i in range(len(noms)))


def _premiere_ligne_libre(colonnes: list[list], nb_lignes: int) -> int | None:
    for index in range(nb_lignes):
        if all(not _cellule(colonne, index) for colonne in colonnes):
            return index

    return None


def _ecrire(sheet_id: str, cellules: dict[str, object]) -> None:
    sheets_service._check(
        sheets_service._http().post(
            f"{_SHEETS}/{sheet_id}/values:batchUpdate",
            json={
                "valueInputOption": "RAW",
                "data": [{"range": plage, "values": [[valeur]]} for plage, valeur in cellules.items()],
            },
            timeout=30,
        ),
        "ecriture cockpit",
    )


def enregistrer_signature(infos: dict) -> str:
    with _verrou:
        return _enregistrer(infos)


def _enregistrer(infos: dict) -> str:
    # infos : nom, email, parcours, date_demarrage (AAAA-MM-JJ ou ""),
    # completed_at (ISO DocuSeal ou ""), modalite_paiement (texte ou "").
    # Renvoie "cree", "signature_completee" ou "deja_enregistre".
    sheet_id = os.getenv("COCKPIT_SPREADSHEET_ID", "").strip()
    email = str(infos.get("email") or "").strip().lower()
    nom = str(infos.get("nom") or "").strip()
    parcours = infos.get("parcours")

    if not email or not nom:
        # Garde-fou : un email vide correspondrait a la premiere cellule vide.
        raise ValueError("Email ou nom absent")

    offre_client, formule = _OFFRES[parcours]
    signe_le = _serie(date_signature(infos.get("completed_at")))

    nb_clients = DERNIERE_LIGNE_CLIENTS - PREMIERE_LIGNE + 1
    nb_contrats = DERNIERE_LIGNE_CONTRATS - PREMIERE_LIGNE + 1
    fin_c, fin_k = DERNIERE_LIGNE_CLIENTS, DERNIERE_LIGNE_CONTRATS

    noms_clients, emails_clients, noms_contrats, emails_contrats, signes = _lire_colonnes(sheet_id, [
        _plage(ONGLET_CLIENTS, f"A{PREMIERE_LIGNE}:A{fin_c}"),
        _plage(ONGLET_CLIENTS, f"AD{PREMIERE_LIGNE}:AD{fin_c}"),
        _plage(ONGLET_CONTRATS, f"A{PREMIERE_LIGNE}:A{fin_k}"),
        _plage(ONGLET_CONTRATS, f"M{PREMIERE_LIGNE}:M{fin_k}"),
        _plage(ONGLET_CONTRATS, f"O{PREMIERE_LIGNE}:O{fin_k}"),
    ])

    contrat = _index_email(emails_contrats, email)

    if contrat is not None:
        if _cellule(signes, contrat):
            return "deja_enregistre"

        _ecrire(sheet_id, {_plage(ONGLET_CONTRATS, f"O{PREMIERE_LIGNE + contrat}"): signe_le})
        return "signature_completee"

    cellules: dict[str, object] = {}
    client = _index_email(emails_clients, email)

    if client is None:
        if _nom_pris(noms_clients, nom):
            raise NomDejaPris("Nom de client deja utilise dans Suivi clients")

        client = _premiere_ligne_libre([noms_clients, emails_clients], nb_clients)

        if client is None:
            raise CockpitPlein("Suivi clients complet")

        ligne = PREMIERE_LIGNE + client
        cellules[_plage(ONGLET_CLIENTS, f"A{ligne}")] = nom
        cellules[_plage(ONGLET_CLIENTS, f"B{ligne}")] = offre_client
        cellules[_plage(ONGLET_CLIENTS, f"AD{ligne}")] = email
        nom_client = nom
    else:
        nom_client = _cellule(noms_clients, client)

        if not nom_client:
            if _nom_pris(noms_clients, nom, sauf=client):
                raise NomDejaPris("Nom de client deja utilise dans Suivi clients")

            nom_client = nom
            cellules[_plage(ONGLET_CLIENTS, f"A{PREMIERE_LIGNE + client}")] = nom

    libre = _premiere_ligne_libre([noms_contrats, emails_contrats], nb_contrats)

    if libre is None:
        raise CockpitPlein("Contrats & encaissements complet")

    ligne = PREMIERE_LIGNE + libre
    demarrage = signe_le

    try:
        demarrage = _serie(date.fromisoformat(str(infos.get("date_demarrage") or "")))
    except ValueError:
        # Date absente ou impossible (ex. 31/02 saisi dans le contrat) : on
        # retombe sur la date de signature plutot que d'abandonner l'ecriture.
        pass

    prix, mode, note = montant(parcours, infos.get("modalite_paiement") or "")
    cellules[_plage(ONGLET_CONTRATS, f"A{ligne}")] = nom_client
    cellules[_plage(ONGLET_CONTRATS, f"B{ligne}")] = formule
    cellules[_plage(ONGLET_CONTRATS, f"D{ligne}")] = demarrage
    cellules[_plage(ONGLET_CONTRATS, f"J{ligne}")] = "En cours"
    cellules[_plage(ONGLET_CONTRATS, f"M{ligne}")] = email
    cellules[_plage(ONGLET_CONTRATS, f"O{ligne}")] = signe_le

    if prix is not None:
        cellules[_plage(ONGLET_CONTRATS, f"F{ligne}")] = prix

    if mode:
        cellules[_plage(ONGLET_CONTRATS, f"I{ligne}")] = mode

    if note:
        cellules[_plage(ONGLET_CONTRATS, f"L{ligne}")] = note

    _ecrire(sheet_id, cellules)
    return "cree"


def aujourd_hui() -> date:
    return date_signature(None)


def marquer_onboarding(email: str, client_notion: bool, acces_envoye_le: date | None) -> str:
    # Apres l'onboarding Notion : coche Suivi clients!AF (client Notion cree)
    # et date AG (acces portail envoye le) sur la ligne du client, retrouvee
    # par email (AD). Ne remplace jamais une valeur deja saisie.
    # Renvoie "marque", "deja_a_jour" ou "absent".
    with _verrou:
        return _marquer(email, client_notion, acces_envoye_le)


def _marquer(email: str, client_notion: bool, acces_envoye_le: date | None) -> str:
    sheet_id = os.getenv("COCKPIT_SPREADSHEET_ID", "").strip()
    email = str(email or "").strip().lower()
    fin = DERNIERE_LIGNE_CLIENTS

    emails, coches, acces = _lire_colonnes(sheet_id, [
        _plage(ONGLET_CLIENTS, f"AD{PREMIERE_LIGNE}:AD{fin}"),
        _plage(ONGLET_CLIENTS, f"AF{PREMIERE_LIGNE}:AF{fin}"),
        _plage(ONGLET_CLIENTS, f"AG{PREMIERE_LIGNE}:AG{fin}"),
    ])
    index = _index_email(emails, email)

    if index is None:
        return "absent"

    ligne = PREMIERE_LIGNE + index
    cellules: dict[str, object] = {}

    if client_notion and not (index < len(coches) and coches[index] is True):
        cellules[_plage(ONGLET_CLIENTS, f"AF{ligne}")] = True

    if acces_envoye_le is not None and not _cellule(acces, index):
        cellules[_plage(ONGLET_CLIENTS, f"AG{ligne}")] = _serie(acces_envoye_le)

    if not cellules:
        return "deja_a_jour"

    _ecrire(sheet_id, cellules)
    return "marque"


def reporter_demarrage(email: str, demarrage: date) -> str:
    # Atelier : la date de la session 1 arrive avec la signature du coach, apres
    # celle du participant. Remplace Contrats!D seulement s'il est vide ou s'il
    # vaut encore la date de signature (O), mise par defaut a la creation de la
    # ligne : une date saisie a la main est conservee.
    # Renvoie "reporte", "deja_a_jour" ou "absent".
    with _verrou:
        return _reporter_demarrage(email, demarrage)


def _reporter_demarrage(email: str, demarrage: date) -> str:
    sheet_id = os.getenv("COCKPIT_SPREADSHEET_ID", "").strip()
    email = str(email or "").strip().lower()
    fin = DERNIERE_LIGNE_CONTRATS

    emails, debuts, signes = _lire_colonnes(sheet_id, [
        _plage(ONGLET_CONTRATS, f"M{PREMIERE_LIGNE}:M{fin}"),
        _plage(ONGLET_CONTRATS, f"D{PREMIERE_LIGNE}:D{fin}"),
        _plage(ONGLET_CONTRATS, f"O{PREMIERE_LIGNE}:O{fin}"),
    ])
    index = _index_email(emails, email)

    if index is None:
        return "absent"

    actuel = _cellule(debuts, index)
    nouveau = _serie(demarrage)

    if actuel == str(nouveau) or (actuel and actuel != _cellule(signes, index)):
        return "deja_a_jour"

    _ecrire(sheet_id, {_plage(ONGLET_CONTRATS, f"D{PREMIERE_LIGNE + index}"): nouveau})
    return "reporte"



# --- Lecture seule : onglet « Suivi client » de l'Espace Coach ----------------
#
# Uniquement des lectures (values.get / values:batchGet), jamais d'ecriture.
# Les colonnes sont retrouvees par le texte de leur en-tete (ligne 4), jamais
# par leur lettre. Seules les colonnes listees ci-dessous sont lues : Notes,
# Reste a encaisser, Email et le suivi portail (AE a AN) ne sont jamais demandes
# a Google, donc jamais renvoyes.

LIGNE_EN_TETES = 4

# cle de la reponse -> en-tete exact du cockpit (le "☐" des cases est ignore).
EN_TETES_SUIVI = {
    "nom": "Client",
    "offre": "Offre",
    "date_rdv_qualifie": "Date RDV qualifié",
    "rdv_qualifie": "☐ RDV qualifié",
    "questionnaire_envoye": "☐ Questionnaire envoyé",
    "date_premiere_session": "Date 1re session",
    "premiere_session_faite": "☐ 1re session faite",
    "synthese_envoyee": "☐ Synthèse envoyée",
    "date_j7": "J+7",
    "j7_fait": "☐ J+7 fait",
    "date_j15": "J+15",
    "j15_fait": "☐ J+15 fait",
    "date_j30": "J+30",
    "bilan_j30_fait": "☐ Bilan J+30 fait",
    "decision": "Décision",
    "suite_cloture_envoyee": "☐ Suite ou clôture envoyée",
    "etape": "Étape en cours",
    "prochaine_action": "Prochaine action",
    "echeance": "Échéance",
    "alerte": "Alerte",
    "leads": "Leads",
    "rdv": "RDV",
    "ventes": "Ventes",
    "conversion": "Conversion",
    "panier_moyen": "Panier moyen (€)",
    "reachat": "Réachat",
    "etape_numero": "n",
}

# Etapes du process, dans l'ordre du cockpit : (cle, libelle, case, date prevue).
# "Fait" = case cochee (valeur booleenne vraie). La decision n'a pas de case :
# elle est faite quand la colonne Décision est renseignee, comme dans la formule
# de l'etape en cours (colonne n) du cockpit.
ETAPES_SUIVI = [
    ("rdv_qualifie", "RDV qualifié", "rdv_qualifie", "date_rdv_qualifie"),
    ("questionnaire_envoye", "Questionnaire envoyé", "questionnaire_envoye", None),
    ("premiere_session", "1re session faite", "premiere_session_faite", "date_premiere_session"),
    ("synthese_envoyee", "Synthèse envoyée", "synthese_envoyee", None),
    ("j7", "Suivi J+7", "j7_fait", "date_j7"),
    ("j15", "Suivi J+15", "j15_fait", "date_j15"),
    ("bilan_j30", "Bilan J+30", "bilan_j30_fait", "date_j30"),
    ("decision", "Décision", None, None),
    ("suite_cloture", "Suite ou clôture envoyée", "suite_cloture_envoyee", None),
]

INDICATEURS_SUIVI = ["leads", "rdv", "ventes", "conversion", "panier_moyen", "reachat"]

# Valeurs de la colonne n du cockpit : 1 a 7 = etape en cours, 8 = termine.
ETAPE_TERMINEE = 8


class StructureCockpitInvalide(RuntimeError):
    pass


def _normaliser_en_tete(texte) -> str:
    return " ".join(str(texte or "").replace("☐", " ").split()).casefold()


def _lettre_colonne(index: int) -> str:
    lettres = ""
    index += 1

    while index:
        index, reste = divmod(index - 1, 26)
        lettres = chr(65 + reste) + lettres

    return lettres


def _colonnes_suivi(en_tetes: list) -> dict[str, str]:
    # Associe chaque cle a la lettre de sa colonne. En-tete absent ou en double :
    # erreur, plutot que de lire une autre colonne. Le message ne cite que des
    # en-tetes, jamais une donnee client.
    positions: dict[str, list[int]] = {}

    for index, texte in enumerate(en_tetes):
        cle = _normaliser_en_tete(texte)

        if cle:
            positions.setdefault(cle, []).append(index)

    colonnes, manquants, doublons = {}, [], []

    for cle, en_tete in EN_TETES_SUIVI.items():
        trouves = positions.get(_normaliser_en_tete(en_tete), [])

        if not trouves:
            manquants.append(en_tete)
        elif len(trouves) > 1:
            doublons.append(en_tete)
        else:
            colonnes[cle] = _lettre_colonne(trouves[0])

    if manquants or doublons:
        raise StructureCockpitInvalide(
            f"En-tetes de {ONGLET_CLIENTS} non reconnus : manquants={manquants} doublons={doublons}"
        )

    return colonnes


def _lire_en_tetes(sheet_id: str) -> list:
    reponse = sheets_service._check(
        sheets_service._http().get(
            f"{_SHEETS}/{sheet_id}/values/{_plage(ONGLET_CLIENTS, f'{LIGNE_EN_TETES}:{LIGNE_EN_TETES}')}",
            params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
            timeout=30,
        ),
        "lecture en-tetes cockpit",
    )
    lignes = reponse.json().get("values") or [[]]
    return lignes[0]


def _brut(colonne: list, index: int):
    return colonne[index] if index < len(colonne) else None


def _texte(valeur) -> str | None:
    if valeur is None or isinstance(valeur, bool):
        return None

    texte = str(valeur).strip()
    return texte or None


def _date_iso(valeur) -> str | None:
    # Les dates arrivent en numero de serie (UNFORMATTED_VALUE). Un texte libre
    # n'est jamais interprete : la date reste vide.
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None

    if not 1 <= valeur < 2958466:
        return None

    return (date(1899, 12, 30) + timedelta(days=int(valeur))).isoformat()


def _indicateur(valeur):
    if isinstance(valeur, bool):
        return None

    if isinstance(valeur, (int, float)):
        return valeur

    return _texte(valeur)


def _etape_numero(valeur) -> int | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None

    numero = int(valeur)
    return numero if numero == valeur and 1 <= numero <= ETAPE_TERMINEE else None


def _fiche_suivi(valeurs: dict[str, list], index: int) -> dict | None:
    def brut(cle):
        return _brut(valeurs[cle], index)

    nom = _texte(brut("nom"))

    if not nom:
        return None

    etapes = []

    for cle, libelle, case, colonne_date in ETAPES_SUIVI:
        etape = {"cle": cle, "libelle": libelle}

        if case is None:
            decision = _texte(brut("decision"))
            etape["fait"] = decision is not None
            etape["valeur"] = decision
        else:
            etape["fait"] = brut(case) is True

        if colonne_date:
            etape["date"] = _date_iso(brut(colonne_date))

        etapes.append(etape)

    indicateurs = {}

    for cle in INDICATEURS_SUIVI:
        valeur = _indicateur(brut(cle))

        if valeur is not None:
            indicateurs[cle] = valeur

    return {
        "ligne": PREMIERE_LIGNE + index,
        "nom": nom,
        "offre": _texte(brut("offre")),
        "etape_numero": _etape_numero(brut("etape_numero")),
        "etape": _texte(brut("etape")),
        "date_premiere_session": _date_iso(brut("date_premiere_session")),
        "etapes": etapes,
        "prochaine_action": _texte(brut("prochaine_action")),
        "echeance": _date_iso(brut("echeance")),
        "alerte": _texte(brut("alerte")),
        "indicateurs": indicateurs,
    }


def lire_suivi_clients() -> list[dict]:
    # Une fiche par ligne de "Suivi clients" dont la colonne Client est remplie.
    sheet_id = os.getenv("COCKPIT_SPREADSHEET_ID", "").strip()

    try:
        colonnes = _colonnes_suivi(_lire_en_tetes(sheet_id))
        cles = list(colonnes)
        lues = _lire_colonnes(sheet_id, [
            _plage(ONGLET_CLIENTS, f"{colonnes[c]}{PREMIERE_LIGNE}:{colonnes[c]}{DERNIERE_LIGNE_CLIENTS}")
            for c in cles
        ])

    except RuntimeError:
        raise

    except Exception as error:
        # Erreur reseau ou d'authentification Google : seul le type remonte
        # (le texte d'une erreur requests contient l'URL appelee).
        raise RuntimeError(f"Google (lecture suivi clients) {type(error).__name__}") from None

    if len(lues) != len(cles):
        raise RuntimeError("Google (lecture suivi clients) reponse incomplete")

    valeurs = dict(zip(cles, lues))
    nb_lignes = DERNIERE_LIGNE_CLIENTS - PREMIERE_LIGNE + 1
    fiches = (_fiche_suivi(valeurs, index) for index in range(nb_lignes))
    return [fiche for fiche in fiches if fiche]
