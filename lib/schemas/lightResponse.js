/**
 * Schéma Zod pour les réponses Claude en mode LIGHT (messages normaux)
 */

import { z } from 'zod';
import {
	HeureSchema,
	ChoixSchema,
	ChangementRelationSchema,
	TransactionSchema,
	DeltasValentinSchema,
	NouveauJourSchema
} from './common.js';

// ============================================================================
// SCHÉMA PRINCIPAL
// ============================================================================

export const LightResponseSchema = z.object({
	// === OBLIGATOIRES ===
	lieu_actuel: z.string().min(1, "lieu_actuel requis"),
	narratif: z.string().min(1, "narratif requis"),
	heure: HeureSchema,
	choix: ChoixSchema,

	// === OPTIONNELS AVEC DEFAULTS ===
	pnjs_presents: z.array(z.string()).default([]),
	changements_relation: z.array(ChangementRelationSchema).default([]),
	transactions: z.array(TransactionSchema).default([]),
	deltas_valentin: DeltasValentinSchema,

	// === NOUVEAU CYCLE ===
	nouveau_cycle: z.boolean().default(false),
	nouveau_jour: NouveauJourSchema.optional()

}).refine(
	(data) => !data.nouveau_cycle || data.nouveau_jour,
	{
		message: "nouveau_jour requis si nouveau_cycle est true",
		path: ['nouveau_jour']
	}
);

// ============================================================================
// VALEURS PAR DÉFAUT
// ============================================================================

export const LIGHT_DEFAULTS = {
	pnjs_presents: [],
	changements_relation: [],
	transactions: [],
	deltas_valentin: { energie: 0, moral: 0, sante: 0 },
	nouveau_cycle: false
};

// ============================================================================
// VALIDATION
// ============================================================================

/**
 * Valide une réponse light avec tentative de réparation
 * @param {object} data - Données brutes parsées
 * @returns {{ success: boolean, data?: object, errors?: string[], warnings?: string[] }}
 */
export function validateLightResponse(data) {
	if (!data || typeof data !== 'object') {
		return {
			success: false,
			errors: ['Données invalides ou manquantes']
		};
	}

	// Tentative directe
	const result = LightResponseSchema.safeParse(data);

	if (result.success) {
		return { success: true, data: result.data };
	}

	// Tentative avec defaults
	const withDefaults = { ...LIGHT_DEFAULTS, ...data };
	const repairedResult = LightResponseSchema.safeParse(withDefaults);

	if (repairedResult.success) {
		const warnings = result.error.errors.map(
			e => `${e.path.join('.')}: ${e.message}`
		);
		return {
			success: true,
			data: repairedResult.data,
			warnings
		};
	}

	// Échec définitif
	const errors = result.error.errors.map(
		e => `${e.path.join('.')}: ${e.message}`
	);

	return { success: false, errors, partialData: data };
}

// ============================================================================
// VALIDATION PARTIELLE (streaming)
// ============================================================================

/**
 * Vérifie si les champs minimaux sont présents (pour streaming)
 */
export function hasMinimalLightFields(data) {
	return !!(
		data?.narratif &&
		data?.lieu_actuel &&
		data?.heure
	);
}

/**
 * Extrait les champs affichables même si validation incomplète
 */
export function extractDisplayableLight(data) {
	if (!data) return null;

	return {
		narratif: data.narratif || null,
		heure: data.heure || null,
		lieu_actuel: data.lieu_actuel || null,
		choix: Array.isArray(data.choix) ? data.choix : [],
		pnjs_presents: Array.isArray(data.pnjs_presents) ? data.pnjs_presents : []
	};
}
