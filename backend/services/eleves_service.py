# Onglet « Élèves » de l'Espace Coach (28/10/2026) : ce que chaque élève fait
# dans son espace client, lu aux mêmes sources que le portail (Notion), pour
# que les deux espaces disent la même chose.
#
# Avant, l'Espace Coach ne lisait que le cockpit Google Sheets (« Suivi
# client », tenu à la main) et la fiche 8 : rien de ce que l'élève saisit
# (fiches, KPI, carnet de prospects, bilans, retours d'Idris) n'y remontait.
#
# - liste() : une ligne légère par élève (3 requêtes Notion par élève).
# - detail() : le tableau de bord exact de l'élève (get_client_dashboard, le
#   même calcul que /portal/me) + son carnet + ses bilans hebdomadaires.
# Depuis le 29/10/2026, Rony y signe aussi les retours d'Idris et y écrit le
# compte rendu de chaque point (comptes_rendus_service).

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from backend.services import notion_service as ns
from backend.services import comptes_rendus_service, prospects_service

logger = logging.getLogger(__name__)

# Pool dédié : get_client_dashboard utilise déjà ns._POOL, l'attendre depuis
# le même pool pourrait le bloquer.
_POOL_ELEVES = ThreadPoolExecutor(max_workers=4)

# « Terminé » sert d'archive dans [DB] Clients (pas d'option « Archivé »).
_ETATS_ARCHIVES = {"Terminé"}


def _jours_depuis(valeur, maintenant: datetime) -> int | None:
    if not valeur:
        return None

    try:
        quand = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None

    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)

    return max((maintenant - quand).days, 0)


def _derniere_connexion(email: str | None) -> str | None:
    if not email:
        return None

    lignes = ns._query_data_source(
        ns.CONNEXIONS_DATA_SOURCE_ID,
        filter_={"property": "Email", "title": {"equals": email}},
        sorts=[{"property": "Date de connexion", "direction": "descending"}],
    )
    dates = [ns._prop_value(ns._prop(l.get("properties", {}), "Date de connexion")) for l in lignes]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def _ligne_eleve(row: dict, maintenant: datetime) -> dict:
    client_id = row["id"]
    props = row.get("properties", {})
    parcours = ns._prop_value(ns._prop(props, "Parcours"))
    email = ns._prop_value(ns._prop(props, "E-mail"))
    debut = ns._prop_value(ns._prop(props, "Date de demarrage")) or ns._prop_value(ns._prop(props, "Date de démarrage"))
    atelier = ns._est_parcours_atelier(parcours)

    fiches = ns._query_data_source(
        ns.FICHES_CLIENT_DATA_SOURCE_ID,
        filter_={"property": "⁠[DB] Clients⁠", "relation": {"contains": client_id}},
    )
    etats = []

    for page in fiches:
        fiche_props = page.get("properties", {})
        master_id = ns._resolve_master_id(fiche_props)

        if master_id is None or (atelier and master_id not in ns._ATELIER_JOUR):
            continue

        etats.append(ns._prop_value(ns._prop(fiche_props, "État")))

    entrees = ns._query_data_source(
        ns.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"property": "Client", "relation": {"contains": client_id}},
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
    )
    # Ce que Rony ecrit lui-meme (comptes rendus de point) n'est pas une saisie de l'eleve.
    entrees = [e for e in entrees if not comptes_rendus_service.est_compte_rendu(e)]
    derniere_saisie = max((e.get("last_edited_time") or "" for e in entrees), default="") or None
    carnet = next(
        (e for e in entrees if prospects_service.NOM_CARNET in str(ns._prop_value(ns._prop(e.get("properties", {}), "Nom")) or "")),
        None,
    )
    a_relire = [e for e in entrees if ns._prop_value(ns._prop(e.get("properties", {}), "Retour IA statut")) == "À relire"]
    retours_a_relire = len(a_relire)

    try:
        connexion = _derniere_connexion(email)
    except RuntimeError as error:
        logger.warning("Dernière connexion illisible (%s)", ns._resume_erreur(error))
        connexion = None

    prospects = prospects_service._contenu(carnet)["prospects"] if carnet else []

    return {
        "client_page_id": client_id,
        "nom": ns.client_display_name(row),
        "etat": ns._prop_value(ns._prop(props, "État")),
        "parcours": ns._nom_parcours(parcours),
        "jour": ns._jour_parcours(debut),
        "duree": 28 if atelier else 90,
        "objectif_90j": ns._prop_value(ns._prop(props, "Objectif 90j")),
        "fiches_terminees": sum(1 for e in etats if e == "Terminé"),
        "fiches_en_cours": sum(1 for e in etats if e == "En cours"),
        "fiches_total": len(etats),
        "derniere_saisie": derniere_saisie,
        "jours_sans_saisie": _jours_depuis(derniere_saisie, maintenant),
        "derniere_connexion": connexion,
        "nb_saisies": len(entrees),
        "nb_prospects": len(prospects),
        "prospects_par_statut": {
            s: sum(1 for p in prospects if p.get("statut") == s) for s in prospects_service.STATUTS
        },
        "retours_ia_a_relire": retours_a_relire,
        "fiches_a_relire": sorted({f for f in (ns._relation_id(e.get("properties", {}), "Fiche Client") for e in a_relire) if f}),
        "derniere_relance": ns._prop_value(ns._prop(props, "Dernière relance")),
        "nb_relances": ns._prop_value(ns._prop(props, "Nb relances")) or 0,
    }


def liste(maintenant: datetime | None = None) -> list[dict]:
    maintenant = maintenant or datetime.now(timezone.utc)
    rows = [
        row for row in ns._query_data_source(ns.CLIENTS_DATA_SOURCE_ID)
        if ns._prop_value(ns._prop(row.get("properties", {}), "État")) not in _ETATS_ARCHIVES
    ]

    def _sans_echec(row):
        try:
            return _ligne_eleve(row, maintenant)
        except Exception as error:
            # Un élève illisible ne doit pas vider tout l'onglet.
            logger.warning("Élève %s illisible (%s)", row.get("id"), ns._resume_erreur(error))
            return {
                "client_page_id": row["id"],
                "nom": ns.client_display_name(row),
                "etat": ns._prop_value(ns._prop(row.get("properties", {}), "État")),
                "illisible": True,
            }

    eleves = list(_POOL_ELEVES.map(_sans_echec, rows))
    # Les élèves en cours d'abord, puis les plus inactifs en haut.
    eleves.sort(key=lambda e: (
        e.get("etat") != "En cours",
        -(e.get("jours_sans_saisie") if e.get("jours_sans_saisie") is not None else 10_000),
        e.get("nom") or "",
    ))
    return eleves


def _signe_par_coach(entree: dict) -> bool:
    # Derniere modification = Rony qui valide le retour : pas une saisie de l'eleve.
    valide_le = ns._prop_value(ns._prop(entree.get("properties", {}), "Retour validé le"))

    try:
        ecart = abs(
            datetime.fromisoformat(str(entree.get("last_edited_time")).replace("Z", "+00:00"))
            - datetime.fromisoformat(str(valide_le).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return False

    return ecart <= timedelta(minutes=3)


def activite(jours: int = 30, maintenant: datetime | None = None) -> dict[str, str]:
    """Derniere saisie de chaque eleve (fiche, bilan, carnet de prospects) sur
    les `jours` derniers jours : badge « nouveau » de l'Espace Coach. Une seule
    requete Notion, les 100 entrees les plus recentes."""
    maintenant = maintenant or datetime.now(timezone.utc)
    depuis = (maintenant - timedelta(days=jours)).isoformat()
    entrees = ns._query_data_source(
        ns.ENTREES_PORTAIL_DATA_SOURCE_ID,
        filter_={"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": depuis}},
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
    )
    dernieres = {}

    for entree in entrees:
        if comptes_rendus_service.est_compte_rendu(entree) or _signe_par_coach(entree):
            continue

        for lien in (entree.get("properties", {}).get("Client") or {}).get("relation") or []:
            quand = entree.get("last_edited_time") or ""

            if quand > dernieres.get(lien["id"], ""):
                dernieres[lien["id"]] = quand

    return dernieres


def calendrier() -> list[dict]:
    """Eleves en cours, avec juste ce qu'il faut pour le rythme des points
    (une seule requete Notion, sans lire leurs fiches)."""
    eleves = []

    for row in ns._query_data_source(ns.CLIENTS_DATA_SOURCE_ID):
        props = row.get("properties", {})

        if ns._prop_value(ns._prop(props, "État")) != "En cours":
            continue

        debut = ns._prop_value(ns._prop(props, "Date de demarrage")) or ns._prop_value(ns._prop(props, "Date de démarrage"))
        eleves.append({
            "client_page_id": row["id"],
            "nom": ns.client_display_name(row),
            "parcours": ns._nom_parcours(ns._prop_value(ns._prop(props, "Parcours"))),
            "date_demarrage": str(debut)[:10] if debut else None,
            "jour": ns._jour_parcours(debut),
        })

    eleves.sort(key=lambda e: e["nom"] or "")
    return eleves


def detail(client_page_id: str, frais: bool = False) -> dict:
    if frais:
        ns._cache_clear(f"dashboard:{client_page_id}")
        ns._cache_clear(f"carnet:{client_page_id}")
        ns._cache_clear(f"comptes_rendus:{client_page_id}")

    dashboard = ns.get_client_dashboard(client_page_id)
    carnet = prospects_service.vue_client(prospects_service.lire(client_page_id, dashboard))
    fiche_bilan = next((f for f in dashboard.get("fiches", []) if f.get("master_id") == ns._BILAN_HEBDO_MASTER_ID), None)
    bilans = []

    if fiche_bilan:
        try:
            bilans = ns._historique_bilans(fiche_bilan["id"])
        except RuntimeError as error:
            logger.warning("Bilans illisibles (%s)", ns._resume_erreur(error))

    comptes_rendus = []

    if not ns._est_parcours_autonome(dashboard.get("parcours")):
        try:
            comptes_rendus = comptes_rendus_service.lister(client_page_id)
        except RuntimeError as error:
            logger.warning("Comptes rendus illisibles (%s)", ns._resume_erreur(error))

    return {
        "client_page_id": client_page_id,
        "dashboard": dashboard,
        "carnet": carnet,
        "bilans": bilans,
        "comptes_rendus": comptes_rendus,
    }
