// progressUtils.js

// Poids recalculés selon votre JSON d'exemple (~12000 caractères total)
// Order based on observed LLM generation sequence
export const GENERATION_STEPS = [
	{ key: 'companion', label: 'Compagnon', weight: 4 },
	{ key: 'inventory', label: 'Inventaire', weight: 8 },
	{ key: 'locations', label: 'Lieux', weight: 18 },
	{ key: 'characters', label: 'Personnages', weight: 28 },
	{ key: 'protagonist', label: 'Protagoniste', weight: 6 },
	{ key: 'arrival_event', label: 'Arrivée', weight: 6 },
	{ key: 'organizations', label: 'Organisations', weight: 6 },
	{ key: 'narrative_arcs', label: 'Arcs narratifs', weight: 10 },
	{ key: 'initial_relations', label: 'Relations', weight: 14 },
];

/**
 * Vérifie si une section JSON est complète (accolades/crochets équilibrés)
 */
export function isSectionComplete(json, key) {
	const regex = new RegExp(`"${key}"\\s*:\\s*`);
	const match = json.match(regex);
	if (!match) return false;

	const startIndex = match.index + match[0].length;
	const startChar = json[startIndex];

	if (startChar !== '{' && startChar !== '[') {
		// Valeur simple (string, number, etc.) - considérée complète si suivie de virgule ou }
		const afterValue = json.slice(startIndex).match(/^[^,}\]]+[,}\]]/);
		return !!afterValue;
	}

	const closeChar = startChar === '{' ? '}' : ']';
	let depth = 0;
	let inString = false;
	let escapeNext = false;

	for (let i = startIndex; i < json.length; i++) {
		const char = json[i];

		if (escapeNext) { escapeNext = false; continue; }
		if (char === '\\' && inString) { escapeNext = true; continue; }
		if (char === '"') { inString = !inString; continue; }
		if (inString) continue;

		if (char === '{' || char === '[') depth++;
		if (char === '}' || char === ']') depth--;

		if (depth === 0) return true;
	}

	return false;
}

/**
 * Estime la progression dans une section incomplète
 */
function estimateSectionProgress(json, key) {
	const regex = new RegExp(`"${key}"\\s*:\\s*`);
	const match = json.match(regex);
	if (!match) return 0;

	const startIndex = match.index + match[0].length;
	const remaining = json.slice(startIndex);

	// Compte les éléments dans un tableau (pour characters, locations, etc.)
	if (remaining.startsWith('[')) {
		const closedObjects = (remaining.match(/\}\s*,/g) || []).length;
		// Estimation : chaque objet fermé = progression partielle
		// On plafonne à 0.8 car la section n'est pas fermée
		return Math.min(0.8, closedObjects * 0.15);
	}

	// Pour un objet simple, on estime par la profondeur
	return 0.5;
}

// Director sub-step progress mapping (75-100% range)
const DIRECTOR_PROGRESS = {
	'Tension narrative': 78,
	'Intentions PNJ': 85,
	'Événements': 92,
	'Vision globale': 97,
};

/**
 * Calcule la progression totale (JSON stream 0-90% + Director 90-100%)
 */
export function calculateProgress(partialJson, isStreamComplete = false, directorStatus = null, directorLabel = null) {
	// Director sub-steps (90-100%)
	if (directorStatus === 'done') return 100;
	if (directorStatus === 'running') {
		return DIRECTOR_PROGRESS[directorLabel] || 76;
	}

	// JSON stream (0-90%)
	if (!partialJson) return 0;

	let progress = 0;

	for (const step of GENERATION_STEPS) {
		const keyExists = new RegExp(`"${step.key}"\\s*:`).test(partialJson);

		if (keyExists) {
			if (isSectionComplete(partialJson, step.key)) {
				progress += step.weight;
			} else {
				const partial = estimateSectionProgress(partialJson, step.key);
				progress += step.weight * partial;
			}
		}
	}

	// Scale to 0-75% range, cap at 75% until Director takes over
	const scaled = Math.round(progress * 0.75);
	if (!isStreamComplete) {
		return Math.min(scaled, 74);
	}

	return Math.min(scaled, 75);
}

/**
 * Retourne l'étape actuellement en cours
 */
export function getCurrentStep(partialJson) {
	if (!partialJson) return GENERATION_STEPS[0];

	let currentStep = GENERATION_STEPS[0];

	for (const step of GENERATION_STEPS) {
		if (new RegExp(`"${step.key}"\\s*:`).test(partialJson)) {
			currentStep = step;
			if (!isSectionComplete(partialJson, step.key)) {
				break;
			}
		}
	}

	return currentStep;
}

/**
 * Retourne le statut de chaque step : 'done', 'active', ou 'pending'
 * - done: la clé existe et la section est complète (brackets fermés)
 * - active: la clé existe mais la section est encore ouverte (en cours de stream)
 * - pending: la clé n'existe pas encore
 */
export function getStepStatuses(partialJson) {
	if (!partialJson) {
		return GENERATION_STEPS.map(step => ({ ...step, status: 'pending' }));
	}

	return GENERATION_STEPS.map(step => {
		const keyExists = new RegExp(`"${step.key}"\\s*:`).test(partialJson);
		if (!keyExists) return { ...step, status: 'pending' };
		if (isSectionComplete(partialJson, step.key)) return { ...step, status: 'done' };
		return { ...step, status: 'active' };
	});
}

/**
 * Extrait le nom du monde
 */
export function extractWorldName(partialJson) {
	if (!partialJson) return null;
	const match = partialJson.match(/"world"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"/);
	return match ? match[1] : null;
}
