/**
 * Parsing et validation des réponses Claude
 */

import { validateLightResponse, hasMinimalLightFields, } from '../schemas/lightResponse.js';
import { validateInitResponse, hasMinimalInitFields } from '../schemas/initResponse.js';

// ============================================================================
// EXTRACTION JSON
// ============================================================================

/**
 * Tente de parser une string JSON avec réparation
 * @param {string} jsonStr - String JSON brute
 * @returns {object|null}
 */
export function tryParseJSON(jsonStr) {
	if (!jsonStr || typeof jsonStr !== 'string') return null;

	let cleaned = jsonStr.trim();

	// Nettoyer les backticks markdown
	if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
	if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
	if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
	cleaned = cleaned.trim();

	// Trouver le premier {
	const firstBrace = cleaned.indexOf('{');
	if (firstBrace > 0) cleaned = cleaned.slice(firstBrace);
	else if (firstBrace === -1) return null;

	// Tentative directe
	try {
		return JSON.parse(cleaned);
	} catch (e) {
		// Continuer avec réparation
	}

	// Réparation : analyse syntaxique
	return tryRepairJSON(cleaned);
}

/**
 * Tente de réparer un JSON malformé
 */
function tryRepairJSON(str) {
	let lastValidIndex = -1;
	let braceCount = 0;
	let inString = false;
	let escapeNext = false;

	for (let i = 0; i < str.length; i++) {
		const char = str[i];

		if (escapeNext) {
			escapeNext = false;
			continue;
		}

		if (char === '\\' && inString) {
			escapeNext = true;
			continue;
		}

		if (char === '"' && !escapeNext) {
			inString = !inString;
			continue;
		}

		if (!inString) {
			if (char === '{') braceCount++;
			if (char === '}') {
				braceCount--;
				if (braceCount === 0) lastValidIndex = i;
			}
		}
	}

	// Tenter avec la partie valide trouvée
	if (lastValidIndex > 0) {
		try {
			return JSON.parse(str.slice(0, lastValidIndex + 1));
		} catch (e) {
			// Continuer
		}
	}

	// Fermer les accolades manquantes
	let fixed = str;
	if (inString) fixed += '"';
	while (braceCount > 0) {
		fixed += '}';
		braceCount--;
	}

	try {
		return JSON.parse(fixed);
	} catch (e) {
		return null;
	}
}

/**
 * Extrait le JSON d'un contenu qui peut avoir du texte autour
 */
export function extractJSON(content) {
	if (!content) return null;

	const trimmed = content.trim();

	// Commence par { → parse direct
	if (trimmed.startsWith('{')) {
		return tryParseJSON(content);
	}

	// Chercher un JSON après une nouvelle ligne
	const lastBraceIndex = content.lastIndexOf('\n{');
	if (lastBraceIndex > 0) {
		const result = tryParseJSON(content.slice(lastBraceIndex + 1));
		if (result) return result;
	}

	// Chercher le premier { dans le contenu
	const firstBraceIndex = content.indexOf('{');
	if (firstBraceIndex >= 0) {
		return tryParseJSON(content.slice(firstBraceIndex));
	}

	return null;
}

// ============================================================================
// VALIDATION COMBINÉE
// ============================================================================

/**
 * Parse et valide une réponse Claude complète
 * @param {string} content - Contenu brut de Claude
 * @param {'init' | 'light'} mode - Mode de validation
 * @returns {{ 
 *   success: boolean, 
 *   parsed: object|null, 
 *   errors: string[], 
 *   warnings: string[],
 *   rawParsed: object|null 
 * }}
 */
export function parseAndValidate(content, mode) {
	const result = {
		success: false,
		parsed: null,
		errors: [],
		warnings: [],
		rawParsed: null
	};

	// 1. Extraction JSON
	const rawParsed = extractJSON(content);
	result.rawParsed = rawParsed;

	if (!rawParsed) {
		result.errors.push('Impossible de parser le JSON de la réponse');
		return result;
	}

	// 2. Validation selon le mode
	const validation = mode === 'init'
		? validateInitResponse(rawParsed)
		: validateLightResponse(rawParsed);

	if (validation.success) {
		result.success = true;
		result.parsed = validation.data;
		result.warnings = validation.warnings || [];
	} else {
		result.errors = validation.errors || [];
		// Garder le parsed brut pour affichage dégradé
		result.parsed = rawParsed;
	}

	return result;
}

// ============================================================================
// VÉRIFICATION STREAMING
// ============================================================================

/**
 * Vérifie si le JSON partiel a les champs minimaux
 */
export function hasMinimalFields(jsonStr, mode) {
	const partial = extractJSON(jsonStr);
	if (!partial) return false;

	return mode === 'init'
		? hasMinimalInitFields(partial)
		: hasMinimalLightFields(partial);
}

/**
 * Détecte une structure JSON suspecte pendant le streaming
 */
export function detectSuspiciousStructure(jsonStr, expectedMode) {
	// Pas assez de contenu pour juger
	if (jsonStr.length < 100) return false;

	// Manque le champ narratif après 500 chars
	if (jsonStr.length > 500 && !jsonStr.includes('"narratif"')) {
		return true;
	}

	// Mode init mais manque les champs requis
	if (expectedMode === 'init' && jsonStr.length > 1000) {
		if (!jsonStr.includes('"monde"') && !jsonStr.includes('"ia"')) {
			return true;
		}
	}

	return false;
}
