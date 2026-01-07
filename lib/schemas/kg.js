/**
 * Schémas Zod pour le Knowledge Graph
 * Validation et normalisation des entités, relations, états, événements et opérations
 */

import { z } from 'zod';

// ============================================================================
// HELPERS DE NORMALISATION
// ============================================================================

/**
 * Extrait un nombre d'une string ("28 ans" → 28, "3.5" → 3.5)
 */
function extraireNombre(val) {
	if (typeof val === 'number') return val;
	if (typeof val !== 'string') return undefined;
	const match = val.match(/-?\d+(\.\d+)?/);
	return match ? parseFloat(match[0]) : undefined;
}

/**
 * Convertit une valeur en tableau si nécessaire
 * "a, b, c" → ["a", "b", "c"]
 */
function versTableau(val) {
	if (Array.isArray(val)) return val;
	if (typeof val === 'string') {
		return val.split(/[,;]/).map(s => s.trim()).filter(Boolean);
	}
	return val ? [val] : [];
}

/**
 * Convertit en booléen
 */
function versBooleen(val) {
	if (typeof val === 'boolean') return val;
	if (typeof val === 'string') {
		return ['true', 'oui', 'yes', '1', 'vrai'].includes(val.toLowerCase());
	}
	return Boolean(val);
}

/**
 * Normalise une valeur selon sa table de valeurs canoniques
 */
function normaliserValeur(valeur, tableValeurs) {
	if (!valeur || !tableValeurs) return valeur;
	const valeurLower = String(valeur).toLowerCase().trim();
	return tableValeurs[valeurLower] || valeur;
}

/**
 * Normalise les clés d'un objet selon la table de synonymes
 */
function normaliserCles(obj, tablesSynonymes) {
	if (!obj || typeof obj !== 'object') return obj;

	const result = {};
	for (const [key, value] of Object.entries(obj)) {
		const keyLower = key.toLowerCase().trim();
		const cleCanonique = tablesSynonymes[keyLower] || keyLower;
		if (!(cleCanonique in result)) {
			result[cleCanonique] = value;
		}
	}
	return result;
}

// ============================================================================
// VALEURS CANONIQUES (normalisation des valeurs)
// ============================================================================

const VALEURS_CANONIQUES = {
	sexe: {
		'femme': 'F', 'female': 'F', 'f': 'F', 'féminin': 'F', 'feminine': 'F',
		'homme': 'M', 'male': 'M', 'm': 'M', 'masculin': 'M', 'masculine': 'M',
		'autre': 'A', 'other': 'A', 'non-binaire': 'A', 'nonbinary': 'A', 'nb': 'A', 'x': 'A',
	},

	type_lieu: {
		'shop': 'commerce', 'store': 'commerce', 'magasin': 'commerce', 'boutique': 'commerce',
		'bar': 'commerce', 'restaurant': 'commerce', 'cafe': 'commerce', 'café': 'commerce',
		'home': 'habitat', 'housing': 'habitat', 'residential': 'habitat', 'logement': 'habitat',
		'appartement': 'habitat', 'apartment': 'habitat',
		'office': 'travail', 'work': 'travail', 'bureau': 'travail', 'workplace': 'travail',
		'public_space': 'public', 'common': 'public', 'commun': 'public',
		'terminal': 'transport', 'station': 'transport', 'hub': 'transport', 'transit': 'transport',
		'quai': 'transport', 'dock': 'transport', 'hangar': 'transport',
		'entertainment': 'loisir', 'leisure': 'loisir', 'fun': 'loisir', 'divertissement': 'loisir',
		'health': 'medical', 'hospital': 'medical', 'clinic': 'medical', 'sante': 'medical',
		'admin': 'administratif', 'government': 'administratif', 'official': 'administratif',
	},

	type_objet: {
		'tool': 'outil', 'equipment': 'outil', 'equipement': 'outil',
		'clothes': 'vetement', 'clothing': 'vetement', 'habit': 'vetement', 'tenue': 'vetement',
		'food': 'nourriture', 'consumable': 'nourriture', 'drink': 'nourriture',
		'paper': 'document', 'file': 'document', 'doc': 'document', 'fichier': 'document',
		'tech': 'electronique', 'device': 'electronique', 'gadget': 'electronique', 'appareil': 'electronique',
		'furniture': 'mobilier', 'meuble': 'mobilier',
	},

	etat_objet: {
		'new': 'neuf', 'nouveau': 'neuf', 'mint': 'neuf',
		'good': 'bon', 'fine': 'bon', 'ok': 'bon',
		'used': 'use', 'worn': 'use', 'usagé': 'use', 'utilise': 'use',
		'damaged': 'abime', 'endommage': 'abime', 'endommagé': 'abime', 'abîmé': 'abime', 'broken': 'casse', 'cassé': 'casse',
	},

	niveau_lieu: {
		'world': 'zone', 'region': 'zone', 'monde': 'zone',
		'district': 'secteur', 'area': 'secteur', 'quartier': 'secteur',
		'place': 'lieu', 'spot': 'lieu', 'location': 'lieu', 'endroit': 'lieu',
	},

	type_arc: {
		'work': 'travail', 'job': 'travail', 'career': 'travail', 'carriere': 'travail',
		'personal': 'personnel', 'perso': 'personnel', 'self': 'personnel',
		'love': 'romance', 'romantic': 'romance', 'relationship': 'romance', 'amour': 'romance',
		'discover': 'exploration', 'explore': 'exploration', 'decouverte': 'exploration',
		'mystery': 'mystere', 'secret': 'mystere', 'enigme': 'mystere',
		'community': 'social', 'friendship': 'social', 'amitie': 'social',
	},

	etat_arc: {
		'active': 'actif', 'ongoing': 'actif', 'en_cours': 'actif', 'current': 'actif',
		'paused': 'en_pause', 'pause': 'en_pause', 'hold': 'en_pause', 'suspendu': 'en_pause',
		'done': 'termine', 'finished': 'termine', 'completed': 'termine', 'fini': 'termine',
		'dropped': 'abandonne', 'cancelled': 'abandonne', 'annule': 'abandonne', 'failed': 'abandonne',
	},
};

// ============================================================================
// SYNONYMES PAR TYPE D'ENTITÉ (normalisation des clés)
// ============================================================================

const SYNONYMES_ENTITES = {
	_common: {
		'description': 'description',
		'desc': 'description',
		'resume': 'description',
		'notes': 'description',
	},

	personnage: {
		// Identité
		'job': 'metier',
		'profession': 'metier',
		'travail': 'metier',
		'occupation': 'metier',
		'emploi': 'metier',
		'work': 'metier',
		'role': 'metier',

		'âge': 'age',
		'years': 'age',
		'ans': 'age',

		'race': 'espece',
		'species': 'espece',

		'genre': 'sexe',
		'gender': 'sexe',
		'sex': 'sexe',

		// Apparence
		'apparence': 'physique',
		'appearance': 'physique',
		'look': 'physique',
		'description_physique': 'physique',
		'corps': 'physique',

		// Personnalité
		'personnalite': 'traits',
		'personality': 'traits',
		'caractere': 'traits',
		'character': 'traits',
		'temperament': 'traits',
		'trait': 'traits',

		// Localisation
		'habitation': 'domicile',
		'residence': 'domicile',
		'home': 'domicile',
		'adresse': 'domicile',
		'lieu_vie': 'domicile',

		// Romance
		'romantique': 'interet_romantique',
		'romance': 'interet_romantique',
		'love_interest': 'interet_romantique',
		'datable': 'interet_romantique',
	},

	lieu: {
		'category': 'type_lieu',
		'categorie': 'type_lieu',
		'kind': 'type_lieu',
		'type': 'type_lieu',

		'zone': 'secteur',
		'district': 'secteur',
		'quartier': 'secteur',
		'area': 'secteur',
		'parent': 'secteur',

		'heures': 'horaires',
		'hours': 'horaires',
		'opening': 'horaires',
		'ouverture': 'horaires',
		'schedule': 'horaires',

		'mood': 'ambiance',
		'atmosphere': 'ambiance',
		'vibe': 'ambiance',
		'feeling': 'ambiance',

		'hierarchy': 'niveau',
		'level': 'niveau',
		'rank': 'niveau',
	},

	objet: {
		'category': 'type_objet',
		'categorie': 'type_objet',
		'kind': 'type_objet',
		'type': 'type_objet',

		'prix': 'valeur',
		'price': 'valeur',
		'cost': 'valeur',
		'worth': 'valeur',

		'condition': 'etat',
		'state': 'etat',
		'status': 'etat',
		'quality': 'etat',
	},

	organisation: {
		'category': 'type_org',
		'categorie': 'type_org',
		'kind': 'type_org',
		'type': 'type_org',

		'secteur': 'domaine',
		'sector': 'domaine',
		'field': 'domaine',
		'industry': 'domaine',

		'size': 'taille',
		'effectif': 'taille',
		'employees': 'taille',
	},

	arc_narratif: {
		'category': 'type_arc',
		'categorie': 'type_arc',
		'kind': 'type_arc',
		'type': 'type_arc',

		'progress': 'progression',
		'avancement': 'progression',
		'completion': 'progression',

		'blocages': 'obstacles',
		'challenges': 'obstacles',
		'problems': 'obstacles',
		'defis': 'obstacles',

		'status': 'etat',
		'state': 'etat',
		'statut': 'etat',
	},
};

// ============================================================================
// DÉTECTION DE MAUVAIS TYPAGE
// ============================================================================

/**
 * Propriétés caractéristiques par type (pour détection)
 */
const PROPRIETES_SIGNATURE = {
	personnage: {
		fortes: ['age', 'sexe', 'metier', 'traits', 'physique', 'espece', 'interet_romantique'],
		faibles: ['domicile', 'arcs', 'cheveux', 'yeux', 'vetements'],
		exclues: ['horaires', 'ambiance', 'type_lieu', 'pnjs_frequents'],
	},
	lieu: {
		fortes: ['type_lieu', 'horaires', 'ambiance', 'secteur', 'niveau', 'pnjs_frequents'],
		faibles: ['description', 'capacite'],
		exclues: ['age', 'sexe', 'physique', 'traits', 'interet_romantique'],
	},
	objet: {
		fortes: ['type_objet', 'valeur', 'etat'],
		faibles: ['description'],
		exclues: ['age', 'sexe', 'horaires'],
	},
	organisation: {
		fortes: ['type_org', 'domaine', 'taille', 'effectif'],
		faibles: ['description', 'siege'],
		exclues: ['age', 'sexe', 'physique'],
	},
	arc_narratif: {
		fortes: ['type_arc', 'progression', 'obstacles', 'pnjs_impliques'],
		faibles: ['description', 'etat'],
		exclues: ['age', 'sexe', 'horaires'],
	},
	ia: {
		fortes: ['voix', 'programmation', 'createur'],
		faibles: ['traits', 'caracteristiques'],
		exclues: ['horaires', 'type_lieu'],
	},
};

/**
 * Patterns de noms caractéristiques
 */
const PATTERNS_NOMS = {
	lieu: [
		// === Début de nom ===
		/^(le |la |l'|les )?(bar|restaurant|café|comptoir)\b/i,
		/^(le |la |l'|les )?(terminal|station|quai|dock|hangar)\b/i,
		/^(le |la |l'|les )?(bureau|clinique|hôpital|infirmerie)\b/i,
		/^(le |la |l'|les )?(appartement|appart|chambre|studio|loft)\b/i,
		/^(le |la |l'|les )?(dortoir|colocation|résidence)\b/i,
		/^(le |la |l'|les )?(boutique|magasin|échoppe|arrière-boutique)\b/i,
		/^(le |la |l'|les )?(secteur|quartier|zone|district)\b/i,

		// === Patterns avec codes/numéros ===
		/^appartement\s*\d+/i,
		/^secteur\s*[a-z](\s|$|-|—)/i,      // "Secteur E", "Secteur A (Administratif)"
		/^habitat-[a-z]/i,                   // "Habitat-C"
		/^commerce-[a-z]/i,                  // "Commerce-B"
		/^tech-[a-z]/i,                      // "Tech-A"
		/^zone\s+(centrale|nord|sud|est|ouest|\d)/i,

		// === Patterns descriptifs entre parenthèses ===
		/\(zone\s+\w+\)/i,                   // "(zone populaire)", "(zone centrale)"
		/\(quartier\s+\w+\)/i,
		/\(secteur\s+\w+\)/i,
		/\(même\s+(étage|couloir|niveau)\b/i, // "(même étage que...)"

		// === Patterns avec tiret long (—) ===
		/—\s*secteur\s+/i,                   // "— Secteur Habitat-C"

		// === Mots-clés dans le nom ===
		/\b(niveau|étage|sous-sol|rez-de-chaussée)\b/i,
		/\b(agriculture|agricole|hydroponique)\b/i,
		/\bstation\s+de\s+(recharge|maintenance|contrôle)/i,

		// === Suffixes numériques ===
		/\s+\d{3,4}(\s|$|,|—)/,              // "Appartement 1247", "Bureau 12"
	],

	organisation: [
		/\b(inc|corp|ltd|sarl|sa|gmbh|analytics|industries|group|systems|dynamics)\b/i,
		/\b(entreprise|société|compagnie|faction|guilde|syndicat)\b/i,
		/^chronos\b/i,
		/^helix\b/i,
	],

	ia: [
		/^(unit-?\d+|robot|androïde|drone)/i,
		/\b(assistant|ia|intelligence artificielle)\b/i,
	],

	personnage: [
		// Prénoms courants (sample)
		/^(jean|marie|pierre|paul|jacques|michel|andré|philippe|alain|bernard|daniel|robert|marc|patrick|éric|laurent|christophe|nicolas|stéphane|david|julien|sébastien|thomas|maxime|antoine|alexandre|hugo|lucas|théo|nathan|mathis|léo|gabriel|raphaël|louis|arthur|jules|adam|maël|noah|ethan|nino|timéo|liam|aaron|sacha|valentin|victor|martin|dimitri|kael|emilio|davi)\b/i,
		/^(justine|mira|elena|sarah|laura|julie|sophie|camille|emma|léa|manon|chloé|inès|jade|louise|alice|lola|anna|rose|julia|eva|charlotte|zoé|clara|margot|lucie|jeanne|agathe|victoire|capucine|clémence|gabrielle|hélène|juliette|laure|mathilde|pauline|romane|roxane|salomé|valentine|amélie|siobhan|amaia|saraswati)\b/i,
		// Titres suivis de nom
		/^(dr\.|docteur|prof\.|professeur|mme|mr|m\.)\s+\w/i,
		// Nom + Prénom (deux mots capitalisés)
		/^[A-Z][a-zéèêëàâäùûüïîôö]+\s+[A-Z][a-zéèêëàâäùûüïîôö]+$/,
	],
};

/**
 * Détecte le type probable d'une entité basé sur ses propriétés et son nom
 * @returns {{ typeSuggere: string|null, confiance: number, raisons: string[] }}
 */
export function detecterType(nom, proprietes) {
	const scores = {
		personnage: 0,
		lieu: 0,
		objet: 0,
		organisation: 0,
		arc_narratif: 0,
		ia: 0,
	};
	const raisons = [];
	const props = proprietes || {};

	// Normaliser les clés pour l'analyse
	const cles = Object.keys(props).map(k => k.toLowerCase());
	const clesAvecSynonymes = new Set(cles);

	// Ajouter les clés canoniques correspondantes
	for (const [type, synonymes] of Object.entries(SYNONYMES_ENTITES)) {
		if (type === '_common') continue;
		for (const cle of cles) {
			if (synonymes[cle]) {
				clesAvecSynonymes.add(synonymes[cle]);
			}
		}
	}

	// === DÉTECTION IA DANS LES PROPRIÉTÉS ===
	const propsStr = JSON.stringify(props).toLowerCase();
	if (
		props.type?.toLowerCase() === 'ia' ||
		props.role?.toLowerCase()?.includes('ia') ||
		props.role?.toLowerCase()?.includes('virtuel') ||
		propsStr.includes('"ia"') ||
		propsStr.includes('intelligence artificielle') ||
		propsStr.includes('compagne virtuelle') ||
		propsStr.includes('assistant virtuel')
	) {
		scores.ia += 10;
		raisons.push('propriété indique IA');
	}

	// === SCORE BASÉ SUR LES PROPRIÉTÉS ===
	for (const [type, signatures] of Object.entries(PROPRIETES_SIGNATURE)) {
		// Propriétés fortes (+3)
		for (const prop of signatures.fortes) {
			if (clesAvecSynonymes.has(prop)) {
				scores[type] += 3;
				raisons.push(`propriété "${prop}" → ${type}`);
			}
		}
		// Propriétés faibles (+1)
		for (const prop of (signatures.faibles || [])) {
			if (clesAvecSynonymes.has(prop)) {
				scores[type] += 1;
			}
		}
		// Propriétés exclues (-3)
		for (const prop of (signatures.exclues || [])) {
			if (clesAvecSynonymes.has(prop)) {
				scores[type] -= 3;
			}
		}
	}

	// === SCORE BASÉ SUR LE NOM ===
	for (const [type, patterns] of Object.entries(PATTERNS_NOMS)) {
		for (const pattern of patterns) {
			if (pattern.test(nom)) {
				scores[type] += 3;
				raisons.push(`nom "${nom}" → pattern ${type}`);
				break; // Un seul match par type
			}
		}
	}

	// === HEURISTIQUES SPÉCIALES ===

	// Propriétés vides → TRÈS suspect pour un personnage (un vrai PNJ a toujours des infos)
	const propsVides = Object.keys(props).length === 0;

	if (propsVides) {
		// Malus personnage : un PNJ sans propriétés est très improbable
		scores.personnage -= 2;

		// Bonus lieu si le nom contient des indices
		if (/secteur|zone|habitat|commerce|tech-|appartement|dortoir|bureau|station|colocation|arrière/i.test(nom)) {
			scores.lieu += 5;
			raisons.push('propriétés vides + nom de lieu');
		}
		if (/\d{3,}/.test(nom)) { // Numéro à 3+ chiffres (Appartement 1247)
			scores.lieu += 2;
		}
	}

	// Age numérique → très probablement personnage
	if (props.age !== undefined && !isNaN(parseInt(props.age))) {
		scores.personnage += 2;
	}

	// Espèce non-humain définie → personnage (alien, androïde, etc.)
	if (props.espece && props.espece.toLowerCase() !== 'humain') {
		scores.personnage += 2;
	}

	// interet_romantique défini → personnage
	if (props.interet_romantique !== undefined) {
		scores.personnage += 3;
	}

	// === TROUVER LE MEILLEUR TYPE ===
	let meilleurType = null;
	let meilleurScore = 0;
	let secondScore = 0;

	for (const [type, score] of Object.entries(scores)) {
		if (score > meilleurScore) {
			secondScore = meilleurScore;
			meilleurScore = score;
			meilleurType = type;
		} else if (score > secondScore) {
			secondScore = score;
		}
	}

	// Confiance basée sur l'écart + score absolu
	const ecart = meilleurScore - secondScore;
	const confiance = meilleurScore <= 0 ? 0 : Math.min(100, ecart * 15 + meilleurScore * 8);

	return {
		typeSuggere: meilleurScore >= 2 ? meilleurType : null,
		confiance,
		scores,
		raisons: [...new Set(raisons)], // Dédupliquer
	};
}

/**
 * Vérifie si le type déclaré est cohérent avec les propriétés
 * @returns {{ valide: boolean, correction?: string, confiance: number, raisons: string[] }}
 */
export function verifierCoherenceType(typeDecare, nom, proprietes) {
	const detection = detecterType(nom, proprietes);

	// Pas assez d'indices pour juger
	if (!detection.typeSuggere || detection.confiance < 40) {
		return { valide: true, confiance: detection.confiance, raisons: [] };
	}

	// Type cohérent
	if (detection.typeSuggere === typeDecare) {
		return { valide: true, confiance: detection.confiance, raisons: [] };
	}

	// Incohérence détectée
	const scoreDecare = detection.scores[typeDecare] || 0;
	const scoreSuggere = detection.scores[detection.typeSuggere];

	// Seuil de correction : le type suggéré doit être significativement plus probable
	// Écart ≥ 3 ET confiance ≥ 60%
	if (scoreSuggere >= scoreDecare + 3 && detection.confiance >= 60) {
		return {
			valide: false,
			correction: detection.typeSuggere,
			confiance: detection.confiance,
			raisons: detection.raisons,
		};
	}

	// Avertissement sans correction automatique
	if (scoreSuggere > scoreDecare) {
		return {
			valide: true, // On laisse passer mais on warn
			avertissement: `Type "${typeDecare}" douteux, "${detection.typeSuggere}" semble plus probable`,
			confiance: detection.confiance,
			raisons: detection.raisons,
		};
	}

	return { valide: true, confiance: detection.confiance, raisons: [] };
}

// ============================================================================
// SCHÉMAS ZOD - ENTITÉS
// ============================================================================

export const PersonnageProprietesSchema = z.object({
	age: z.preprocess(extraireNombre, z.number().min(0).max(1000)).optional(),
	sexe: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.sexe),
		z.enum(['F', 'M', 'A'])).optional(),
	espece: z.string().default('humain'),
	physique: z.string().optional(),
	metier: z.string().optional(),
	domicile: z.string().optional(),
	traits: z.preprocess(versTableau, z.array(z.string()).default([])),
	interet_romantique: z.preprocess(versBooleen, z.boolean().default(false)),
	arcs: z.preprocess(versTableau, z.array(z.string()).default([])),
	description: z.string().optional(),
}).strict();

export const LieuProprietesSchema = z.object({
	niveau: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.niveau_lieu),
		z.enum(['zone', 'secteur', 'lieu'])).optional(),
	type_lieu: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.type_lieu),
		z.enum(['commerce', 'habitat', 'travail', 'public', 'loisir', 'transport', 'medical', 'administratif'])).optional(),
	secteur: z.string().optional(),
	horaires: z.string().optional(),
	ambiance: z.string().optional(),
	description: z.string().optional(),
	pnjs_frequents: z.array(z.any()).optional(),
}).strict();

export const ObjetProprietesSchema = z.object({
	type_objet: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.type_objet),
		z.enum(['outil', 'vetement', 'nourriture', 'document', 'electronique', 'mobilier'])).optional(),
	valeur: z.preprocess(extraireNombre, z.number().min(0)).optional(),
	etat: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.etat_objet),
		z.enum(['neuf', 'bon', 'use', 'abime', 'casse']).default('bon')
	),
	description: z.string().optional(),
}).strict();

export const OrganisationProprietesSchema = z.object({
	type_org: z.enum(['entreprise', 'faction', 'gouvernement', 'informel']).optional(),
	domaine: z.string().optional(),
	taille: z.string().optional(),
	description: z.string().optional(),
}).strict();

export const ArcNarratifProprietesSchema = z.object({
	type_arc: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.type_arc),
		z.enum(['travail', 'personnel', 'romance', 'exploration', 'mystere', 'social', 'pnj_personnel'])).optional(),
	description: z.string().optional(),
	progression: z.preprocess(extraireNombre, z.number().min(0).max(100).default(0)),
	etat: z.preprocess(
		v => normaliserValeur(v, VALEURS_CANONIQUES.etat_arc),
		z.enum(['actif', 'en_pause', 'termine', 'abandonne']).default('actif')
	),
	obstacles: z.preprocess(versTableau, z.array(z.string()).default([])),
	pnjs_impliques: z.preprocess(versTableau, z.array(z.string()).default([])),
}).strict();

export const IAProprietesSchema = z.object({
	traits: z.preprocess(versTableau, z.array(z.string()).default([])),
	voix: z.string().optional(),
	description: z.string().optional(),
}).strict();

export const ProtagonistProprietesSchema = z.object({
	physique: z.string().optional(),
	traits: z.preprocess(versTableau, z.array(z.string()).default([])),
	raison_depart: z.string().optional(),
	poste: z.string().optional(),
	hobbies: z.preprocess(versTableau, z.array(z.string()).default([])),
	competences: z.record(z.number().min(1).max(5)).optional(),
	description: z.string().optional(),
}).strict();

/**
 * Mapping type → schéma pour les entités
 */
const SCHEMAS_ENTITES = {
	personnage: PersonnageProprietesSchema,
	lieu: LieuProprietesSchema,
	objet: ObjetProprietesSchema,
	organisation: OrganisationProprietesSchema,
	arc_narratif: ArcNarratifProprietesSchema,
	ia: IAProprietesSchema,
	protagoniste: ProtagonistProprietesSchema,
};

/**
 * Valide et normalise une entité complète (type + propriétés)
 */
export function validerEntite(typeDecare, nom, proprietes) {
	const corrections = [];
	const erreurs = [];
	let typeFinal = typeDecare;
	let typeCorrige = false;

	// ===== ÉTAPE 1 : Vérifier cohérence du type =====
	const coherence = verifierCoherenceType(typeDecare, nom, proprietes);

	if (!coherence.valide && coherence.correction) {
		corrections.push(`type "${typeDecare}" → "${coherence.correction}" (${coherence.raisons.join(', ')})`);
		typeFinal = coherence.correction;
		typeCorrige = true;
	} else if (coherence.avertissement) {
		console.warn(`[Schema] ${nom}: ${coherence.avertissement}`);
	}

	// ===== ÉTAPE 2 : Normaliser les clés =====
	if (!proprietes || typeof proprietes !== 'object') {
		return { success: true, type: typeFinal, proprietes: {}, corrections, erreurs, typeCorrige };
	}

	const synonymes = {
		...SYNONYMES_ENTITES._common,
		...(SYNONYMES_ENTITES[typeFinal] || {})
	};
	const avantNormalisation = { ...proprietes };
	const apresNormalisation = normaliserCles(proprietes, synonymes);

	// Tracker les corrections de clés
	for (const [oldKey, value] of Object.entries(avantNormalisation)) {
		const newKey = Object.keys(apresNormalisation).find(k =>
			apresNormalisation[k] === value && k !== oldKey.toLowerCase()
		);
		if (newKey && newKey !== oldKey.toLowerCase()) {
			corrections.push(`clé "${oldKey}" → "${newKey}"`);
		}
	}

	// ===== ÉTAPE 3 : Valider avec Zod (strict) =====
	const schema = SCHEMAS_ENTITES[typeFinal];

	if (!schema) {
		return { success: true, type: typeFinal, proprietes: apresNormalisation, corrections, erreurs, typeCorrige };
	}

	const result = schema.safeParse(apresNormalisation);

	if (!result.success) {
		for (const issue of result.error.issues) {
			const path = issue.path.join('.');

			if (issue.code === 'unrecognized_keys') {
				// Clés non reconnues → on les supprime
				for (const key of issue.keys) {
					erreurs.push(`propriété "${key}" ignorée (non reconnue pour ${typeFinal})`);
					delete apresNormalisation[key];
				}
			} else if (issue.code === 'invalid_enum_value') {
				erreurs.push(`${path}: valeur "${issue.received}" invalide`);
				delete apresNormalisation[path];
			} else {
				erreurs.push(`${path}: ${issue.message}`);
				delete apresNormalisation[path];
			}
		}

		// Re-valider après nettoyage
		const retryResult = schema.safeParse(apresNormalisation);
		if (retryResult.success) {
			return {
				success: true,
				type: typeFinal,
				proprietes: retryResult.data,
				corrections,
				erreurs,
				typeCorrige
			};
		}
	}

	// Tracker corrections de valeurs
	if (result.success) {
		for (const [key, newVal] of Object.entries(result.data)) {
			const oldVal = apresNormalisation[key];
			if (oldVal !== undefined && oldVal !== newVal && typeof newVal !== 'object') {
				if (String(oldVal).toLowerCase() !== String(newVal).toLowerCase()) {
					corrections.push(`${key}: "${oldVal}" → "${newVal}"`);
				}
			}
		}
	}

	return {
		success: result.success,
		type: typeFinal,
		proprietes: result.success ? result.data : apresNormalisation,
		corrections,
		erreurs,
		typeCorrige
	};
}

/**
 * Version simplifiée pour kgOperations
 */
export function normaliserEntite(typeDecare, nom, proprietes) {
	const result = validerEntite(typeDecare, nom, proprietes);

	if (result.corrections.length > 0) {
		console.log(`[Schema] ${nom} - Corrections:`, result.corrections.join(', '));
	}
	if (result.erreurs.length > 0) {
		console.warn(`[Schema] ${nom} - Erreurs:`, result.erreurs.join(', '));
	}

	return {
		type: result.type,
		proprietes: result.proprietes,
		typeCorrige: result.typeCorrige,
	};
}

// ============================================================================
// SCHÉMAS ZOD - RELATIONS
// ============================================================================

const SYNONYMES_RELATIONS = {
	_common: {
		'since': 'depuis_cycle',
		'depuis': 'depuis_cycle',
		'cycle': 'depuis_cycle',
	},

	connait: {
		'level': 'niveau',
		'relation': 'niveau',
		'intimite': 'niveau',
		'proximite': 'niveau',
		'romance': 'etape_romantique',
		'romantic': 'etape_romantique',
		'etape': 'etape_romantique',
		'context': 'contexte',
		'how_met': 'contexte',
		'rencontre': 'contexte',
	},

	possede: {
		'qty': 'quantite',
		'quantity': 'quantite',
		'nombre': 'quantite',
		'count': 'quantite',
	},

	employe_de: {
		'job': 'poste',
		'role': 'poste',
		'position': 'poste',
		'titre': 'poste',
		'hours': 'horaires',
		'schedule': 'horaires',
	},

	frequente: {
		'frequency': 'regularite',
		'frequence': 'regularite',
		'how_often': 'regularite',
		'when': 'periode',
		'quand': 'periode',
		'moment': 'periode',
	},

	a_visite: {
		'visits': 'cycles',
		'visites': 'cycles',
	},

	doit_service_a: {
		'what': 'quoi',
		'description': 'quoi',
		'reason': 'quoi',
		'raison': 'quoi',
		'weight': 'importance',
		'poids': 'importance',
		'gravity': 'importance',
	},
};

export const ConnaitProprietesSchema = z.object({
	niveau: z.preprocess(extraireNombre, z.number().min(0).max(10).default(1)),
	etape_romantique: z.preprocess(extraireNombre, z.number().min(0).max(6)).optional(),
	contexte: z.string().optional(),
	depuis_cycle: z.preprocess(extraireNombre, z.number()).optional(),
}).strict();

export const PossedeProprietesSchema = z.object({
	quantite: z.preprocess(extraireNombre, z.number().min(1).default(1)),
	depuis_cycle: z.preprocess(extraireNombre, z.number()).optional(),
	dernier_cycle_utilise: z.preprocess(extraireNombre, z.number()).optional(),
}).strict();

export const EmployeDeProprietesSchema = z.object({
	poste: z.string().optional(),
	horaires: z.string().optional(),
	depuis_cycle: z.preprocess(extraireNombre, z.number()).optional(),
}).strict();

export const FrequenteProprietesSchema = z.object({
	regularite: z.preprocess(
		v => normaliserValeur(v, { 'often': 'souvent', 'sometimes': 'parfois', 'rarely': 'rarement' }),
		z.enum(['souvent', 'parfois', 'rarement']).default('parfois')
	),
	periode: z.string().optional(),
}).strict();

export const AVisiteProprietesSchema = z.object({
	cycles: z.preprocess(versTableau, z.array(z.number()).default([])),
}).strict();

export const DoitServiceAProprietesSchema = z.object({
	quoi: z.string(),
	importance: z.preprocess(extraireNombre, z.number().min(1).max(5).default(2)),
}).strict();

export const RelationGeneriqueProprietesSchema = z.object({
	depuis_cycle: z.preprocess(extraireNombre, z.number()).optional(),
	raison: z.string().optional(),
	contexte: z.string().optional(),
}).passthrough();

/**
 * Mapping type → schéma pour les relations
 */
const SCHEMAS_RELATIONS = {
	connait: ConnaitProprietesSchema,
	possede: PossedeProprietesSchema,
	employe_de: EmployeDeProprietesSchema,
	frequente: FrequenteProprietesSchema,
	a_visite: AVisiteProprietesSchema,
	doit_service_a: DoitServiceAProprietesSchema,
};

/**
 * Valide et normalise les propriétés d'une relation
 */
export function validerProprietesRelation(typeRelation, proprietes) {
	const corrections = [];
	const erreurs = [];

	if (!proprietes || typeof proprietes !== 'object') {
		return { success: true, data: {}, corrections, erreurs };
	}

	// Normaliser les clés
	const synonymes = {
		...SYNONYMES_RELATIONS._common,
		...(SYNONYMES_RELATIONS[typeRelation] || {})
	};
	const apresNormalisation = normaliserCles(proprietes, synonymes);

	// Tracker corrections de clés
	for (const [oldKey, value] of Object.entries(proprietes)) {
		const newKey = Object.keys(apresNormalisation).find(k =>
			apresNormalisation[k] === value && k !== oldKey.toLowerCase()
		);
		if (newKey && newKey !== oldKey.toLowerCase()) {
			corrections.push(`clé "${oldKey}" → "${newKey}"`);
		}
	}

	// Valider avec le schéma approprié
	const schema = SCHEMAS_RELATIONS[typeRelation] || RelationGeneriqueProprietesSchema;
	const result = schema.safeParse(apresNormalisation);

	if (!result.success) {
		for (const issue of result.error.issues) {
			const path = issue.path.join('.');

			if (issue.code === 'unrecognized_keys') {
				for (const key of issue.keys) {
					erreurs.push(`propriété "${key}" ignorée`);
					delete apresNormalisation[key];
				}
			} else {
				erreurs.push(`${path}: ${issue.message}`);
				delete apresNormalisation[path];
			}
		}

		// Re-valider après nettoyage
		const retryResult = schema.safeParse(apresNormalisation);
		if (retryResult.success) {
			return { success: true, data: retryResult.data, corrections, erreurs };
		}
	}

	// Tracker corrections de valeurs
	if (result.success) {
		for (const [key, newVal] of Object.entries(result.data)) {
			const oldVal = apresNormalisation[key];
			if (oldVal !== undefined && oldVal !== newVal && typeof newVal !== 'object') {
				if (String(oldVal).toLowerCase() !== String(newVal).toLowerCase()) {
					corrections.push(`${key}: "${oldVal}" → "${newVal}"`);
				}
			}
		}
	}

	return {
		success: result.success,
		data: result.success ? result.data : apresNormalisation,
		corrections,
		erreurs
	};
}

/**
 * Version simplifiée pour kgOperations
 */
export function normaliserProprietesRelation(typeRelation, proprietes) {
	const result = validerProprietesRelation(typeRelation, proprietes);

	if (result.corrections.length > 0) {
		console.log(`[Schema] Relation ${typeRelation} - Corrections:`, result.corrections.join(', '));
	}
	if (result.erreurs.length > 0) {
		console.warn(`[Schema] Relation ${typeRelation} - Erreurs:`, result.erreurs.join(', '));
	}

	return result.data;
}

// ============================================================================
// SCHÉMAS ZOD - ÉTATS (kg_etats)
// ============================================================================

/**
 * Configuration des attributs d'état par type d'entité
 */
const ATTRIBUTS_ETATS = {
	protagoniste: {
		energie: { min: 0, max: 5, type: 'number', defaut: 3 },
		moral: { min: 0, max: 5, type: 'number', defaut: 3 },
		sante: { min: 0, max: 5, type: 'number', defaut: 5 },
		credits: { min: 0, max: Infinity, type: 'number', defaut: 1400 },
		humeur: { type: 'string' },
		localisation: { type: 'string' },
	},
	personnage: {
		disposition: { type: 'string' },
		stat_social: { min: 1, max: 5, type: 'number' },
		stat_travail: { min: 1, max: 5, type: 'number' },
		stat_sante: { min: 1, max: 5, type: 'number' },
		humeur: { type: 'string' },
		localisation: { type: 'string' },
	},
	lieu: {
		etat: {
			type: 'enum',
			valeurs: ['ouvert', 'ferme', 'en_travaux', 'bonde', 'vide', 'dangereux'],
			synonymes: {
				'open': 'ouvert', 'closed': 'ferme', 'fermé': 'ferme',
				'crowded': 'bonde', 'bondé': 'bonde', 'empty': 'vide',
			}
		},
		ambiance: { type: 'string' },
	},
	objet: {
		etat: {
			type: 'enum',
			valeurs: ['neuf', 'bon', 'use', 'abime', 'casse'],
			synonymes: VALEURS_CANONIQUES.etat_objet,
		},
	},
	arc_narratif: {
		etat: {
			type: 'enum',
			valeurs: ['actif', 'en_pause', 'termine', 'abandonne'],
			synonymes: VALEURS_CANONIQUES.etat_arc,
		},
		progression: { min: 0, max: 100, type: 'number', defaut: 0 },
	},
};

const SYNONYMES_ATTRIBUTS = {
	'energy': 'energie', 'énergie': 'energie',
	'morale': 'moral', 'mood': 'moral',
	'health': 'sante', 'santé': 'sante', 'hp': 'sante',
	'money': 'credits', 'argent': 'credits', 'cash': 'credits',
	'location': 'localisation', 'position': 'localisation', 'lieu': 'localisation',
	'status': 'etat', 'statut': 'etat', 'state': 'etat',
	'progress': 'progression', 'avancement': 'progression',
	'attitude': 'disposition', 'feeling': 'disposition',
};

/**
 * Valide et normalise un état
 * @returns {{ success: boolean, attribut: string, valeur: any, erreur?: string }}
 */
export function validerEtat(typeEntite, attribut, valeur) {
	// Normaliser l'attribut
	const attrLower = attribut.toLowerCase().trim();
	const attrNormalise = SYNONYMES_ATTRIBUTS[attrLower] || attrLower;

	// Récupérer la config
	const configEntite = ATTRIBUTS_ETATS[typeEntite];
	if (!configEntite) {
		return { success: true, attribut: attrNormalise, valeur: String(valeur) };
	}

	const configAttr = configEntite[attrNormalise];
	if (!configAttr) {
		return {
			success: false,
			attribut: attrNormalise,
			valeur,
			erreur: `Attribut "${attrNormalise}" non reconnu pour ${typeEntite}`
		};
	}

	// Valider selon le type
	let valeurNormalisee = valeur;

	if (configAttr.type === 'number') {
		valeurNormalisee = parseFloat(valeur);
		if (isNaN(valeurNormalisee)) {
			// Essayer d'extraire un nombre
			const match = String(valeur).match(/-?\d+(\.\d+)?/);
			valeurNormalisee = match ? parseFloat(match[0]) : configAttr.defaut;
		}
		// Bornes
		if (configAttr.min !== undefined) {
			valeurNormalisee = Math.max(configAttr.min, valeurNormalisee);
		}
		if (configAttr.max !== undefined) {
			valeurNormalisee = Math.min(configAttr.max, valeurNormalisee);
		}
	}
	else if (configAttr.type === 'enum') {
		const valLower = String(valeur).toLowerCase().trim();
		valeurNormalisee = configAttr.synonymes?.[valLower] || valLower;

		if (!configAttr.valeurs.includes(valeurNormalisee)) {
			return {
				success: false,
				attribut: attrNormalise,
				valeur,
				erreur: `Valeur "${valeur}" invalide pour ${attrNormalise}. Attendu: ${configAttr.valeurs.join(', ')}`
			};
		}
	}
	else if (configAttr.type === 'string') {
		valeurNormalisee = String(valeur).trim();
	}

	return {
		success: true,
		attribut: attrNormalise,
		valeur: valeurNormalisee,
		correction: valeur !== valeurNormalisee ? `${valeur} → ${valeurNormalisee}` : null
	};
}

/**
 * Vérifie si un attribut est valide pour un type d'entité
 */
export function attributEstValide(typeEntite, attribut) {
	const attrLower = attribut.toLowerCase().trim();
	const attrNormalise = SYNONYMES_ATTRIBUTS[attrLower] || attrLower;
	const configEntite = ATTRIBUTS_ETATS[typeEntite];
	return configEntite ? attrNormalise in configEntite : true;
}

// ============================================================================
// SCHÉMAS ZOD - ÉVÉNEMENTS (kg_evenements)
// ============================================================================

const SYNONYMES_EVENEMENTS = {
	type: {
		'past': 'passe', 'passé': 'passe', 'done': 'passe', 'fait': 'passe',
		'planned': 'planifie', 'planifié': 'planifie', 'scheduled': 'planifie', 'prevu': 'planifie',
		'recurring': 'recurrent', 'récurrent': 'recurrent', 'repeat': 'recurrent',
	},
	categorie: {
		'social': 'social', 'meeting': 'social', 'rencontre': 'social',
		'work': 'travail', 'job': 'travail', 'boulot': 'travail',
		'transaction': 'transaction', 'achat': 'transaction', 'vente': 'transaction', 'payment': 'transaction',
		'travel': 'deplacement', 'déplacement': 'deplacement', 'move': 'deplacement',
		'discovery': 'decouverte', 'découverte': 'decouverte', 'revelation': 'decouverte',
		'incident': 'incident', 'accident': 'incident', 'problem': 'incident', 'probleme': 'incident',
		'station': 'station', 'public': 'station', 'announcement': 'station',
	},
	frequence: {
		'daily': 'quotidien', 'jour': 'quotidien', 'everyday': 'quotidien',
		'weekly': 'hebdo', 'semaine': 'hebdo', 'week': 'hebdo',
		'monthly': 'mensuel', 'mois': 'mensuel', 'month': 'mensuel',
	},
};

const TYPES_EVENEMENT = ['passe', 'planifie', 'recurrent'];
const CATEGORIES_EVENEMENT = ['social', 'travail', 'transaction', 'deplacement', 'decouverte', 'incident', 'station'];

export const RecurrenceSchema = z.object({
	frequence: z.preprocess(
		v => SYNONYMES_EVENEMENTS.frequence[String(v).toLowerCase()] || v,
		z.enum(['quotidien', 'hebdo', 'mensuel'])
	),
	prochain_cycle: z.preprocess(extraireNombre, z.number()).optional(),
	jour_semaine: z.string().optional(),
	jour_mois: z.preprocess(extraireNombre, z.number().min(1).max(31)).optional(),
});

export const EvenementSchema = z.object({
	type: z.preprocess(
		v => SYNONYMES_EVENEMENTS.type[String(v).toLowerCase()] || v,
		z.enum(['passe', 'planifie', 'recurrent']).default('passe')
	),
	categorie: z.preprocess(
		v => SYNONYMES_EVENEMENTS.categorie[String(v).toLowerCase()] || v,
		z.enum(CATEGORIES_EVENEMENT).default('social')
	),
	titre: z.string().min(1, "Titre requis"),
	description: z.string().optional(),
	cycle: z.preprocess(extraireNombre, z.number().min(1)),
	heure: z.string()
		.regex(/^\d{1,2}h\d{2}$/, "Format heure invalide")
		.optional()
		.or(z.literal(''))
		.transform(v => v || undefined),
	lieu: z.string().optional(),
	participants: z.preprocess(versTableau, z.array(z.string()).default([])),
	montant: z.preprocess(extraireNombre, z.number()).optional(),
});

export const EvenementPlanifieSchema = EvenementSchema.extend({
	type: z.literal('planifie').default('planifie'),
	cycle_prevu: z.preprocess(extraireNombre, z.number().min(1)),
	recurrence: RecurrenceSchema.optional(),
}).omit({ cycle: true });

/**
 * Valide et normalise un événement
 */
export function validerEvenement(data, estPlanifie = false) {
	const schema = estPlanifie ? EvenementPlanifieSchema : EvenementSchema;
	const result = schema.safeParse(data);

	if (!result.success) {
		const erreurs = result.error.issues.map(i => `${i.path.join('.')}: ${i.message}`);
		return { success: false, erreurs, data: null };
	}

	return { success: true, data: result.data, erreurs: [] };
}

/**
 * Normalise les champs d'un événement (version simplifiée pour kgOperations)
 */
export function normaliserEvenement(data, estPlanifie = false) {
	const result = validerEvenement(data, estPlanifie);

	if (!result.success) {
		console.warn(`[Schema] Événement invalide:`, result.erreurs.join(', '));
		// Retourner les données brutes nettoyées au minimum
		return {
			...data,
			categorie: SYNONYMES_EVENEMENTS.categorie[String(data.categorie).toLowerCase()] || data.categorie || 'social',
			participants: Array.isArray(data.participants) ? data.participants : [],
		};
	}

	return result.data;
}

// ============================================================================
// SCHÉMAS ZOD - OPÉRATIONS KG (validation sortie Haiku)
// ============================================================================

const TYPES_ENTITES = ['personnage', 'lieu', 'objet', 'organisation', 'arc_narratif', 'ia', 'protagoniste'];

const TYPES_RELATIONS = [
	'connait', 'ami_de', 'famille_de', 'collegue_de', 'superieur_de', 'subordonne_de',
	'en_couple_avec', 'ex_de', 'interesse_par', 'rival_de', 'ennemi_de', 'mefiant_envers',
	'habite', 'travaille_a', 'frequente', 'a_visite', 'evite',
	'employe_de', 'membre_de', 'dirige', 'a_quitte', 'client_de',
	'possede', 'veut', 'a_perdu', 'a_prete_a', 'a_emprunte_a',
	'implique_dans', 'situe_dans', 'connecte_a', 'proche_de', 'appartient_a', 'siege_de',
	'partenaire_de', 'concurrent_de', 'filiale_de', 'assiste',
	'a_aide', 'doit_service_a', 'a_promis_a'
];

/**
 * Synonymes pour les noms d'opérations (si Haiku anglicise)
 */
const SYNONYMES_OPERATIONS = {
	'CREATE_ENTITY': 'CREER_ENTITE',
	'CREATE_ENTITE': 'CREER_ENTITE',
	'CREER_ENTITY': 'CREER_ENTITE',
	'MODIFY_ENTITY': 'MODIFIER_ENTITE',
	'UPDATE_ENTITY': 'MODIFIER_ENTITE',
	'UPDATE_ENTITE': 'MODIFIER_ENTITE',
	'DELETE_ENTITY': 'SUPPRIMER_ENTITE',
	'DELETE_ENTITE': 'SUPPRIMER_ENTITE',
	'REMOVE_ENTITE': 'SUPPRIMER_ENTITE',
	'CREATE_RELATION': 'CREER_RELATION',
	'ADD_RELATION': 'CREER_RELATION',
	'MODIFY_RELATION': 'MODIFIER_RELATION',
	'UPDATE_RELATION': 'MODIFIER_RELATION',
	'END_RELATION': 'TERMINER_RELATION',
	'DELETE_RELATION': 'TERMINER_RELATION',
	'REMOVE_RELATION': 'TERMINER_RELATION',
	'MODIFY_STATE': 'MODIFIER_ETAT',
	'UPDATE_STATE': 'MODIFIER_ETAT',
	'SET_STATE': 'MODIFIER_ETAT',
	'SET_ETAT': 'MODIFIER_ETAT',
	'CREATE_EVENT': 'CREER_EVENEMENT',
	'ADD_EVENT': 'CREER_EVENEMENT',
	'PLAN_EVENT': 'PLANIFIER_EVENEMENT',
	'SCHEDULE_EVENT': 'PLANIFIER_EVENEMENT',
	'PLANIFIER_EVENT': 'PLANIFIER_EVENEMENT',
	'COMPLETE_EVENT': 'REALISER_EVENEMENT',
	'CANCEL_EVENT': 'ANNULER_EVENEMENT',
};

/**
 * Normalise le nom d'opération
 */
function normaliserNomOperation(op) {
	if (!op) return op;
	const opUpper = op.toUpperCase().trim();
	return SYNONYMES_OPERATIONS[opUpper] || opUpper;
}

// --- Schémas individuels par opération ---

const CreerEntiteSchema = z.object({
	op: z.literal('CREER_ENTITE'),
	type: z.enum(TYPES_ENTITES),
	nom: z.string().min(1, "Nom requis").transform(s => s.trim()),
	// visible/background pour épistémologie
	visible: z.record(z.any()).optional(),
	background: z.record(z.any()).optional(),
	alias: z.preprocess(versTableau, z.array(z.string()).default([])),
	confirme: z.boolean().default(true),
});

const ModifierEntiteSchema = z.object({
	op: z.literal('MODIFIER_ENTITE'),
	entite: z.string().min(1, "Entité requise").transform(s => s.trim()),
	nouveau_nom: z.string().optional(),
	alias_ajouter: z.preprocess(versTableau, z.array(z.string()).default([])),
	// visible/background pour épistémologie
	visible: z.record(z.any()).optional(),
	background: z.record(z.any()).optional(),
	confirme: z.boolean().optional(),
});

const SupprimerEntiteSchema = z.object({
	op: z.literal('SUPPRIMER_ENTITE'),
	entite: z.string().min(1, "Entité requise").transform(s => s.trim()),
	raison: z.string().optional(),
});

const CreerRelationSchema = z.object({
	op: z.literal('CREER_RELATION'),
	source: z.string().min(1, "Source requise").transform(s => s.trim()),
	cible: z.string().min(1, "Cible requise").transform(s => s.trim()),
	type: z.enum(TYPES_RELATIONS),
	proprietes: z.record(z.any()).default({}),
	source_type: z.enum(TYPES_ENTITES).optional(),
	cible_type: z.enum(TYPES_ENTITES).optional(),
	certitude: z.enum(['certain', 'croit', 'soupconne', 'rumeur']).default('certain'),
	verite: z.boolean().default(true),
	source_info: z.string().optional(),
});

const ModifierRelationSchema = z.object({
	op: z.literal('MODIFIER_RELATION'),
	source: z.string().min(1).transform(s => s.trim()),
	cible: z.string().min(1).transform(s => s.trim()),
	type: z.enum(TYPES_RELATIONS),
	proprietes: z.record(z.any()).default({}),
	certitude: z.enum(['certain', 'croit', 'soupconne', 'rumeur']).optional(),
	verite: z.boolean().optional(),
});

const TerminerRelationSchema = z.object({
	op: z.literal('TERMINER_RELATION'),
	source: z.string().min(1).transform(s => s.trim()),
	cible: z.string().min(1).transform(s => s.trim()),
	type: z.enum(TYPES_RELATIONS),
	raison: z.string().optional(),
});

const ModifierEtatSchema = z.object({
	op: z.literal('MODIFIER_ETAT'),
	entite: z.string().min(1, "Entité requise").transform(s => s.trim()),
	attribut: z.string().min(1).transform(s => s.toLowerCase().trim()),
	valeur: z.union([z.string(), z.number()]),
	details: z.record(z.any()).optional(),
	certitude: z.enum(['certain', 'croit', 'soupconne', 'rumeur']).default('certain'),
	verite: z.boolean().default(true),
});

const CreerEvenementSchema = z.object({
	op: z.literal('CREER_EVENEMENT'),
	titre: z.string().min(1, "Titre requis").transform(s => s.trim()),
	categorie: z.preprocess(
		v => SYNONYMES_EVENEMENTS.categorie[String(v).toLowerCase()] || v,
		z.enum(CATEGORIES_EVENEMENT).default('social')
	),
	description: z.string().optional(),
	cycle: z.preprocess(extraireNombre, z.number()).optional(),
	heure: z.string()
		.regex(/^\d{1,2}h\d{2}$/)
		.optional()
		.or(z.literal(''))
		.transform(v => v || undefined),
	lieu: z.string().optional(),
	participants: z.preprocess(versTableau, z.array(z.string()).default([])),
	montant: z.preprocess(extraireNombre, z.number()).optional(),
	certitude: z.enum(['certain', 'croit', 'soupconne', 'rumeur']).default('certain'),
	verite: z.boolean().default(true),
});

const PlanifierEvenementSchema = z.object({
	op: z.literal('PLANIFIER_EVENEMENT'),
	titre: z.string().min(1, "Titre requis").transform(s => s.trim()),
	categorie: z.preprocess(
		v => SYNONYMES_EVENEMENTS.categorie[String(v).toLowerCase()] || v,
		z.enum(CATEGORIES_EVENEMENT).default('social')
	),
	description: z.string().optional(),
	cycle_prevu: z.preprocess(extraireNombre, z.number().min(1, "cycle_prevu requis")),
	heure: z.string()
		.regex(/^\d{1,2}h\d{2}$/)
		.optional()
		.or(z.literal(''))
		.transform(v => v || undefined),
	lieu: z.string().optional(),
	participants: z.preprocess(versTableau, z.array(z.string()).default([])),
	recurrence: RecurrenceSchema.optional(),
});

const RealiserEvenementSchema = z.object({
	op: z.literal('REALISER_EVENEMENT'),
	titre: z.string().min(1).transform(s => s.trim()),
});

const AnnulerEvenementSchema = z.object({
	op: z.literal('ANNULER_EVENEMENT'),
	titre: z.string().min(1).transform(s => s.trim()),
	raison: z.string().optional(),
});

// --- Map des schémas par opération ---
const SCHEMAS_OPERATIONS = {
	'CREER_ENTITE': CreerEntiteSchema,
	'MODIFIER_ENTITE': ModifierEntiteSchema,
	'SUPPRIMER_ENTITE': SupprimerEntiteSchema,
	'CREER_RELATION': CreerRelationSchema,
	'MODIFIER_RELATION': ModifierRelationSchema,
	'TERMINER_RELATION': TerminerRelationSchema,
	'MODIFIER_ETAT': ModifierEtatSchema,
	'CREER_EVENEMENT': CreerEvenementSchema,
	'PLANIFIER_EVENEMENT': PlanifierEvenementSchema,
	'REALISER_EVENEMENT': RealiserEvenementSchema,
	'ANNULER_EVENEMENT': AnnulerEvenementSchema,
};

/**
 * Valide et normalise une opération KG
 * @returns {{ success: boolean, data?: object, erreur?: string }}
 */
export function validerOperation(operation) {
	if (!operation || typeof operation !== 'object') {
		return { success: false, erreur: 'Opération invalide (null ou non-objet)' };
	}

	// Normaliser le nom d'opération
	const opName = normaliserNomOperation(operation.op);

	if (!opName) {
		return { success: false, erreur: 'Opération sans nom' };
	}

	const schema = SCHEMAS_OPERATIONS[opName];

	if (!schema) {
		return { success: false, erreur: `Opération inconnue: ${opName}` };
	}

	// Préparer l'opération avec le nom normalisé
	const opNormalisee = {
		...operation,
		op: opName,
	};

	const result = schema.safeParse(opNormalisee);

	if (!result.success) {
		const erreurs = result.error.issues.map(i => `${i.path.join('.')}: ${i.message}`);
		return {
			success: false,
			erreur: erreurs.join(', '),
			operationOriginale: operation,
		};
	}

	return { success: true, data: result.data };
}

/**
 * Valide et filtre une liste d'opérations
 * @returns {{ valides: object[], invalides: { op: object, erreur: string }[] }}
 */
export function validerOperations(operations) {
	if (!Array.isArray(operations)) {
		return { valides: [], invalides: [] };
	}

	const valides = [];
	const invalides = [];

	for (const op of operations) {
		const result = validerOperation(op);
		if (result.success) {
			valides.push(result.data);
		} else {
			invalides.push({
				op: op,
				erreur: result.erreur
			});
		}
	}

	return { valides, invalides };
}

// ============================================================================
// EXPORTS
// ============================================================================

/**
 * Fusionne visible + background
 * Retourne les propriétés complètes pour kg_entites
 */
export function fusionnerProprietesEntite(operation) {
	return {
		...(operation.background || {}),
		...(operation.visible || {}),
	};
}

/**
 * Extrait uniquement les propriétés visibles (pour kg_connaissances)
 */
export function extraireProprietesVisibles(operation) {
	if (operation.visible) {
		return operation.visible;
	}
	return {};
}

export { TYPES_ENTITES, TYPES_RELATIONS, CATEGORIES_EVENEMENT };
