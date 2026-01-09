/**
 * LDVELH - Game State Utilities (Frontend)
 * 
 * Version simplifiée : le serveur Python fait la normalisation.
 * Ce fichier ne fait que du merge local pour les updates SSE.
 */

// ============================================================================
// CONSTANTES (copie des valeurs Python pour fallback)
// ============================================================================

export const STATS_DEFAUT = {
	energie: 3.0,
	moral: 3.0,
	sante: 4.0,
	credits: 1400
};

// ============================================================================
// VALIDATION SIMPLE
// ============================================================================

/**
 * Vérifie si un état est valide (vient du serveur Python normalisé)
 */
export function isValidGameState(state) {
	if (!state) return false;
	// Le serveur renvoie toujours { partie, valentin, ia }
	return state.partie !== undefined || state.valentin !== undefined;
}

/**
 * Normalise un état (no-op si déjà normalisé par le serveur)
 * Garde la compatibilité avec le code existant
 */
export function normalizeGameState(state) {
	if (!state) return null;

	// Si c'est un état complet du serveur, le retourner tel quel
	if (state.partie !== undefined || state.valentin !== undefined) {
		return {
			partie: state.partie || null,
			valentin: state.valentin || { ...STATS_DEFAUT, inventaire: [] },
			ia: state.ia || null
		};
	}

	// Si c'est un update partiel (ex: { heure: "08:00" })
	// Le wrapper pour merge
	return {
		partie: extractPartieFields(state),
		valentin: extractValentinFields(state),
		ia: null
	};
}

// ============================================================================
// MERGE HELPERS (pour updates SSE partiels)
// ============================================================================

/**
 * Fusionne deux états de jeu
 * Utilisé quand le serveur envoie un update partiel via SSE
 */
export function mergeGameStates(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		partie: mergeObjects(prev.partie, next.partie),
		valentin: mergeValentin(prev.valentin, next.valentin),
		ia: mergeObjects(prev.ia, next.ia)
	};
}

/**
 * Merge spécial pour Valentin (l'inventaire est toujours remplacé)
 */
function mergeValentin(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		energie: next.energie ?? prev.energie,
		moral: next.moral ?? prev.moral,
		sante: next.sante ?? prev.sante,
		credits: next.credits ?? prev.credits,
		// L'inventaire vient du serveur, toujours le remplacer
		inventaire: next.inventaire !== undefined ? next.inventaire : prev.inventaire
	};
}

/**
 * Merge générique d'objets (ignore les null/undefined)
 */
function mergeObjects(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	const result = { ...prev };
	for (const [key, value] of Object.entries(next)) {
		if (value !== null && value !== undefined) {
			result[key] = value;
		}
	}
	return result;
}

// ============================================================================
// EXTRACTEURS (pour updates partiels non structurés)
// ============================================================================

const PARTIE_KEYS = [
	'id', 'nom', 'heure', 'lieu_actuel', 'pnjs_presents',
	'cycle_actuel', 'jour', 'date_jeu', 'status'
];

const VALENTIN_KEYS = [
	'energie', 'moral', 'sante', 'credits', 'inventaire'
];

function extractPartieFields(obj) {
	const result = {};
	let hasFields = false;

	for (const key of PARTIE_KEYS) {
		if (key in obj) {
			result[key] = obj[key];
			hasFields = true;
		}
	}

	return hasFields ? result : null;
}

function extractValentinFields(obj) {
	const result = {};
	let hasFields = false;

	for (const key of VALENTIN_KEYS) {
		if (key in obj) {
			result[key] = obj[key];
			hasFields = true;
		}
	}

	return hasFields ? result : null;
}
