# Bibliotheque de modeles (lot 4, decision de Rony du 25/10/2026) : deux couches.
# 1. Une base par metier : scripts, messages, trames tires du contenu de Rony
#    (scripts de prospection terrain, kit WhatsApp Antilles, templates module 4).
# 2. Une couche personnalisee : chaque modele est pre-rempli avec les mots du
#    client (sa cible, son resultat, son probleme) tires de ses fiches 9, 10 et 12,
#    et Idris peut reecrire un modele entier a partir de toutes ses fiches.
# La liste des metiers et les valeurs par defaut sont a valider avec Rony.

import re

from backend.services import ia_service, notion_service
from backend.services import idris_service

_N = notion_service._NUMERO_TO_MASTER_ID

METIERS = {
    "btp": {
        "libelle": "Artisan du bâtiment",
        "mots": ["btp", "bâtiment", "batiment", "maçon", "macon", "plomb", "électric", "electric", "menuis", "peint", "carrel", "charpent", "couvreur", "rénovation", "renovation", "climatisation", "artisan"],
        "cible": "les propriétaires qui veulent rénover ou agrandir",
        "resultat": "réaliser leurs travaux dans les délais",
        "probleme": "les chantiers qui traînent et les devis flous",
    },
    "beaute": {
        "libelle": "Beauté et bien-être",
        "mots": ["beauté", "beaute", "coiff", "esthéti", "estheti", "ongle", "massage", "spa", "bien-être", "bien etre", "maquill", "onglerie", "barb"],
        "cible": "les femmes actives qui veulent prendre soin d'elles",
        "resultat": "prendre un vrai moment pour elles",
        "probleme": "les rendez-vous impossibles à caler",
    },
    "restauration": {
        "libelle": "Restauration et traiteur",
        "mots": ["restau", "traiteur", "cuisin", "food", "snack", "boulang", "pâtiss", "patiss", "bar ", "chef"],
        "cible": "les entreprises et les familles qui organisent un repas",
        "resultat": "réussir leurs repas et leurs événements",
        "probleme": "le stress de l'organisation",
    },
    "tourisme": {
        "libelle": "Tourisme et loisirs",
        "mots": ["touris", "location", "gîte", "gite", "excursion", "plongée", "plongee", "loisir", "hébergement", "hebergement", "guide"],
        "cible": "les visiteurs et les locaux qui cherchent une sortie",
        "resultat": "vivre une expérience authentique",
        "probleme": "les activités trop touristiques",
    },
    "commerce": {
        "libelle": "Commerce et boutique",
        "mots": ["commerce", "boutique", "magasin", "vente de", "épicerie", "epicerie", "e-commerce", "prêt-à-porter", "pret-a-porter"],
        "cible": "les clients de ton secteur",
        "resultat": "trouver le bon produit près de chez eux",
        "probleme": "les commandes en ligne qui mettent des semaines",
    },
    "conseil": {
        "libelle": "Conseil, formation, coaching",
        "mots": ["conseil", "consult", "coach", "formation", "formateur", "accompagnement", "expert", "comptab", "assurance", "immobili", "digital", "marketing", "informatique", "freelance"],
        "cible": "les dirigeants de TPE",
        "resultat": "prendre des décisions plus claires",
        "probleme": "la solitude du dirigeant",
    },
    "services": {
        "libelle": "Services aux particuliers",
        "mots": ["service", "ménage", "menage", "jardin", "garde", "aide à domicile", "transport", "taxi", "nettoyage", "dépannage", "depannage", "photograph", "événement", "evenement"],
        "cible": "les familles et les particuliers débordés",
        "resultat": "libérer du temps",
        "probleme": "les tâches qui s'accumulent",
    },
}
METIER_PAR_DEFAUT = "services"

CATEGORIES = ["Premier contact", "Relance", "Rendez-vous", "Proposition", "Recommandation"]

# {cible}, {resultat}, {probleme} : remplis par les mots du client, sinon par
# le metier. {prenom} : le prenom du client. [Prénom] : son destinataire.
MODELES = [
    {
        "id": "whatsapp_froid",
        "categorie": "Premier contact",
        "canal": "WhatsApp",
        "titre": "Premier message à un prospect",
        "texte": "Bonjour [Prénom] 👋\nJe suis {prenom}. J'aide {cible} à {resultat}, sans {probleme}.\nEst-ce que c'est un sujet qui vous parle ? On peut en discuter 15 minutes cette semaine ?",
    },
    {
        "id": "apres_evenement",
        "categorie": "Premier contact",
        "canal": "WhatsApp",
        "titre": "Après une rencontre (salon, réseau)",
        "texte": "Bonjour [Prénom],\nRavi d'avoir échangé avec vous à [événement] ! Beaucoup de personnes comme vous me disent que {probleme}, c'est pesant.\nJ'aide {cible} à {resultat}. Ça vous parle ? Si oui, on peut en discuter 10 minutes la semaine prochaine.",
    },
    {
        "id": "terrain_approche",
        "categorie": "Premier contact",
        "canal": "Terrain",
        "titre": "Phrase d'approche en événement",
        "texte": "Bonjour, je m'appelle {prenom}.\nJ'aide {cible} à {resultat}, sans {probleme}.\nEst-ce que c'est un sujet qui vous parle ?",
    },
    {
        "id": "telephone_ouverture",
        "categorie": "Premier contact",
        "canal": "Téléphone",
        "titre": "Ouverture d'un appel",
        "texte": "Bonjour [Prénom], je m'appelle {prenom}.\nJ'aide {cible} à {resultat}.\nAujourd'hui, pour vous, la priorité c'est plutôt :\n1. régler un souci comme {probleme} ?\n2. gagner du temps ?\n3. maîtriser votre budget ?\nJe vous propose un échange de 15 minutes pour voir si je peux vous aider.",
    },
    {
        "id": "relance_j3",
        "categorie": "Relance",
        "canal": "WhatsApp",
        "titre": "Relance à J+3",
        "texte": "Bonjour [Prénom],\nJe reviens vers vous rapidement, car je sais que {probleme} peut vraiment peser au quotidien.\nEst-ce que 15 minutes cette semaine pour en parler vous iraient ?",
    },
    {
        "id": "relance_j7",
        "categorie": "Relance",
        "canal": "WhatsApp",
        "titre": "Dernière relance à J+7",
        "texte": "Bonjour [Prénom],\nDernier message de ma part, promis !\nSi le sujet vous intéresse un jour, je reste disponible. Il suffit de me répondre « OUI » et je vous rappelle.\nBelle journée !",
    },
    {
        "id": "confirmation_rdv",
        "categorie": "Rendez-vous",
        "canal": "WhatsApp",
        "titre": "Confirmation de rendez-vous",
        "texte": "Bonjour [Prénom],\nJe vous confirme notre rendez-vous [jour] à [heure], [lieu ou lien].\nPour qu'il vous soit vraiment utile, notez ce que vous aimeriez régler en priorité.\nÀ très vite, {prenom}",
    },
    {
        "id": "trame_decouverte",
        "categorie": "Rendez-vous",
        "canal": "Rendez-vous",
        "titre": "Trame de rendez-vous découverte",
        "texte": "1. Accueil : « Merci pour votre temps. Je vous propose de commencer par vous écouter, puis je vous dirai si et comment je peux vous aider. »\n2. Situation : « Aujourd'hui, comment ça se passe pour vous ? Qu'est-ce qui vous freine le plus ? »\n3. Impact : « Qu'est-ce que ça vous coûte, en temps, en argent ou en énergie ? »\n4. Objectif : « Si on se revoit dans 3 mois et que tout s'est bien passé, qu'est-ce qui aura changé ? »\n5. Reformulation : « Si je résume, ce qui vous pèse le plus aujourd'hui, c'est… C'est bien ça ? »\n6. Proposition : présenter votre offre en une phrase, puis le prix, puis se taire.\n7. Prochaine étape : fixer une date précise, ensemble.",
    },
    {
        "id": "relance_devis",
        "categorie": "Proposition",
        "canal": "WhatsApp",
        "titre": "Relance après un devis",
        "texte": "Bonjour [Prénom],\nJe reviens vers vous au sujet de la proposition envoyée le [date].\nPour rappel, j'aide {cible} à {resultat}. Avez-vous des questions, ou un point à ajuster ensemble ?\nJe peux vous appeler 10 minutes [jour] si c'est plus simple.",
    },
    {
        "id": "demande_recommandation",
        "categorie": "Recommandation",
        "canal": "WhatsApp",
        "titre": "Demande de recommandation",
        "texte": "Bonjour [Prénom],\nMerci encore pour votre confiance, ça me fait vraiment plaisir que vous soyez satisfait(e).\nJ'ai une petite question : connaissez-vous une ou deux personnes parmi {cible} à qui je pourrais être utile ?\nSi oui, je vous laisse leur transmettre mon numéro, ou me donner le leur avec leur accord.",
    },
    {
        "id": "demande_avis_google",
        "categorie": "Recommandation",
        "canal": "WhatsApp",
        "titre": "Demande d'avis Google",
        "texte": "Bonjour [Prénom],\nVotre avis compte beaucoup pour moi et aide d'autres personnes à me faire confiance.\nAccepteriez-vous de laisser quelques mots sur ma fiche Google ? Voici le lien : [lien]\nÇa prend une minute. Merci d'avance !",
    },
]

_LONGUEUR_MAX_VALEUR = 120
_POSITIONNEMENT = re.compile(r"j['’]aide\s+(.+?)\s+à\s+(.+?)(?:\s+sans\s+(.+?))?(?:\s+grâce\s+à.*)?[.!]?$", re.IGNORECASE | re.DOTALL)

_SYSTEME_PERSONNALISER = """Tu es Idris, l'assistant IA du programme eVolution 2.0 (RL-eVolution). Tu adaptes un modèle de message commercial à un indépendant ou une TPE des Antilles-Guyane, à partir de SES fiches (offre, cible, positionnement, script).
Garde la structure, la longueur et l'intention du modèle. Remplace les formulations génériques par SES mots, SA cible et SON résultat. Vouvoiement pour le destinataire, ton simple, humain et chaleureux, sans jargon. N'invente aucun chiffre, aucun client, aucune référence. Laisse tels quels les champs entre crochets ([Prénom], [date], [jour], [lien]...).
Réponds uniquement avec le texte du message, sans guillemets, sans titre, sans commentaire."""


def detecter_metier(identite: dict | None) -> str:
    texte = " ".join(str((identite or {}).get(c) or "") for c in ("secteur", "activite", "offre_principale")).lower()

    if texte.strip():
        for cle, metier in METIERS.items():
            if any(mot in texte for mot in metier["mots"]):
                return cle

    return METIER_PAR_DEFAUT


def _court(valeur) -> str | None:
    texte = " ".join(str(valeur or "").split()).strip(" .")

    if not texte or len(texte) > _LONGUEUR_MAX_VALEUR:
        return None

    return texte[0].lower() + texte[1:] if texte[:2] != texte[:2].upper() else texte


def mots_du_client(client_page_id: str, dashboard: dict) -> dict:
    """Ce que les fiches du client disent de sa cible, de son resultat et du
    probleme qu'il resout. Seules les reponses courtes sont reprises telles quelles."""
    sources = [_N["9"], _N["10"], _N["11"]]

    try:
        fiches = notion_service.reponses_des_fiches(client_page_id, dashboard.get("fiches") or [], sources)
    except Exception:
        return {}

    par_cle = {}

    for master_id in sources:
        schema = notion_service.FICHE_SCHEMAS.get(master_id) or {}

        for champ in schema.get("champs", []):
            par_cle[champ["libelle"]] = champ["cle"]

    reponses = {par_cle.get(libelle, libelle): valeur for fiche in fiches for libelle, valeur in fiche["reponses"]}
    mots = {}
    phrase = _POSITIONNEMENT.match(" ".join(str(reponses.get("phrase_positionnement_officielle") or "").split()))

    if phrase:
        for cle, valeur in zip(("cible", "resultat", "probleme"), phrase.groups()):
            if _court(valeur):
                mots[cle] = _court(valeur)

    # Le resultat ne vient que de la phrase de positionnement (« à [verbe]... »).
    for cle, source in (("probleme", "probleme_resolu"), ("cible", "portrait_client_ideal")):
        if cle not in mots and _court(reponses.get(source)):
            mots[cle] = _court(reponses.get(source))

    return mots


def _remplir(texte: str, valeurs: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: valeurs.get(m.group(1), m.group(0)), texte)


def bibliotheque(client_page_id: str, dashboard: dict, metier: str | None = None) -> dict:
    detecte = detecter_metier(dashboard.get("identite"))
    choisi = metier if metier in METIERS else detecte
    mots = mots_du_client(client_page_id, dashboard)
    base = METIERS[choisi]
    prenom = (dashboard.get("nom") or "").split(" ")[0] or "[ton prénom]"
    valeurs = {"cible": base["cible"], "resultat": base["resultat"], "probleme": base["probleme"], **mots, "prenom": prenom}

    return {
        "metier": choisi,
        "metier_detecte": detecte,
        "metiers": [{"id": cle, "libelle": m["libelle"]} for cle, m in METIERS.items()],
        "categories": CATEGORIES,
        "personnalise_avec": sorted(mots),
        "personnalisation_ia": ia_service.enabled(),
        "modeles": [{**{k: m[k] for k in ("id", "categorie", "canal", "titre")}, "texte": _remplir(m["texte"], valeurs)} for m in MODELES],
    }


def personnaliser(client_page_id: str, dashboard: dict, modele_id: str, metier: str | None = None) -> dict:
    """Idris reecrit un modele avec les mots du client. Leve ValueError
    (modele inconnu), PermissionError (limite du jour)."""
    modeles = {m["id"]: m for m in bibliotheque(client_page_id, dashboard, metier)["modeles"]}

    if modele_id not in modeles:
        raise ValueError("Modèle inconnu")

    if not idris_service._quota_jour_ok(f"m:{client_page_id}", idris_service._MAX_REDACTIONS_JOUR):
        raise PermissionError("Limite du jour atteinte")

    modele = modeles[modele_id]
    demande = (
        idris_service._contexte(client_page_id, dashboard, avec_chiffres=False)
        + f"\n\nModèle à adapter ({modele['titre']}, {modele['canal']}) :\n{modele['texte']}"
    )
    texte = ia_service.generer(_SYSTEME_PERSONNALISER, [{"role": "user", "texte": demande}], temperature=0.6, max_tokens=600).strip()

    if not texte:
        raise RuntimeError("Modèle IA vide")

    return {"texte": texte}
