"""Schémas de formulaires pour le portail client eVolution 2.0.

Ce module décrit, pour chaque fiche de la base Notion "[DB] Fiches Master",
la liste des champs que le client doit remplir dans le portail web, en
remplacement de la saisie de texte libre directement dans Notion.

Clé du dictionnaire FICHE_SCHEMAS : l'ID de la page Notion SANS tirets.
mode :
    - "unique"    -> la fiche correspond à la propriété Notion "Réponse unique"
                     (le client répond une seule fois ; diagnostics, positionnement,
                     vision, etc.)
    - "recurrent" -> la fiche correspond à la propriété Notion "Suivi récurrent"
                     (tableau ou bilan qui s'alimente dans la durée ; les "champs"
                     décrivent alors les colonnes d'UNE ligne/entrée soumise par
                     le client, à stocker dans "[DB] Entrées Portail").

Types de champ autorisés : "texte", "nombre", "date", "choix" (+ clé "options").

Notes de classification générales :
- Les fiches purement informatives (0. BIENVENUE, 18. TRAME D'ENTRETIEN DE VENTE,
  15... voir au cas par cas) ont été classées "Réponse unique" par défaut avec une
  liste de champs vide ou réduite, comme autorisé par la consigne, car il n'y a pas
  de saisie répétée dans le temps à modéliser.
- Les checklists (cases à cocher) sont modélisées comme des champs de type "choix"
  representant un booléen (options ["Oui", "Non"]), un par item de checklist.
- Pour les fiches "Suivi récurrent" à base de tableau, les champs = colonnes du
  tableau tel que vu dans Notion. Quand un identifiant temporel (ex: semaine)
  n'était pas explicitement une colonne mais est nécessaire pour distinguer les
  entrées dans le temps, un champ raisonnable a été ajouté et annoté en commentaire.
"""

FICHE_SCHEMAS = {
    # 0. BIENVENUE DANS VOTRE ESPACE EVOLUTION 2.0
    # Page purement informative (mode d'emploi du portail). Aucune question posée
    # au client -> liste de champs vide.
    "39ffaffd87588016a405da4d8a0582d4": {
        "nom": "0. BIENVENUE DANS VOTRE ESPACE EVOLUTION 2.0",
        "mode": "unique",
        "champs": [],
    },

    # 1. MON POINT DE DÉPART
    "39ffaffd8758809e9807c4c5e5504352": {
        "nom": "1. MON POINT DE DÉPART",
        "mode": "unique",
        "champs": [
            {"cle": "activite", "libelle": "Votre activité / Votre métier", "type": "texte", "ordre": 1},
            {"cle": "anciennete", "libelle": "Depuis combien de temps êtes-vous lancé ?", "type": "texte", "ordre": 2},
            {"cle": "offre_prix", "libelle": "Que vendez-vous aujourd'hui et à quel prix ?", "type": "texte", "ordre": 3},
            {"cle": "clients_actuels", "libelle": "Qui sont vos clients actuels ?", "type": "texte", "ordre": 4},
            {"cle": "frein_principal", "libelle": "Quel est votre principal frein ou blocage aujourd'hui ?", "type": "texte", "ordre": 5},
            {"cle": "objectif_90j", "libelle": "Quel est votre objectif chiffré ou personnel pour les 90 prochains jours ?", "type": "nombre", "ordre": 6},
        ],
    },

    # 2. CHECKLIST DE DÉMARRAGE
    # Checklist de lecture/préparation -> chaque item modélisé en champ "choix" bool.
    # Le dépôt de documents (drag & drop) n'est pas modélisé ici : pas de type
    # "fichier" prévu dans le schéma, à gérer via un mécanisme d'upload séparé.
    "39ffaffd875880a6aad2f438e54855dd": {
        "nom": "2. CHECKLIST DE DÉMARRAGE",
        "mode": "unique",
        "champs": [
            {"cle": "fiche_point_depart_complete", "libelle": "J'ai complété la fiche \"Mon point de départ\"", "type": "choix", "options": ["Oui", "Non"], "ordre": 1},
            {"cle": "rdv_coaching_planifie", "libelle": "Notre premier rendez-vous de coaching est planifié et confirmé dans mon agenda", "type": "choix", "options": ["Oui", "Non"], "ordre": 2},
            {"cle": "documents_deposes", "libelle": "J'ai déposé mes documents existants (plaquette, tarifs, ancienne page de vente, etc.)", "type": "choix", "options": ["Oui", "Non"], "ordre": 3},
        ],
    },

    # 3. DIAGNOSTIC : ZONE 1 — L'OFFRE
    "39ffaffd87588001824bdaf6c91b3632": {
        "nom": "3. DIAGNOSTIC : ZONE 1 — L'OFFRE",
        "mode": "unique",
        "champs": [
            {"cle": "offre_repond_probleme_urgent", "libelle": "Mon offre actuelle répond à un problème précis et urgent pour mon client", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 1},
            {"cle": "tarifs_coherents_valeur", "libelle": "Mes tarifs sont cohérents avec la valeur que j'apporte et le temps que j'y passe", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 2},
            {"cle": "offre_distincte_concurrence", "libelle": "Mon offre se distingue clairement de la concurrence sur mon marché", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 3},
            {"cle": "changement_offre_prioritaire", "libelle": "Si vous deviez changer une seule chose dans votre offre aujourd'hui, ce serait quoi ?", "type": "texte", "ordre": 4},
        ],
    },

    # 4. DIAGNOSTIC : ZONE 2 — LA VISIBILITÉ
    "39ffaffd8758802d93c6e790f165b53e": {
        "nom": "4. DIAGNOSTIC : ZONE 2 — LA VISIBILITÉ",
        "mode": "unique",
        "champs": [
            {"cle": "offre_comprehensible_immediatement", "libelle": "Mes prospects comprennent immédiatement ce que je vends dès qu'ils voient mes profils (LinkedIn, WhatsApp Business, Site)", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 1},
            {"cle": "publie_contenu_regulier", "libelle": "Je publie ou je communique régulièrement du contenu qui démontre mon expertise", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 2},
            {"cle": "recoit_demandes_spontanees", "libelle": "Je reçois régulièrement des demandes de contact de manière spontanée (bouche-à-oreille ou réseau)", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 3},
            {"cle": "ou_clients_vous_trouvent", "libelle": "Où vos clients actuels vous trouvent-ils le plus souvent aujourd'hui ?", "type": "texte", "ordre": 4},
        ],
    },

    # 5. DIAGNOSTIC : ZONE 3 — LA PROSPECTION
    "39ffaffd87588048a076e678e9b24230": {
        "nom": "5. DIAGNOSTIC : ZONE 3 — LA PROSPECTION",
        "mode": "unique",
        "champs": [
            {"cle": "routine_prospection_reguliere", "libelle": "J'ai une routine de prospection régulière (ex: tous les jours ou toutes les semaines)", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 1},
            {"cle": "liste_prospects_a_jour", "libelle": "Je sais exactement qui contacter et j'ai une liste de prospects à jour", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 2},
            {"cle": "aise_contact_inconnu", "libelle": "Je me sens à l'aise au moment de contacter un inconnu (WhatsApp, LinkedIn, Téléphone)", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 3},
            {"cle": "blocage_principal_prospection", "libelle": "Quel est votre plus grand blocage au moment de prospecter ? (Peur du rejet, manque de temps, ne pas savoir quoi dire...)", "type": "texte", "ordre": 4},
        ],
    },

    # 6. DIAGNOSTIC : ZONE 4 — LA CONVERSION
    "39ffaffd875880abae31d7fd1f7a1c99": {
        "nom": "6. DIAGNOSTIC : ZONE 4 — LA CONVERSION",
        "mode": "unique",
        "champs": [
            {"cle": "trame_claire_rdv_commerciaux", "libelle": "J'ai une trame claire et structurée que je suis durant mes rendez-vous commerciaux", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 1},
            {"cle": "sait_repondre_objections", "libelle": "Je sais comment répondre aux objections courantes (ex: \"C'est trop cher\")", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 2},
            {"cle": "propose_offre_claire_ferme", "libelle": "Je formule une proposition claire et ferme à la fin de chaque rendez-vous", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 3},
            {"cle": "taux_signature_sur_10_rdv", "libelle": "Sur 10 rendez-vous commerciaux réalisés, combien de clients signez-vous en moyenne aujourd'hui ?", "type": "nombre", "ordre": 4},
        ],
    },

    # 7. DIAGNOSTIC : ZONE 5 — LE SUIVI COMMERCIAL
    # NB : le contenu fetché s'arrête après les 3 questions "Oui/Plutôt/Non", sans
    # section "MON RESSENTI" contrairement aux autres zones de diagnostic (1 à 4).
    # Contenu potentiellement tronqué par l'outil fetch (page marquée "truncated").
    # A vérifier manuellement dans Notion si une question ouverte existe en plus.
    "39ffaffd87588086b588e7a82738c7b1": {
        "nom": "7. DIAGNOSTIC : ZONE 5 — LE SUIVI COMMERCIAL",
        "mode": "unique",
        "champs": [
            {"cle": "relance_prospects_en_reflexion", "libelle": "Je relance systématiquement les prospects qui m'ont dit \"Je vais réfléchir\"", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 1},
            {"cle": "suit_chiffres_vente_chaque_semaine", "libelle": "Je note et je suis mes chiffres de vente chaque semaine", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 2},
            {"cle": "connait_ca_previsionnel_30j", "libelle": "Je connais mon chiffre d'affaires prévisionnel pour les 30 prochains jours", "type": "choix", "options": ["Oui", "Plutôt", "Non"], "ordre": 3},
        ],
    },

    # 8. MON RÉSULTAT DE DIAGNOSTIC
    "39ffaffd87588015a47febbf572e6f62": {
        "nom": "8. MON RÉSULTAT DE DIAGNOSTIC",
        "mode": "unique",
        "champs": [
            {"cle": "score_offre", "libelle": "Score d'Offre (/3)", "type": "nombre", "ordre": 1},
            {"cle": "score_visibilite", "libelle": "Score de Visibilité (/3)", "type": "nombre", "ordre": 2},
            {"cle": "score_prospection", "libelle": "Score de Prospection (/3)", "type": "nombre", "ordre": 3},
            {"cle": "score_conversion", "libelle": "Score de Conversion (/3)", "type": "nombre", "ordre": 4},
            {"cle": "score_suivi", "libelle": "Score de Suivi (/3)", "type": "nombre", "ordre": 5},
            {"cle": "score_total", "libelle": "SCORE TOTAL (/15)", "type": "nombre", "ordre": 6},
            {"cle": "priorite_1", "libelle": "Priorité 1 pour les 90 jours", "type": "texte", "ordre": 7},
            {"cle": "priorite_2", "libelle": "Priorité 2 pour les 90 jours", "type": "texte", "ordre": 8},
            {"cle": "priorite_3", "libelle": "Priorité 3 pour les 90 jours", "type": "texte", "ordre": 9},
        ],
    },

    # 9. MON OFFRE ACTUELLE
    "39ffaffd8758805ebebfd5f5c3914a56": {
        "nom": "9. MON OFFRE ACTUELLE",
        "mode": "unique",
        "champs": [
            {"cle": "nom_offre", "libelle": "Quel est le nom de votre offre ou service principal ?", "type": "texte", "ordre": 1},
            {"cle": "tarif_format_offre", "libelle": "Quel est son tarif et son format ? (ex: accompagnement de 3 mois, forfait, taux horaire...)", "type": "texte", "ordre": 2},
            {"cle": "probleme_resolu", "libelle": "Quel est le problème urgent et douloureux que vous résolvez pour votre client ?", "type": "texte", "ordre": 3},
            {"cle": "resultat_concret_client", "libelle": "Quel est le résultat concret et mesurable que votre client obtient grâce à vous ?", "type": "texte", "ordre": 4},
        ],
    },

    # 10. MA CIBLE PRIORITAIRE
    "39ffaffd875880deb56ce1395ae32687": {
        "nom": "10. MA CIBLE PRIORITAIRE",
        "mode": "unique",
        "champs": [
            {"cle": "portrait_client_ideal", "libelle": "Qui est-il précisément ? (Secteur d'activité, taille d'entreprise, rôle de votre interlocuteur...)", "type": "texte", "ordre": 1},
            {"cle": "frustration_principale_client", "libelle": "Quelle est sa plus grande frustration au quotidien ?", "type": "texte", "ordre": 2},
            {"cle": "urgence_probleme_maintenant", "libelle": "Pourquoi a-t-il besoin de résoudre ce problème maintenant (urgence) ?", "type": "texte", "ordre": 3},
            {"cle": "budget_disponible", "libelle": "Dispose-t-il du budget nécessaire pour s'offrir vos services ?", "type": "choix", "options": ["Oui", "Probablement", "Non (À retravailler avec le coach)"], "ordre": 4},
        ],
    },

    # 11. MA PHRASE DE POSITIONNEMENT
    "39ffaffd875880f980a9f99a718d4141": {
        "nom": "11. MA PHRASE DE POSITIONNEMENT",
        "mode": "unique",
        "champs": [
            {"cle": "phrase_positionnement_officielle", "libelle": "Ma phrase officielle (J'aide [cible] à obtenir [résultat] sans [frustration] grâce à [méthode])", "type": "texte", "ordre": 1},
            {"cle": "presentation_flash_orale", "libelle": "Ma présentation flash (orale - 10 secondes)", "type": "texte", "ordre": 2},
            {"cle": "bio_profil_ecrite", "libelle": "Ma bio de profil (écrite - LinkedIn, WhatsApp, Site)", "type": "texte", "ordre": 3},
        ],
    },

    # 12. VALIDATION TERRAIN DE MON POSITIONNEMENT
    "39ffaffd875880d7bf80c72c865a88b2": {
        "nom": "12. VALIDATION TERRAIN DE MON POSITIONNEMENT",
        "mode": "unique",
        "champs": [
            {"cle": "retour_personne_1", "libelle": "Retour Personne 1 : est-ce clair pour elle ? Qu'a-t-elle compris ?", "type": "texte", "ordre": 1},
            {"cle": "retour_personne_2", "libelle": "Retour Personne 2", "type": "texte", "ordre": 2},
            {"cle": "decision_validation", "libelle": "Décision de validation de la phrase de positionnement", "type": "choix", "options": ["Ma phrase est claire, les gens comprennent immédiatement ce que je vends", "Des ajustements sont nécessaires (à voir lors de la prochaine séance de coaching)"], "ordre": 3},
        ],
    },

    # 13. MON PLAN DE PROSPECTION DE LA SEMAINE
    # Fiche répétée chaque semaine par le client -> Suivi récurrent. Un champ
    # "semaine_du" (date) a été ajouté pour identifier chaque entrée dans le
    # temps ; il n'apparaît pas explicitement comme un champ à remplir dans le
    # contenu Notion mais est nécessaire pour distinguer les soumissions
    # hebdomadaires dans "[DB] Entrées Portail".
    "39ffaffd875880ebbcdde70a29c35269": {
        "nom": "13. MON PLAN DE PROSPECTION DE LA SEMAINE",
        "mode": "recurrent",
        "champs": [
            {"cle": "semaine_du", "libelle": "Semaine du (identifiant de l'entrée)", "type": "date", "ordre": 1},
            {"cle": "nb_prospects_a_contacter", "libelle": "Cette semaine, je vais contacter ... nouveaux prospects", "type": "nombre", "ordre": 2},
            {"cle": "canal_principal", "libelle": "Le canal de contact principal", "type": "choix", "options": ["Téléphone", "WhatsApp", "LinkedIn", "Email", "Physique (terrain)"], "ordre": 3},
            {"cle": "segment_cible_priorite", "libelle": "Le segment ciblé en priorité", "type": "texte", "ordre": 4},
            {"cle": "creneau_prospection", "libelle": "Créneau bloqué dans mon agenda pour prospecter (ex: Mardi et Jeudi de 9h à 11h)", "type": "texte", "ordre": 5},
        ],
    },

    # 14. MON TABLEAU DE PROSPECTION
    "39ffaffd875880f7aee1e8b138416d0a": {
        "nom": "14. MON TABLEAU DE PROSPECTION",
        "mode": "recurrent",
        "champs": [
            {"cle": "date_contact", "libelle": "Date", "type": "date", "ordre": 1},
            {"cle": "nom_prospect", "libelle": "Nom du Prospect", "type": "texte", "ordre": 2},
            {"cle": "canal", "libelle": "Canal", "type": "texte", "ordre": 3},
            {"cle": "statut", "libelle": "Statut", "type": "choix", "options": ["Relance", "RdV", "Non"], "ordre": 4},
            {"cle": "prochaine_action", "libelle": "Prochaine Action", "type": "texte", "ordre": 5},
        ],
    },

    # 15. SCRIPT D'APPROCHE (MODÈLE)
    "39ffaffd875880f9a066e6a7e1dc7d37": {
        "nom": "15. SCRIPT D'APPROCHE (MODÈLE)",
        "mode": "unique",
        "champs": [
            {"cle": "script_personnalise", "libelle": "Mon script personnalisé (adaptez la structure d'accroche / qualification / appel à l'action à votre voix)", "type": "texte", "ordre": 1},
        ],
    },

    # 16. GESTION DES OBJECTIONS
    "39ffaffd8758808c91dfdd277b66fa2a": {
        "nom": "16. GESTION DES OBJECTIONS",
        "mode": "unique",
        "champs": [
            {"cle": "reponse_objection_trop_cher", "libelle": "Objection \"C'est trop cher\" : ma réponse", "type": "texte", "ordre": 1},
            {"cle": "reponse_objection_pas_le_temps", "libelle": "Objection \"Je n'ai pas le temps en ce moment\" : ma réponse", "type": "texte", "ordre": 2},
            {"cle": "reponse_objection_je_vais_reflechir", "libelle": "Objection \"Je vais réfléchir\" : ma réponse", "type": "texte", "ordre": 3},
        ],
    },

    # 17. BILAN HEBDOMADAIRE : PROSPECTION
    # Bilan rempli chaque vendredi -> Suivi récurrent. "semaine_du" ajouté comme
    # identifiant temporel de l'entrée (non listé explicitement comme champ dans
    # le contenu Notion, mais nécessaire pour distinguer les bilans dans le temps).
    "39ffaffd875880708581d60c234aab45": {
        "nom": "17. BILAN HEBDOMADAIRE : PROSPECTION",
        "mode": "recurrent",
        "champs": [
            {"cle": "semaine_du", "libelle": "Semaine du (identifiant de l'entrée)", "type": "date", "ordre": 1},
            {"cle": "nb_contacts_tentes", "libelle": "Nombre de contacts tentés", "type": "nombre", "ordre": 2},
            {"cle": "nb_rdv_obtenus", "libelle": "Nombre de rendez-vous obtenus", "type": "nombre", "ordre": 3},
            {"cle": "nb_propositions_envoyees", "libelle": "Nombre de propositions envoyées", "type": "nombre", "ordre": 4},
            {"cle": "nb_ventes_conclues", "libelle": "Nombre de ventes conclues", "type": "nombre", "ordre": 5},
            {"cle": "ce_qui_a_le_mieux_fonctionne", "libelle": "Qu'est-ce qui a le mieux fonctionné cette semaine ?", "type": "texte", "ordre": 6},
            {"cle": "difficulte_principale", "libelle": "Quelle est la difficulté principale rencontrée ?", "type": "texte", "ordre": 7},
            {"cle": "objectif_semaine_prochaine", "libelle": "Mon objectif pour la semaine prochaine (en termes d'actions)", "type": "texte", "ordre": 8},
        ],
    },

    # 18. TRAME D'ENTRETIEN DE VENTE
    # Page informative (structure en 4 phases), aucun champ de saisie libre
    # identifié dans le contenu -> liste de champs vide.
    "39ffaffd87588001b983e13aa1a06cda": {
        "nom": "18. TRAME D'ENTRETIEN DE VENTE",
        "mode": "unique",
        "champs": [],
    },

    # 19. TABLEAU DE SUIVI DE CLOSING
    # Table de suivi de propositions commerciales -> Suivi récurrent (une entrée
    # par proposition/prospect). Le contenu Notion mentionne "Statut
    # (Gagné/Perdu)" ; l'option "En cours" a été ajoutée pour couvrir l'état
    # transitoire d'une proposition envoyée mais pas encore décidée (non présente
    # littéralement dans le contenu source, ajoutée par jugement pratique).
    "39ffaffd8758805398f7dc22d26b9626": {
        "nom": "19. TABLEAU DE SUIVI DE CLOSING",
        "mode": "recurrent",
        "champs": [
            {"cle": "nom_prospect", "libelle": "Nom du Prospect", "type": "texte", "ordre": 1},
            {"cle": "montant_offre", "libelle": "Montant Offre", "type": "nombre", "ordre": 2},
            {"cle": "date_envoi", "libelle": "Date Envoi", "type": "date", "ordre": 3},
            {"cle": "relance_prevue", "libelle": "Relance Prévue", "type": "date", "ordre": 4},
            {"cle": "statut", "libelle": "Statut", "type": "choix", "options": ["Gagné", "Perdu", "En cours"], "ordre": 5},
        ],
    },

    # 20. AUTOMATISATION & OUTILS : Gagner en impact
    "39ffaffd875880809b88e03b18dd4be3": {
        "nom": "20. AUTOMATISATION & OUTILS : Gagner en impact",
        "mode": "unique",
        "champs": [
            {"cle": "outils_captation_prospects", "libelle": "Quels outils utilisez-vous pour capter vos prospects ? (Formulaire, réseaux sociaux, site web, téléphone…)", "type": "texte", "ordre": 1},
            {"cle": "actions_deja_automatisees", "libelle": "Quelles actions sont déjà automatisées ? (Accusés de réception, relances, transferts d'informations…)", "type": "texte", "ordre": 2},
            {"cle": "temps_saisie_manuelle_semaine", "libelle": "Saisie manuelle des contacts : temps estimé / semaine", "type": "nombre", "ordre": 3},
            {"cle": "penibilite_saisie_manuelle", "libelle": "Saisie manuelle des contacts : pénibilité (/5)", "type": "nombre", "ordre": 4},
            {"cle": "temps_relances_semaine", "libelle": "Relances prospects / rendez-vous : temps estimé / semaine", "type": "nombre", "ordre": 5},
            {"cle": "penibilite_relances", "libelle": "Relances prospects / rendez-vous : pénibilité (/5)", "type": "nombre", "ordre": 6},
            {"cle": "temps_envoi_documents_semaine", "libelle": "Envoi de documents / devis : temps estimé / semaine", "type": "nombre", "ordre": 7},
            {"cle": "penibilite_envoi_documents", "libelle": "Envoi de documents / devis : pénibilité (/5)", "type": "nombre", "ordre": 8},
            {"cle": "temps_reponses_repetitives_semaine", "libelle": "Réponses répétitives aux mêmes questions : temps estimé / semaine", "type": "nombre", "ordre": 9},
            {"cle": "penibilite_reponses_repetitives", "libelle": "Réponses répétitives aux mêmes questions : pénibilité (/5)", "type": "nombre", "ordre": 10},
            {"cle": "action_prioritaire_1", "libelle": "Action n°1 (première automatisation prioritaire)", "type": "texte", "ordre": 11},
            {"cle": "pourquoi_action_1", "libelle": "Pourquoi l'action n°1 est prioritaire", "type": "texte", "ordre": 12},
            {"cle": "action_prioritaire_2", "libelle": "Action n°2", "type": "texte", "ordre": 13},
            {"cle": "pourquoi_action_2", "libelle": "Pourquoi l'action n°2", "type": "texte", "ordre": 14},
            {"cle": "action_prioritaire_3", "libelle": "Action n°3", "type": "texte", "ordre": 15},
            {"cle": "pourquoi_action_3", "libelle": "Pourquoi l'action n°3", "type": "texte", "ordre": 16},
            {"cle": "a_identifie_perte_de_temps", "libelle": "J'ai identifié ma principale perte de temps", "type": "choix", "options": ["Oui", "Non"], "ordre": 17},
            {"cle": "a_defini_priorite_semaine", "libelle": "J'ai défini ma priorité n°1 pour la semaine", "type": "choix", "options": ["Oui", "Non"], "ordre": 18},
            {"cle": "a_liste_outils_actuels", "libelle": "J'ai listé mes outils actuels", "type": "choix", "options": ["Oui", "Non"], "ordre": 19},
        ],
    },

    # 21. MA VISION LONG TERME : eVolution 2.0
    "39ffaffd875880448c4fe3287b893bf1": {
        "nom": "21. MA VISION LONG TERME : eVolution 2.0",
        "mode": "unique",
        "champs": [
            {"cle": "objectif_ca_1an", "libelle": "Objectif financier (Chiffre d'affaires) à horizon 1 an", "type": "texte", "ordre": 1},
            {"cle": "nb_clients_actifs_cible", "libelle": "Nombre de clients actifs visé (eVolution 2.0)", "type": "nombre", "ordre": 2},
            {"cle": "niveau_liberte_operationnelle", "libelle": "Niveau de liberté opérationnelle visé", "type": "texte", "ordre": 3},
            {"cle": "evolution_offre", "libelle": "Comment mon offre va-t-elle évoluer pour mieux servir mes clients ?", "type": "texte", "ordre": 4},
            {"cle": "prochaine_etape_developpement", "libelle": "Quelle est la prochaine étape de développement (nouveau produit, nouveau marché, automatisation poussée) ?", "type": "texte", "ordre": 5},
        ],
    },
}
