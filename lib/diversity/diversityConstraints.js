/**
 * Générateur de contraintes de diversité pour l'init
 */

import {
	EXCLUSIONS,
	ORIGINES,
	STYLES_STATION,
	CONTRAINTES_PNJ,
	LETTRES_INTERESSANTES
} from './nameBank.js';

// ============================================================================
// HELPERS
// ============================================================================

function pickRandom(array) {
	return array[Math.floor(Math.random() * array.length)];
}

function pickMultiple(array, count) {
	const shuffled = [...array].sort(() => Math.random() - 0.5);
	return shuffled.slice(0, count);
}

function coinFlip(probability = 0.5) {
	return Math.random() < probability;
}

// ============================================================================
// GÉNÉRATION DES CONTRAINTES
// ============================================================================

/**
 * Génère les contraintes de diversité pour une nouvelle partie
 * @returns {object} Contraintes à injecter dans le prompt
 */
export function generateDiversityConstraints() {
	const constraints = {
		ia: generateIAConstraints(),
		station: generateStationConstraints(),
		pnj: generatePNJConstraints(),
		exclusions: EXCLUSIONS
	};

	return constraints;
}

/**
 * Contraintes pour le nom de l'IA
 */
function generateIAConstraints() {
	const origine = pickRandom(ORIGINES);
	const lettre = pickRandom(LETTRES_INTERESSANTES);

	// 50% chance d'imposer une lettre initiale
	const avecLettre = coinFlip(0.5);

	return {
		origine: origine.code,
		origineLabel: origine.label,
		exemples: pickMultiple(origine.exemples, 3),
		lettreInitiale: avecLettre ? lettre : null,
		style: pickRandom([
			'un prénom humain rare et ancien',
			'un prénom humain peu courant dans la SF',
			'un prénom qui sonne doux mais pas mièvre',
			'un prénom avec une sonorité inhabituelle'
		])
	};
}

/**
 * Contraintes pour le nom de la station
 */
function generateStationConstraints() {
	const style = pickRandom(STYLES_STATION);

	return {
		style: style.code,
		styleLabel: style.label,
		exemples: style.exemples,
		// Éviter les noms "spatiaux" génériques
		interdits: ['tout nom évoquant les étoiles, galaxies, cosmos, nébuleuses']
	};
}

/**
 * Contraintes pour les PNJ
 */
function generatePNJConstraints() {
	// Piocher 2-3 contraintes de diversité obligatoires
	const contraintesObligatoires = pickMultiple(CONTRAINTES_PNJ, 2);

	// Origines culturelles variées pour les noms
	const originesPnj = pickMultiple(ORIGINES, 3);

	return {
		diversiteObligatoire: contraintesObligatoires.map(c => ({
			type: c.type,
			valeur: pickRandom(c.options)
		})),
		originesSuggérées: originesPnj.map(o => o.code),
		nombreMinAliens: coinFlip(0.7) ? 1 : 2, // 1 ou 2 aliens minimum
		ageVarié: true // Au moins un PNJ de chaque tranche d'âge
	};
}

// ============================================================================
// FORMATAGE POUR LE PROMPT
// ============================================================================

/**
 * Formate les contraintes en texte pour injection dans le prompt
 */
export function formatConstraintsForPrompt(constraints) {
	let text = `\n\n---\n\n## CONTRAINTES DE DIVERSITÉ (OBLIGATOIRES)\n\n`;

	text += `- RESPECTE IMPÉRATIVEMENT les contraintes de diversité fournies\n`
	text += `- Les noms interdits ne doivent JAMAIS apparaître, même partiellement\n`
	text += `- Si une lettre initiale est imposée pour l'IA, le nom DOIT commencer par cette lettre\n`;

	// IA
	text += `### Nom de l'IA\n`;
	text += `- Style : ${constraints.ia.style}\n`;
	text += `- Origine culturelle imposée : ${constraints.ia.origineLabel}\n`;
	text += `- Exemples de cette origine : ${constraints.ia.exemples.join(', ')}\n`;
	if (constraints.ia.lettreInitiale) {
		text += `- DOIT commencer par la lettre : ${constraints.ia.lettreInitiale}\n`;
	}
	text += `- INTERDIT : ${constraints.exclusions.ia.slice(0, 10).join(', ')}...\n\n`;

	// Station
	text += `### Nom de la station/habitat\n`;
	text += `- Style imposé : ${constraints.station.styleLabel}\n`;
	text += `- Exemples de ce style : ${constraints.station.exemples.join(', ')}\n`;
	text += `- INTERDIT : ${constraints.exclusions.station.slice(0, 8).join(', ')}...\n`;
	text += `- ÉVITER : ${constraints.station.interdits.join(', ')}\n\n`;

	// PNJ
	text += `### Diversité des PNJ\n`;
	text += `- Minimum ${constraints.pnj.nombreMinAliens} personnage(s) non-humain(s)\n`;
	text += `- Origines culturelles à privilégier pour les noms : ${constraints.pnj.originesSuggérées.join(', ')}\n`;
	text += `- INTERDIT comme prénoms : ${constraints.exclusions.pnj_prenoms.join(', ')}\n`;
	text += `- Contraintes obligatoires :\n`;
	for (const c of constraints.pnj.diversiteObligatoire) {
		text += `  • Au moins un PNJ : ${c.valeur}\n`;
	}

	// Lieux
	text += `\n### Noms de lieux\n`;
	text += `- INTERDIT : ${constraints.exclusions.lieux.join(', ')}\n`;
	text += `- Privilégier des noms réalistes, vernaculaires, ou fonctionnels\n`;

	return text;
}

// ============================================================================
// EXPORT COMBINÉ
// ============================================================================

/**
 * Génère et formate les contraintes en une seule fonction
 * @returns {{ constraints: object, promptText: string }}
 */
export function generateAndFormatConstraints() {
	const constraints = generateDiversityConstraints();
	const promptText = formatConstraintsForPrompt(constraints);

	return { constraints, promptText };
}
