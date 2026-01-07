/**
 * LDVELH - Constantes centralisées
 * ============================================================================
 * Ce fichier centralise toutes les constantes du projet pour éviter les
 * duplications et faciliter la maintenance.
 */

// ============================================================================
// MODÈLES CLAUDE
// ============================================================================

export const MODELS = {
	MAIN: 'claude-sonnet-4-5',           // Modèle principal (génération narrative)
	EXTRACTION: 'claude-haiku-4-5',      // Modèle léger (extraction KG)
};

// ============================================================================
// CONFIGURATION API
// ============================================================================

export const API_CONFIG = {
	MAX_TOKENS_INIT: 8192,
	MAX_TOKENS_LIGHT: 4096,
	MAX_TOKENS_EXTRACTION: 1024,
	MAX_TOKENS_RESUME: 256,
	TEMPERATURE: 0.8,
	MAX_RETRIES_EXTRACTION: 1,
};

// ============================================================================
// JAUGES ET STATS VALENTIN
// ============================================================================

export const JAUGES = {
	ENERGIE: { min: 0, max: 5, arrondi: 0.5, defaut: 3 },
	MORAL: { min: 0, max: 5, arrondi: 0.5, defaut: 3 },
	SANTE: { min: 0, max: 5, arrondi: 0.5, defaut: 5 },
	CREDITS: { min: 0, max: Infinity, arrondi: 1, defaut: 1400 },
};

export const STATS_VALENTIN_DEFAUT = {
	energie: JAUGES.ENERGIE.defaut,
	moral: JAUGES.MORAL.defaut,
	sante: JAUGES.SANTE.defaut,
	credits: JAUGES.CREDITS.defaut,
};

// ============================================================================
// ROMANCE
// ============================================================================

export const ROMANCE = {
	AGE_MIN: 25,
	AGE_MAX: 45,
	ETAPES: [
		'Inconnus',
		'Indifférence',
		'Reconnaissance',
		'Sympathie',
		'Curiosité',
		'Intérêt',
		'Attirance',
	],
};

// ============================================================================
// COMPÉTENCES VALENTIN
// ============================================================================

export const COMPETENCES_VALENTIN = {
	// Expertise (4-5)
	informatique: 5,
	systemes: 4,
	recherche: 4,

	// Moyennes (3)
	cuisine: 3,
	bricolage: 3,
	observation: 3,
	culture: 3,
	sang_froid: 3,
	pedagogie: 3,
	physique: 3,
	administration: 3,
	jeux: 3,

	// Faibles (2)
	social: 2,
	discretion: 2,
	negociation: 2,
	empathie: 2,
	art: 2,
	commerce: 2,
	leadership: 2,
	xenologie: 2,

	// Très faibles (1)
	medical: 1,
	pilotage: 1,
	mensonge: 1,
	survie: 1,
	intimidation: 1,
	seduction: 1,
	droit: 1,
	botanique: 1,
};

// ============================================================================
// TYPES D'ENTITÉS
// ============================================================================

export const TYPES_ENTITES = [
	'personnage',
	'lieu',
	'objet',
	'organisation',
	'arc_narratif',
	'ia',
	'protagoniste',
];

export const TYPES_ORGANISATION = ['entreprise', 'faction', 'gouvernement', 'informel'];

// ============================================================================
// TYPES DE RELATIONS
// ============================================================================

export const TYPES_RELATIONS = [
	// Interpersonnelles
	'connait', 'ami_de', 'famille_de', 'collegue_de', 'superieur_de', 'subordonne_de',
	'en_couple_avec', 'ex_de', 'interesse_par', 'rival_de', 'ennemi_de', 'mefiant_envers',

	// Lieux
	'habite', 'travaille_a', 'frequente', 'a_visite', 'evite',

	// Organisations
	'employe_de', 'membre_de', 'dirige', 'a_quitte', 'client_de',

	// Objets
	'possede', 'veut', 'a_perdu', 'a_prete_a', 'a_emprunte_a',

	// Arcs et lieux
	'implique_dans', 'situe_dans', 'connecte_a', 'proche_de', 'appartient_a', 'siege_de',

	// Organisations entre elles
	'partenaire_de', 'concurrent_de', 'filiale_de',

	// IA
	'assiste',

	// Services
	'a_aide', 'doit_service_a', 'a_promis_a',
];

// ============================================================================
// CATÉGORIES ET ÉTATS OBJETS
// ============================================================================

export const CATEGORIES_OBJET = [
	'nourriture',
	'outils',
	'equipement',
	'vetements',
	'decoration',
	'electronique',
	'documents',
	'mobilier',
	'hygiene',
	'loisirs',
	'consommable',
];

export const ETATS_OBJET = ['neuf', 'bon', 'use', 'abime', 'casse'];

// ============================================================================
// LOCALISATIONS
// ============================================================================

export const LOCALISATIONS = {
	SUR_SOI: 'sur_soi',
	SAC_A_DOS: 'sac_a_dos',
	SAC: 'sac',
	VALISE: 'valise',
	APPARTEMENT: 'appartement',
	BUREAU: 'bureau',
	STOCKAGE: 'stockage',
	PRETE: 'prete',
};

export const LOCALISATIONS_OBJETS = [LOCALISATIONS.SUR_SOI, LOCALISATIONS.SAC_A_DOS, LOCALISATIONS.SAC, LOCALISATIONS.VALISE, LOCALISATIONS.APPARTEMENT, LOCALISATIONS.BUREAU, LOCALISATIONS.STOCKAGE, LOCALISATIONS.PRETE]

export const LABELS_LOCALISATION = {
	[LOCALISATIONS.SUR_SOI]: '📍 Sur soi',
	[LOCALISATIONS.SAC_A_DOS]: '🎒 Sac à dos',
	[LOCALISATIONS.SAC]: '🎒 Sac',
	[LOCALISATIONS.VALISE]: '🧳 Valise',
	[LOCALISATIONS.APPARTEMENT]: '🏠 Appartement',
	[LOCALISATIONS.BUREAU]: '💼 Bureau',
	[LOCALISATIONS.STOCKAGE]: '📦 Stockage',
	[LOCALISATIONS.PRETE]: '🤝 Prêté',
};

// ============================================================================
// TYPES DE TRANSACTIONS
// ============================================================================

export const TYPES_TRANSACTION = [
	// Économiques
	'achat', 'vente', 'salaire', 'loyer', 'facture',
	'amende', 'pourboire', 'service', 'remboursement',

	// Transferts
	'don', 'cadeau_recu', 'pret', 'emprunt', 'retour_pret',

	// État
	'perte', 'oubli', 'vol', 'destruction', 'reparation', 'degradation',

	// Déplacement
	'deplacement', 'rangement', 'recuperation',
];

// ============================================================================
// TYPES DE LIEUX
// ============================================================================

export const TYPES_LIEU = [
	'commerce',
	'habitat',
	'travail',
	'public',
	'loisir',
	'transport',
	'medical',
	'administratif',
];

export const NIVEAUX_LIEU = ['zone', 'secteur', 'lieu'];

// ============================================================================
// TYPES D'ARCS NARRATIFS
// ============================================================================

export const TYPES_ARC = [
	'travail',
	'personnel',
	'romance',
	'exploration',
	'mystere',
	'social',
	'pnj_personnel',
];

export const ETATS_ARC = ['actif', 'en_pause', 'termine', 'abandonne'];

// ============================================================================
// ÉVÉNEMENTS
// ============================================================================

export const TYPES_EVENEMENT = ['passe', 'planifie', 'recurrent'];

export const CATEGORIES_EVENEMENT = [
	'social',
	'travail',
	'transaction',
	'deplacement',
	'decouverte',
	'incident',
	'station',
];

export const FREQUENCES_RECURRENCE = ['quotidien', 'hebdo', 'mensuel'];

// ============================================================================
// CERTITUDE EPISTÉMIQUE
// ============================================================================

export const NIVEAUX_CERTITUDE = ['certain', 'croit', 'soupconne', 'rumeur'];

// ============================================================================
// RÉGULARITÉ (PNJ dans lieux)
// ============================================================================

export const REGULARITES = ['souvent', 'parfois', 'rarement'];

// ============================================================================
// CONFIGURATION CONTEXT BUILDER
// ============================================================================

export const CONTEXT_CONFIG = {
	MAX_PERSONNAGES_FICHES: 10,
	MAX_EVENEMENTS_RECENTS: 8,
	MAX_EVENEMENTS_A_VENIR: 5,
	MAX_MESSAGES_RECENTS: 30,
	CYCLES_RECENTS: 3,
};

// ============================================================================
// CONFIGURATION CACHE (TTL en millisecondes)
// ============================================================================

export const CACHE_TTL = {
	PROTAGONISTE: 5 * 60 * 1000,      // 5 min
	IA: 10 * 60 * 1000,               // 10 min
	STATS: 30 * 1000,                 // 30 sec
	RELATIONS: 60 * 1000,             // 1 min
	PERSONNAGES: 2 * 60 * 1000,       // 2 min
	LIEUX: 5 * 60 * 1000,             // 5 min
	INVENTAIRE: 30 * 1000,            // 30 sec
	EVENEMENTS: 60 * 1000,            // 1 min
	CONNAISSANCES: 60 * 1000,         // 1 min
	DEFAULT: 60 * 1000,               // 1 min
};

export const CACHE_LIMITS = {
	MAX_ENTRIES_PER_PARTIE: 100,
	MAX_PARTIES: 10,
};

// ============================================================================
// CONFIGURATION SCENES
// ============================================================================

export const SCENE_CONFIG = {
	SEUIL_ANALYSE_INTERMEDIAIRE: 30, // Messages avant résumé intermédiaire
};

// ============================================================================
// SITUATIONS DE DÉPART
// ============================================================================

export const SITUATIONS_DEPART = {
	standard: {
		credits: 1400,
		description: 'Arrivée normale avec économies moyennes',
	},
	fuite_precipitee: {
		credits: 650,
		description: 'Départ précipité, peu d\'affaires',
	},
	rupture_difficile: {
		credits: 800,
		description: 'Rupture récente, affaires partagées',
	},
	opportunite_professionnelle: {
		credits: 2200,
		description: 'Mutation bien préparée avec prime',
	},
	nouveau_depart: {
		credits: 1000,
		description: 'Tout recommencer, le minimum vital',
	},
};

// ============================================================================
// SEXES
// ============================================================================

export const SEXES = {
	FEMININ: 'F',
	MASCULIN: 'M',
	AUTRE: 'A',
};

// ============================================================================
// CODES ERREUR
// ============================================================================

export const ERROR_CODES = {
	NOT_FOUND: 'NOT_FOUND',
	VALIDATION_ERROR: 'VALIDATION_ERROR',
	DB_ERROR: 'DB_ERROR',
	CLAUDE_API_ERROR: 'CLAUDE_API_ERROR',
	STREAM_ERROR: 'STREAM_ERROR',
	INTERNAL_ERROR: 'INTERNAL_ERROR',
};

// ============================================================================
// ICÔNES PAR TYPE D'ENTITÉ
// ============================================================================

export const ENTITY_ICONS = {
	personnage: '👤',
	lieu: '📍',
	organisation: '🏢',
	objet: '📦',
	arc_narratif: '📖',
	ia: '🤖',
	protagoniste: '🎭',
};

// ============================================================================
// LABELS DE RELATION
// ============================================================================

export const RELATION_LABELS = {
	connait: 'Connaissance',
	ami_de: 'Ami',
	collegue_de: 'Collègue',
	superieur_de: 'Supérieur',
	employe_de: 'Employeur',
	travaille_a: 'Lieu de travail',
	habite: 'Domicile',
	frequente: 'Lieu fréquenté',
	possede: 'Possédé',
};

// ============================================================================
// DISPOSITIONS PNJ
// ============================================================================

export const DISPOSITIONS = [
	'amicale',
	'neutre',
	'distante',
	'agacee',
	'chaleureuse',
	'mefiante',
	'pressee',
	'curieuse',
];

// ============================================================================
// FUZZY MATCHING
// ============================================================================

export const FUZZY_CONFIG = {
	SEUIL_OBJET: 70,
	SEUIL_EVENEMENT: 75,
	SEUIL_TRANSACTION: 80,
	SEUIL_ENTITE: 70,
};

// ============================================================================
// ÉCONOMIE (repères)
// ============================================================================

export const ECONOMIE = {
	SALAIRE_MENSUEL: 2000,
	LOYER_40M2: 600,
	NOURRITURE_MENSUELLE: 200,
	CAFE_SNACK: { min: 3, max: 8 },
	REPAS_RESTAURANT: { min: 15, max: 30 },
	OBJET_COURANT: { min: 10, max: 50 },
	REPARATION_SERVICE: { min: 50, max: 300 },
	EQUIPEMENT_TECH: { min: 100, max: 2000 },
};
