/**
 * Schéma Zod pour les réponses Claude en mode INIT (World Builder)
 * 
 * NOTE: Le mode INIT ne génère plus de narratif ni de choix.
 * Il génère uniquement les données du monde + un événement d'arrivée
 * qui sera utilisé par le premier appel LIGHT pour générer le narratif.
 */

import { z } from 'zod';
import {
	MondeSchema,
	EmployeurSchema,
	ValentinInitSchema,
	IASchema,
	PnjInitialSchema,
	LieuInitialSchema,
	ArcPotentielSchema,
	InventaireItemSchema
} from './common.js';

// ============================================================================
// SCHÉMA ÉVÉNEMENT D'ARRIVÉE
// ============================================================================

const EvenementArriveeSchema = z.object({
	// Temporalité et lieu (maintenant dans l'événement)
	lieu_actuel: z.string().min(1, "lieu_actuel requis"),
	cycle: z.number().positive().default(1),
	jour: z.string().min(1, "jour requis"),
	date_jeu: z.string().min(1, "date_jeu requise"),
	heure: z.string().regex(/^\d{1,2}h\d{2}$/, "Format heure: HHhMM"),

	// Instructions pour le narrateur
	titre: z.string().min(5),
	contexte: z.string().min(20, "Contexte trop court - décris la situation d'arrivée"),
	ton: z.enum(['neutre', 'tendu', 'accueillant', 'mystérieux', 'mélancolique']).default('neutre'),
	elements_sensoriels: z.array(z.string()).min(3).max(6),
	premier_contact: z.string().nullable().default(null)
});

// ============================================================================
// SCHÉMA PRINCIPAL
// ============================================================================

export const InitResponseSchema = z.object({
	// === MONDE ===
	monde: MondeSchema,
	employeur: EmployeurSchema,

	// === PERSONNAGES ===
	valentin: ValentinInitSchema,
	ia: IASchema,

	// === ÉCONOMIE ===
	credits_initiaux: z.number().nonnegative().optional(),

	// === LISTES ===
	pnj_initiaux: z.array(PnjInitialSchema)
		.min(1, "Au moins 1 PNJ requis"),
	lieux_initiaux: z.array(LieuInitialSchema)
		.min(1, "Au moins 1 lieu requis"),
	inventaire_initial: z.array(InventaireItemSchema).default([]),

	// === ÉVÉNEMENT D'ARRIVÉE (contient lieu, cycle, jour, date, heure) ===
	evenement_arrivee: EvenementArriveeSchema,

	// === ARCS ===
	arcs_potentiels: z.array(ArcPotentielSchema).default([])
});

// ============================================================================
// VALEURS PAR DÉFAUT
// ============================================================================

export const INIT_DEFAULTS = {
	cycle: 1,
	arcs_potentiels: [],
	inventaire_initial: []
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
		// Validation de cohérence
		const coherenceWarnings = validateCoherence(result.data);
		return {
			success: true,
			data: result.data,
			warnings: coherenceWarnings.length > 0 ? coherenceWarnings : undefined
		};
	}

	// Tentative avec defaults
	const withDefaults = { ...INIT_DEFAULTS, ...data };
	const repairedResult = InitResponseSchema.safeParse(withDefaults);

	if (repairedResult.success) {
		const warnings = result.error.issues.map(
			e => `${e.path.join('.')}: ${e.message}`
		);
		const coherenceWarnings = validateCoherence(repairedResult.data);
		return {
			success: true,
			data: repairedResult.data,
			warnings: [...warnings, ...coherenceWarnings]
		};
	}

	// Échec définitif
	const errors = result.error.issues.map(
		e => `${e.path.join('.')}: ${e.message}`
	);

	return { success: false, errors, partialData: data };
}

// ============================================================================
// VALIDATION DE COHÉRENCE
// ============================================================================

/**
 * Vérifie la cohérence interne des données générées
 */
function validateCoherence(data) {
	const warnings = [];
	const pnjNoms = new Set((data.pnj_initiaux || []).map(p => p.nom.toLowerCase()));
	const lieuNoms = new Set((data.lieux_initiaux || []).map(l => l.nom.toLowerCase()));

	// 1. lieu_actuel doit exister dans lieux_initiaux
	if (data.lieu_actuel && !lieuNoms.has(data.lieu_actuel.toLowerCase())) {
		warnings.push(`lieu_actuel "${data.lieu_actuel}" non trouvé dans lieux_initiaux`);
	}

	// 2. premier_contact doit exister dans pnj_initiaux
	if (data.evenement_arrivee?.premier_contact) {
		const contact = data.evenement_arrivee.premier_contact.toLowerCase();
		if (!pnjNoms.has(contact)) {
			warnings.push(`premier_contact "${data.evenement_arrivee.premier_contact}" non trouvé dans pnj_initiaux`);
		}
	}

	// 3. pnjs_frequents doivent exister
	for (const lieu of (data.lieux_initiaux || [])) {
		for (const freq of (lieu.pnjs_frequents || [])) {
			if (!pnjNoms.has(freq.pnj.toLowerCase())) {
				warnings.push(`PNJ fréquent "${freq.pnj}" de ${lieu.nom} non trouvé dans pnj_initiaux`);
			}
		}
	}

	// 4. pnjs_impliques des arcs doivent exister
	for (const arc of (data.arcs_potentiels || [])) {
		for (const pnjNom of (arc.pnjs_impliques || [])) {
			if (!pnjNoms.has(pnjNom.toLowerCase())) {
				warnings.push(`PNJ "${pnjNom}" de l'arc "${arc.nom}" non trouvé dans pnj_initiaux`);
			}
		}
	}

	// 5. Vérifier domiciles des PNJ (optionnel, peut être générique)
	for (const pnj of (data.pnj_initiaux || [])) {
		if (pnj.domicile && !lieuNoms.has(pnj.domicile.toLowerCase())) {
			// Pas un warning bloquant, le domicile peut être générique
			// warnings.push(`Domicile "${pnj.domicile}" de ${pnj.nom} non trouvé`);
		}
	}

	return warnings;
}

// ============================================================================
// VALIDATION PARTIELLE (streaming)
// ============================================================================

/**
 * Vérifie si les champs minimaux sont présents pour considérer la réponse valide
 */
export function hasMinimalInitFields(data) {
	return !!(
		data?.monde?.nom &&
		data?.ia?.nom &&
		data?.evenement_arrivee?.lieu_actuel &&
		data?.evenement_arrivee?.contexte
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
 * Extrait les données de l'événement d'arrivée pour le premier LIGHT
 */
export function extractEvenementArrivee(data) {
	if (!data?.evenement_arrivee) return null;

	const evt = data.evenement_arrivee;
	return {
		// Temporalité et lieu
		lieu_actuel: evt.lieu_actuel,
		cycle: evt.cycle || 1,
		jour: evt.jour,
		date_jeu: evt.date_jeu,
		heure: evt.heure,

		// Instructions narrateur
		titre: evt.titre,
		contexte: evt.contexte,
		ton: evt.ton || 'neutre',
		elements_sensoriels: evt.elements_sensoriels || [],
		premier_contact: evt.premier_contact,

		// Contexte additionnel
		monde_nom: data.monde?.nom,
		ia_nom: data.ia?.nom
	};
}
