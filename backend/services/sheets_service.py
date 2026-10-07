"""Synchronisation portail -> Google Sheets "Tableau de bord" du client.

Chaque client a sa propre copie du modele (90 jours ou Atelier), creee
automatiquement et partagee avec lui. Les saisies du portail y sont reportees :

  fiche 13 (plan de la semaine)  -> onglet "Plan de la semaine"
  fiche 14 (tableau prospection) -> onglet "Prospects"
  fiche 17 (bilan hebdomadaire)  -> onglet "Suivi hebdo" (ligne S1..S13)
  fiche 19 (suivi de closing)    -> onglet "Propositions"

Configuration (variables d'environnement, jamais dans le code) :
  Option A - GOOGLE_SERVICE_ACCOUNT_JSON : cle JSON du compte de service (brute ou base64)
  Option B - GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET /
             GOOGLE_OAUTH_REFRESH_TOKEN : acces OAuth de ton propre compte Google
  (une simple "cle API" Google ne suffit PAS : elle ne peut pas ecrire dans un Drive)
  SHEETS_FOLDER_ID            : dossier Drive des copies clients (partage en
                                Editeur avec le compte de service)
  SHEETS_TEMPLATE_90J_ID / SHEETS_TEMPLATE_ATELIER_ID : modeles (defauts ci-dessous)

Sans cle de service, tout est desactive silencieusement : le portail continue
de fonctionner normalement.
"""

import base64
import json
import logging
import os
import threading
from datetime import date, datetime

logger = logging.getLogger("uvicorn.error")  # visible dans les logs Render

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_DRIVE = "https://www.googleapis.com/drive/v3"
_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"

# Modeles et dossier par defaut (ceux deja presents dans le Drive de Rony).
_DEFAULT_TEMPLATE_90J = "1FT_9qflpb6TSt1F_Lm5Chir_WqJ5nVr2TPCxtMSyqxY"
_DEFAULT_TEMPLATE_ATELIER = "1Tcrx6W1IKuQ_mlXJXx786ksc3WVOlYoBTkeCP-HfzY4"
_DEFAULT_FOLDER = "12nEtDNxUX5cE-QMdSET5mADmwTodLZKB"

_lock = threading.Lock()
_session = None
_cache_url: dict[str, str] = {}
_cache_tabs: dict[str, set[str]] = {}


def _config():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        return None

    try:
        if not raw.startswith("{"):
            raw = base64.b64decode(raw).decode("utf-8")

        return json.loads(raw)

    except Exception:
        logger.warning("GOOGLE_SERVICE_ACCOUNT_JSON illisible")
        return None


def _oauth_config():
    # Alternative au compte de service : acces OAuth de Rony (ses propres
    # identifiants Google + un jeton de renouvellement). Les classeurs sont
    # alors crees dans SON Drive, sans avoir a partager de dossier.
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    refresh = os.getenv("GOOGLE_OAUTH_REFRESH_TOKEN", "").strip()

    if cid and secret and refresh:
        return {"client_id": cid, "client_secret": secret, "refresh_token": refresh}

    return None


def enabled() -> bool:
    return _config() is not None or _oauth_config() is not None


def _http():
    global _session

    if _session is not None:
        return _session

    from google.auth.transport.requests import AuthorizedSession

    oauth = _oauth_config()

    if oauth:
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            None,
            refresh_token=oauth["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth["client_id"],
            client_secret=oauth["client_secret"],
            scopes=_SCOPES,
        )
    else:
        info = _config()

        if not info:
            raise RuntimeError("Acces Google non configure")

        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    _session = AuthorizedSession(creds)
    return _session


def _check(response, quoi: str):
    if response.status_code >= 300:
        raise RuntimeError(f"Google ({quoi}) {response.status_code} : {response.text[:300]}")

    return response


# ---------------------------------------------------------------- classeur

def _url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def _nom_classeur(client_page_id: str, client_nom: str, atelier: bool) -> str:
    court = client_page_id.replace("-", "")[:8]
    base = "Tableau de bord Atelier" if atelier else "Tableau de bord 90 jours"
    return f"{base} - {client_nom} [{court}]"


def _find(client_page_id: str) -> str | None:
    court = client_page_id.replace("-", "")[:8]
    q = f"name contains '[{court}]' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
    response = _check(
        _http().get(f"{_DRIVE}/files", params={"q": q, "fields": "files(id,name)", "pageSize": 5}),
        "recherche classeur",
    )
    files = response.json().get("files", [])
    return files[0]["id"] if files else None


def _share(sheet_id: str, email: str) -> None:
    if not email:
        return

    for notify in (False, True):
        response = _http().post(
            f"{_DRIVE}/files/{sheet_id}/permissions",
            params={"sendNotificationEmail": "true" if notify else "false"},
            json={"type": "user", "role": "writer", "emailAddress": email},
        )

        if response.status_code < 300:
            return

    logger.warning("Partage du classeur impossible pour %s : %s", email, response.text[:200])


def get_or_create_sheet(client_page_id: str, client_nom: str, email: str, atelier: bool) -> str | None:
    """Renvoie l'id du classeur du client, en le creant (copie du modele) au besoin."""
    if not enabled():
        return None

    with _lock:
        if client_page_id in _cache_url:
            return _cache_url[client_page_id]

        sheet_id = _find(client_page_id)

        if not sheet_id:
            template = (
                os.getenv("SHEETS_TEMPLATE_ATELIER_ID", _DEFAULT_TEMPLATE_ATELIER)
                if atelier
                else os.getenv("SHEETS_TEMPLATE_90J_ID", _DEFAULT_TEMPLATE_90J)
            )
            folder = os.getenv("SHEETS_FOLDER_ID", _DEFAULT_FOLDER)
            response = _check(
                _http().post(
                    f"{_DRIVE}/files/{template}/copy",
                    json={"name": _nom_classeur(client_page_id, client_nom, atelier), "parents": [folder]},
                ),
                "copie du modele",
            )
            sheet_id = response.json()["id"]
            _share(sheet_id, email)

        _cache_url[client_page_id] = sheet_id
        return sheet_id


def sheet_url(client_page_id: str, client_nom: str, email: str, atelier: bool) -> str | None:
    try:
        sheet_id = get_or_create_sheet(client_page_id, client_nom, email, atelier)
        return _url(sheet_id) if sheet_id else None

    except Exception as error:
        logger.warning("Classeur client indisponible : %s", error)
        return None


# ------------------------------------------------------------ lecture/ecriture

def _tabs(sheet_id: str) -> set[str]:
    if sheet_id not in _cache_tabs:
        response = _check(
            _http().get(f"{_SHEETS}/{sheet_id}", params={"fields": "sheets.properties.title"}),
            "onglets",
        )
        _cache_tabs[sheet_id] = {s["properties"]["title"] for s in response.json().get("sheets", [])}

    return _cache_tabs[sheet_id]


def _col_a(sheet_id: str, tab: str, last_row: int = 80) -> list[str]:
    response = _check(
        _http().get(f"{_SHEETS}/{sheet_id}/values/'{tab}'!A1:A{last_row}"),
        f"lecture {tab}",
    )
    return [row[0] if row else "" for row in response.json().get("values", [])]


def _write_row(sheet_id: str, tab: str, row: int, values: list) -> None:
    last = chr(ord("A") + len(values) - 1)
    _check(
        _http().put(
            f"{_SHEETS}/{sheet_id}/values/'{tab}'!A{row}:{last}{row}",
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": [values]},
        ),
        f"ecriture {tab}",
    )


def _write_cells(sheet_id: str, tab: str, row: int, cells: dict[str, object]) -> None:
    data = [
        {"range": f"'{tab}'!{col}{row}", "values": [[valeur]]}
        for col, valeur in cells.items()
        if valeur not in (None, "")
    ]

    if not data:
        return

    _check(
        _http().post(
            f"{_SHEETS}/{sheet_id}/values:batchUpdate",
            json={"valueInputOption": "USER_ENTERED", "data": data},
        ),
        f"ecriture {tab}",
    )


def _append_table_row(sheet_id: str, tab: str, header_label: str, values: list) -> None:
    # Retrouve la ligne d'en-tete (titre fusionne au-dessus) puis la 1re ligne
    # vide de la colonne A en dessous : fonctionne sur les deux modeles.
    colonne = _col_a(sheet_id, tab)
    header = next((i for i, v in enumerate(colonne) if v.strip() == header_label), None)

    if header is None:
        raise RuntimeError(f"En-tete '{header_label}' introuvable dans '{tab}'")

    cible = next(
        (i for i in range(header + 1, len(colonne)) if not colonne[i].strip()),
        len(colonne),
    )
    _write_row(sheet_id, tab, cible + 1, values)


def _date(valeur) -> str:
    return str(valeur or "")[:10]


def _num(valeur):
    try:
        return float(valeur) if valeur not in (None, "") else ""
    except (TypeError, ValueError):
        return ""


# ------------------------------------------------------------------ fiches

def _sync_prospect(sheet_id: str, d: dict) -> None:
    # Colonnes : Date | Prenom/Nom | Metier | Ville | Canal | Module/Test |
    # Reaction | Mots exacts | Action suivante | Date de relance | Statut
    _append_table_row(sheet_id, "Prospects", "Date", [
        _date(d.get("date_contact")), d.get("nom_prospect", ""), "", "", d.get("canal", ""),
        "", "", "", d.get("prochaine_action", ""), "", d.get("statut", ""),
    ])


def _sync_plan(sheet_id: str, d: dict) -> None:
    _append_table_row(sheet_id, "Plan de la semaine", "Semaine du", [
        _date(d.get("semaine_du")), _num(d.get("nb_prospects_a_contacter")),
        d.get("canal_principal", ""), d.get("segment_cible_priorite", ""),
        d.get("creneau_prospection", ""), "",
    ])


def _sync_proposition(sheet_id: str, d: dict) -> None:
    _append_table_row(sheet_id, "Propositions", "Date d'envoi", [
        _date(d.get("date_envoi")), d.get("nom_prospect", ""), _num(d.get("montant_offre")),
        _date(d.get("relance_prevue")), d.get("statut", ""), "",
    ])


def _semaine_index(semaine_du: str, date_demarrage: str | None) -> int | None:
    try:
        debut = datetime.fromisoformat(str(date_demarrage)[:10]).date()
        jour = datetime.fromisoformat(semaine_du[:10]).date()
    except (TypeError, ValueError):
        return None

    n = (jour - debut).days // 7 + 1
    return n if 1 <= n <= 13 else None


def _sync_bilan(sheet_id: str, d: dict, date_demarrage: str | None) -> None:
    # Ligne "S1".."S13" de l'onglet Suivi hebdo. La semaine se deduit de la
    # date de demarrage ; a defaut, premiere ligne encore vide. Les colonnes
    # de taux et de panier moyen sont des formules du modele : on n'y touche pas.
    tab = "Suivi hebdo"
    colonne = _col_a(sheet_id, tab, last_row=40)
    n = _semaine_index(_date(d.get("semaine_du")), date_demarrage)

    if n is None:
        premiere_vide = next(
            (i for i, v in enumerate(colonne) if v.strip().startswith("S") and v.strip()[1:].isdigit()
             and not _ligne_remplie(sheet_id, tab, i + 1)),
            None,
        )
        ligne = None if premiere_vide is None else premiere_vide + 1
    else:
        index = next((i for i, v in enumerate(colonne) if v.strip() == f"S{n}"), None)
        ligne = None if index is None else index + 1

    if ligne is None:
        raise RuntimeError("Ligne de semaine introuvable dans 'Suivi hebdo'")

    _write_cells(sheet_id, tab, ligne, {
        "C": _num(d.get("nb_contacts_tentes")),
        "D": _num(d.get("nb_rdv_obtenus")),
        "E": _num(d.get("nb_ventes_conclues")),
        "J": d.get("objectif_semaine_prochaine", ""),
    })


def _ligne_remplie(sheet_id: str, tab: str, row: int) -> bool:
    response = _check(_http().get(f"{_SHEETS}/{sheet_id}/values/'{tab}'!C{row}:E{row}"), "lecture ligne")
    return any(str(c).strip() for r in response.json().get("values", []) for c in r)


_FICHES = {
    "13": ("Plan de la semaine", lambda sid, d, dd: _sync_plan(sid, d)),
    "14": ("Prospects", lambda sid, d, dd: _sync_prospect(sid, d)),
    "17": ("Suivi hebdo", lambda sid, d, dd: _sync_bilan(sid, d, dd)),
    "19": ("Propositions", lambda sid, d, dd: _sync_proposition(sid, d)),
}


def sync_entry(numero_fiche: str, data: dict, client_page_id: str, client_nom: str,
               email: str, atelier: bool, date_demarrage: str | None) -> None:
    """Reporte une saisie du portail dans le classeur du client (best effort)."""
    cible = _FICHES.get(str(numero_fiche))

    if not cible:
        logger.info("Synchro Sheets ignoree : la fiche %s n'a pas d'onglet associe", numero_fiche)
        return

    if not enabled():
        return

    tab, fonction = cible

    try:
        sheet_id = get_or_create_sheet(client_page_id, client_nom, email, atelier)

        if not sheet_id or tab not in _tabs(sheet_id):
            return

        fonction(sheet_id, data, date_demarrage)
        logger.info("Synchro Sheets OK : fiche %s -> '%s' (%s)", numero_fiche, tab, client_nom)

    except Exception as error:
        logger.warning("Synchro Sheets echouee (fiche %s, %s) : %s", numero_fiche, client_nom, error)


def sync_entry_async(*args, **kwargs) -> None:
    threading.Thread(target=sync_entry, args=args, kwargs=kwargs, daemon=True).start()
