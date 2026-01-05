/**
 * Schémas Zod communs partagés entre init et light
 */

import { z } from 'zod';

// ============================================================================
// PRIMITIVES
// ============================================================================

export const HeureSchema = z.string()
	.regex(/^\d{1,2}h\d{2}$/, "Format heure invalide (ex: 14h30)");

export const SexeSchema = z.enum(['F', 'M', 'A']);

export const TypeLieuSchema = z.enum([
	'commerce', 'habitat', 'travail', 'public',
	'loisir', 'transport', 'medical', 'administratif'
]);

export const TypeArcSchema = z.enum([
	'travail', 'personnel', 'romance', 'exploration',
	'mystere', 'social', 'pnj_personnel'
]);

export const TypeTransactionSchema = z.enum([
	'achat', 'vente', 'salaire', 'loyer',
	'amende', 'pourboire', 'service'
]);

export const RegulariteSchema = z.enum(['souvent', 'parfois', 'rarement']);

// ============================================================================
// OBJETS COMPOSÉS
// ============================================================================

export const ChangementRelationSchema = z.object({
	pnj: z.string().min(1, "Nom PNJ requis"),
	delta: z.number().min(-3).max(1),
	disposition: z.string().optional(),
	raison: z.string().optional()
});

export const TransactionSchema = z.object({
	type: TypeTransactionSchema,
	montant: z.number(),
	description: z.string().optional(),
	objet: z.string().optional(),
	quantite: z.number().positive().optional()
});

export const DeltasValentinSchema = z.object({
	energie: z.number().min(-2).max(2).default(0),
	moral: z.number().min(-2).max(2).default(0),
	sante: z.number().min(-2).max(2).default(0)
}).default({ energie: 0, moral: 0, sante: 0 });

export const NouveauJourSchema = z.object({
	jour: z.string().min(1),
	date_jeu: z.string().min(1)
});

export const ChoixSchema = z.array(z.string().min(1))
	.min(2, "Au moins 2 choix requis")
	.max(5, "Maximum 5 choix");

// ============================================================================
// PNJ
// ============================================================================

export const PnjFrequentSchema = z.object({
	pnj: z.string().min(1),
	regularite: RegulariteSchema.default('parfois'),
	periode: z.string().optional()
});

export const PnjInitialSchema = z.object({
	nom: z.string().min(1, "Nom PNJ requis"),
	sexe: SexeSchema,
	age: z.number().min(0).max(500),
	espece: z.string().default('humain'),
	physique: z.string().optional(),
	metier: z.string().optional(),
	domicile: z.string().optional(),
	traits: z.array(z.string()).default([]),
	arcs: z.array(z.string()).default([])
});

// ============================================================================
// LIEUX
// ============================================================================

export const LieuInitialSchema = z.object({
	nom: z.string().min(1, "Nom lieu requis"),
	type: TypeLieuSchema,
	secteur: z.string().optional(),
	description: z.string().optional(),
	horaires: z.string().optional(),
	pnjs_frequents: z.array(PnjFrequentSchema).default([])
});

// ============================================================================
// ARCS
// ============================================================================

export const ArcPotentielSchema = z.object({
	nom: z.string().min(1, "Nom arc requis"),
	type: TypeArcSchema,
	description: z.string().optional(),
	obstacles: z.array(z.string()).default([]),
	pnjs_impliques: z.array(z.string()).default([])
});

// ============================================================================
// MONDE
// ============================================================================

export const MondeSchema = z.object({
	nom: z.string().min(1, "Nom du monde requis"),
	type: z.string().min(1),
	orbite: z.string().optional(),
	population: z.string().optional(),
	ambiance: z.string().optional()
});

export const EmployeurSchema = z.object({
	nom: z.string().min(1, "Nom employeur requis"),
	type: z.string().min(1)
});

export const ValentinInitSchema = z.object({
	raison_depart: z.string().optional(),
	poste: z.string().min(1, "Poste requis"),
	hobbies: z.array(z.string()).default(['cuisine'])
});

export const IASchema = z.object({
	nom: z.string().min(1, "Nom IA requis")
});
