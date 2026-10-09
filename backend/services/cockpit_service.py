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
from datetime import date, datetime, timezone

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

    if "comptant" in texte:
        return MONTANT_COACHING_COMPTANT, "Comptant", ""

    if re.search(r"\b3\s*(x|fois|×)", texte):
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

