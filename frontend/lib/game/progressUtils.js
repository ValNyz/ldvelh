// progressUtils.js

// Poids recalculés selon votre JSON d'exemple (~12000 caractères total)
export const GENERATION_STEPS = [
	{ key: 'generation_seed_words', label: 'Initialisation', weight: 2 },
	{ key: 'world', label: 'Création du monde', weight: 4 },
	{ key: 'locations', label: 'Lieux', weight: 18 },
	{ key: 'organizations', label: 'Organisations', weight: 6 },
	{ key: 'protagonist', label: 'Personnage', weight: 6 },
	{ key: 'personal_ai', label: 'IA personnelle', weight: 2 },
	{ key: 'characters', label: 'Personnages', weight: 28 },
	{ key: 'inventory', label: 'Inventaire', weight: 8 },
	{ key: 'narrative_arcs', label: 'Arcs narratifs', weight: 8 },
	{ key: 'initial_relations', label: 'Relations', weight: 12 },
	{ key: 'arrival_event', label: 'Arrivée du Joueur', weight: 6 },
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

/**
 * Calcule la progression totale
 */
export function calculateProgress(partialJson, isStreamComplete = false) {
	if (!partialJson) return 0;

	let progress = 0;

	for (const step of GENERATION_STEPS) {
		const keyExists = new RegExp(`"${step.key}"\\s*:`).test(partialJson);

		if (keyExists) {
			if (isSectionComplete(partialJson, step.key)) {
				progress += step.weight;
			} else {
				// Section en cours : estimation partielle
				const partial = estimateSectionProgress(partialJson, step.key);
				progress += step.weight * partial;
			}
		}
	}

	// Plafonne à 95% tant que le stream n'est pas terminé
	if (!isStreamComplete) {
		progress = Math.min(progress, 95);
	}

	return Math.round(progress);
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
 * Extrait le nom du monde
 */
export function extractWorldName(partialJson) {
	if (!partialJson) return null;
	const match = partialJson.match(/"world"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"/);
	return match ? match[1] : null;
}
