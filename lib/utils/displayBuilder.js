/**
 * Utilitaires centralisés pour construire l'affichage
 * Évite les doublons d'heure et de choix
 */

// ============================================================================
// REGEX PATTERNS (centralisés)
// ============================================================================

// Pattern pour détecter l'heure au début d'un texte (tous formats possibles)
const HEURE_PATTERNS = [
	/^\s*\*{0,2}\[\s*\d{1,2}h\d{1,2}\s*\]\*{0,2}\s*[-–—:.]?\s*/i,  // **[10h30]** ou [10h30]
	/^\s*\*{0,2}\d{1,2}h\d{1,2}\*{0,2}\s*[-–—:.]?\s*/i,             // **10h30** ou 10h30
	/^\s*\*{0,2}\[\s*\d{1,2}:\d{2}\s*\]\*{0,2}\s*[-–—:.]?\s*/i,    // **[10:30]** ou [10:30]
	/^\s*\*{0,2}\d{1,2}:\d{2}\*{0,2}\s*[-–—:.]?\s*/i,               // **10:30** ou 10:30
];

// Pattern pour valider une heure
const HEURE_VALID_PATTERN = /^\d{1,2}h\d{2}$/i;

// ============================================================================
// NETTOYAGE DU NARRATIF
// ============================================================================

/**
 * Supprime l'heure en début de narratif (tous formats)
 * @param {string} narratif - Texte du narratif
 * @returns {string} - Narratif sans heure en début
 */
export function removeHeureFromNarratif(narratif) {
	if (!narratif || typeof narratif !== 'string') return narratif || '';

	let cleaned = narratif;

	// Essayer chaque pattern jusqu'à trouver une correspondance
	for (const pattern of HEURE_PATTERNS) {
		const match = cleaned.match(pattern);
		if (match) {
			cleaned = cleaned.slice(match[0].length);
			break; // Une seule suppression
		}
	}

	return cleaned.trim();
}

/**
 * Normalise une heure au format HHhMM
 * @param {string} heure - Heure brute
 * @returns {string|null} - Heure normalisée ou null
 */
export function normalizeHeure(heure) {
	if (!heure || typeof heure !== 'string') return null;

	const cleaned = heure.trim();

	// Déjà au bon format ?
	if (HEURE_VALID_PATTERN.test(cleaned)) {
		// Normaliser avec zéro devant si besoin (9h30 -> 09h30)
		const match = cleaned.match(/^(\d{1,2})h(\d{2})$/i);
		if (match) {
			const h = match[1].padStart(2, '0');
			const m = match[2];
			return `${h}h${m}`;
		}
	}

	// Format HH:MM ?
	const colonMatch = cleaned.match(/^(\d{1,2}):(\d{2})$/);
	if (colonMatch) {
		const h = colonMatch[1].padStart(2, '0');
		const m = colonMatch[2];
		return `${h}h${m}`;
	}

	return null;
}

// ============================================================================
// DÉDUPLICATION DES CHOIX
// ============================================================================

/**
 * Nettoie et déduplique les choix
 * @param {Array} choix - Liste des choix
 * @returns {Array} - Choix nettoyés et dédupliqués
 */
export function deduplicateChoix(choix) {
	if (!Array.isArray(choix)) return [];

	const seen = new Set();
	const result = [];

	for (const c of choix) {
		if (typeof c !== 'string') continue;

		// Normaliser pour comparaison (lowercase, sans ponctuation finale)
		const normalized = c.trim().toLowerCase().replace(/[.!?]+$/, '');

		if (normalized && !seen.has(normalized)) {
			seen.add(normalized);
			result.push(c.trim());
		}
	}

	return result;
}

// ============================================================================
// CONSTRUCTEUR D'AFFICHAGE PRINCIPAL
// ============================================================================

/**
 * Construit le texte d'affichage final avec déduplication garantie
 * @param {object} options
 * @param {string} options.narratif - Texte narratif
 * @param {string} options.heure - Heure (optionnel)
 * @param {Array} options.choix - Liste des choix (optionnel)
 * @returns {string} - Texte formaté pour affichage
 */
export function buildDisplayText({ narratif, heure, choix }) {
	if (!narratif) return null;

	let display = '';

	// 1. Nettoyer le narratif (supprimer heure en doublon)
	const cleanedNarratif = removeHeureFromNarratif(narratif);

	// 2. Ajouter l'heure normalisée au début
	const normalizedHeure = normalizeHeure(heure);
	if (normalizedHeure) {
		display = `[${normalizedHeure}] `;
	}

	// 3. Ajouter le narratif nettoyé
	display += cleanedNarratif;

	// 4. Ajouter les choix dédupliqués
	const cleanedChoix = deduplicateChoix(choix);
	if (cleanedChoix.length > 0) {
		display += '\n\n' + cleanedChoix.map((c, i) => `${i + 1}. ${c}`).join('\n');
	}

	return display;
}

// ============================================================================
// EXTRACTION DEPUIS JSON PARTIEL (STREAMING)
// ============================================================================

/**
 * Extrait le narratif d'un JSON partiel en streaming
 * @param {string} jsonStr - JSON partiel
 * @returns {string|null}
 */
export function extractNarratifFromPartial(jsonStr) {
	const match = jsonStr.match(/"narratif"\s*:\s*"/);
	if (!match) return null;

	let narratif = '';
	let i = match.index + match[0].length;

	while (i < jsonStr.length) {
		const c = jsonStr[i];
		if (c === '\\' && i + 1 < jsonStr.length) {
			const next = jsonStr[i + 1];
			switch (next) {
				case 'n': narratif += '\n'; i += 2; break;
				case '"': narratif += '"'; i += 2; break;
				case '\\': narratif += '\\'; i += 2; break;
				case 't': narratif += '\t'; i += 2; break;
				case 'r': narratif += '\r'; i += 2; break;
				default: narratif += c; i++; break;
			}
		} else if (c === '"') {
			break;
		} else {
			narratif += c;
			i++;
		}
	}

	return narratif || null;
}

/**
 * Extrait l'heure d'un JSON partiel
 * @param {string} jsonStr - JSON partiel
 * @returns {string|null}
 */
export function extractHeureFromPartial(jsonStr) {
	const match = jsonStr.match(/"heure"\s*:\s*"([^"]+)"/);
	return match ? match[1] : null;
}

/**
 * Extrait les choix d'un JSON partiel
 * @param {string} jsonStr - JSON partiel
 * @returns {Array|null}
 */
export function extractChoixFromPartial(jsonStr) {
	const match = jsonStr.match(/"choix"\s*:\s*\[([\s\S]*?)\]/);
	if (!match) return null;

	try {
		const arr = JSON.parse(`[${match[1]}]`);
		return arr.length > 0 ? arr : null;
	} catch (e) {
		return null;
	}
}

/**
 * Construit l'affichage depuis un JSON partiel (streaming)
 * Utilise la fonction centralisée buildDisplayText
 * @param {string} jsonStr - JSON partiel
 * @returns {string|null}
 */
export function buildDisplayFromPartial(jsonStr) {
	const narratif = extractNarratifFromPartial(jsonStr);
	if (!narratif) return null;

	return buildDisplayText({
		narratif,
		heure: extractHeureFromPartial(jsonStr),
		choix: extractChoixFromPartial(jsonStr)
	});
}
