/**
 * Schéma Zod pour les réponses Claude en mode INIT (nouvelle partie)
 */

import { z } from 'zod';
import {
	HeureSchema,
	ChoixSchema,
	MondeSchema,
	EmployeurSchema,
	ValentinInitSchema,
	IASchema,
	PnjInitialSchema,
	LieuInitialSchema,
	ArcPotentielSchema
} from './common.js';

// ============================================================================
// SCHÉMA PRINCIPAL
// ============================================================================

export const InitResponseSchema = z.object({
	// === SCÈNE ===
	heure: HeureSchema,
	lieu_actuel: z.string().min(1, "lieu_actuel requis"),
	narratif: z.string().min(10, "narratif trop court"),
	choix: ChoixSchema,
	pnjs_presents: z.array(z.string()).default([]),

	// === TEMPORALITÉ ===
	cycle: z.number().positive().default(1),
	jour: z.string().min(1, "jour requis"),
	date_jeu: z.string().min(1, "date_jeu requise"),

	// === MONDE ===
	monde: MondeSchema,
	employeur: EmployeurSchema,

	// === PERSONNAGES ===
	valentin: ValentinInitSchema,
	ia: IASchema,

	// === LISTES ===
	pnj_initiaux: z.array(PnjInitialSchema)
		.min(1, "Au moins 1 PNJ requis"),
	lieux_initiaux: z.array(LieuInitialSchema)
		.min(1, "Au moins 1 lieu requis"),
	arcs_potentiels: z.array(ArcPotentielSchema).default([])
});

// ============================================================================
// VALEURS PAR DÉFAUT
// ============================================================================

export const INIT_DEFAULTS = {
	cycle: 1,
	pnjs_presents: [],
	arcs_potentiels: []
};

// ============================================================================
// VALIDATION
// ============================================================================

/**
 * Valide une réponse init avec tentative de réparation
 * @param {object} data - Données brutes parsées
 * @returns {{ success: boolean, data?: object, errors?: string[], warnings?: string[] }}
 */
export function validateInitResponse(data) {
	if (!data || typeof data !== 'object') {
		return {
			success: false,
			errors: ['Données invalides ou manquantes']
		};
	}

	// Tentative directe
	const result = InitResponseSchema.safeParse(data);

	if (result.success) {
		return { success: true, data: result.data };
	}

	// Tentative avec defaults
	const withDefaults = { ...INIT_DEFAULTS, ...data };
	const repairedResult = InitResponseSchema.safeParse(withDefaults);

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
 * Vérifie si les champs minimaux sont présents
 */
export function hasMinimalInitFields(data) {
	return !!(
		data?.narratif &&
		data?.lieu_actuel &&
		data?.monde?.nom &&
		data?.ia?.nom
	);
}

/**
 * Vérifie la présence de Justine (PNJ obligatoire)
 */
export function hasJustine(data) {
	if (!Array.isArray(data?.pnj_initiaux)) return false;
	return data.pnj_initiaux.some(
		pnj => pnj.nom?.toLowerCase().includes('justine')
	);
}

/**
 * Valide la cohérence des PNJ
 */
export function validatePnjCoherence(data) {
	const warnings = [];

	if (!Array.isArray(data?.pnj_initiaux)) return warnings;

	for (const pnj of data.pnj_initiaux) {
		// Vérifier âge pour intérêt romantique
		if (pnj.sexe === 'F' && pnj.age >= 25 && pnj.age <= 45) {
			// OK, intérêt romantique potentiel
		}

		// Vérifier domicile référence un lieu connu
		if (pnj.domicile) {
			const lieuExists = data.lieux_initiaux?.some(
				l => l.nom.toLowerCase() === pnj.domicile.toLowerCase()
			);
			if (!lieuExists) {
				warnings.push(`Domicile "${pnj.domicile}" de ${pnj.nom} non trouvé dans lieux_initiaux`);
			}
		}
	}

	return warnings;
}
