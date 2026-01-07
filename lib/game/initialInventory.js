// ============================================================================
// lib/game/initialInventory.js
// ============================================================================

/**
 * Configuration des inventaires initiaux selon la situation de départ
 */

export const CATEGORIES_OBJET = [
	'nourriture', 'outils', 'equipement', 'vetements',
	'decoration', 'electronique', 'documents', 'mobilier',
	'hygiene', 'loisirs', 'consommable'
];

export const ETATS_OBJET = ['neuf', 'bon', 'use', 'endommage', 'casse'];

export const LOCALISATIONS = [
	'sur_soi', 'sac_a_dos', 'appartement', 'bureau', 'stockage', 'prete'
];

export const SITUATIONS_DEPART = {
	standard: {
		credits: 1400,
		description: "Arrivée normale avec économies moyennes",
		inventaire: [
			{ nom: "Valise de voyage", categorie: "equipement", localisation: "sur_soi", valeur: 120 },
			{ nom: "Tablet personnel", categorie: "electronique", localisation: "sur_soi", valeur: 450 },
			{ nom: "Vêtements de base", categorie: "vetements", quantite: 5, localisation: "valise", valeur: 200 },
			{ nom: "Trousse de toilette", categorie: "hygiene", localisation: "valise", valeur: 45 },
			{ nom: "Chargeur universel", categorie: "electronique", localisation: "valise", valeur: 25 },
			{ nom: "Documents d'identité", categorie: "documents", localisation: "sur_soi", valeur: 0 }
		]
	},

	fuite_precipitee: {
		credits: 650,
		description: "Départ précipité, peu d'affaires",
		inventaire: [
			{ nom: "Sac à dos usé", categorie: "equipement", localisation: "sur_soi", valeur: 40, etat: "use" },
			{ nom: "Tablet personnel", categorie: "electronique", localisation: "sur_soi", valeur: 450 },
			{ nom: "Vêtements de rechange", categorie: "vetements", quantite: 2, localisation: "sac", valeur: 60 },
			{ nom: "Documents d'identité", categorie: "documents", localisation: "sur_soi", valeur: 0 }
		]
	},

	rupture_difficile: {
		credits: 800,
		description: "Rupture récente, affaires partagées",
		inventaire: [
			{ nom: "Valise cabine", categorie: "equipement", localisation: "sur_soi", valeur: 80 },
			{ nom: "Tablet personnel", categorie: "electronique", localisation: "sur_soi", valeur: 450, etat: "use" },
			{ nom: "Vêtements de base", categorie: "vetements", quantite: 4, localisation: "valise", valeur: 150 },
			{ nom: "Photo encadrée", categorie: "decoration", localisation: "valise", valeur: 15, description: "Souvenir qu'il n'a pas pu laisser" },
			{ nom: "Livre de cuisine", categorie: "loisirs", localisation: "valise", valeur: 25 },
			{ nom: "Documents d'identité", categorie: "documents", localisation: "sur_soi", valeur: 0 }
		]
	},

	opportunite_professionnelle: {
		credits: 2200,
		description: "Mutation bien préparée avec prime",
		inventaire: [
			{ nom: "Valise rigide", categorie: "equipement", localisation: "sur_soi", valeur: 180 },
			{ nom: "Sac professionnel", categorie: "equipement", localisation: "sur_soi", valeur: 95 },
			{ nom: "Tablet professionnel", categorie: "electronique", localisation: "sac", valeur: 800, etat: "neuf" },
			{ nom: "Vêtements professionnels", categorie: "vetements", quantite: 6, localisation: "valise", valeur: 400 },
			{ nom: "Kit de cuisine compact", categorie: "outils", localisation: "valise", valeur: 120 },
			{ nom: "Casque audio premium", categorie: "electronique", localisation: "sac", valeur: 150 },
			{ nom: "Documents professionnels", categorie: "documents", localisation: "sac", valeur: 0 },
			{ nom: "Documents d'identité", categorie: "documents", localisation: "sur_soi", valeur: 0 }
		]
	},

	nouveau_depart: {
		credits: 1000,
		description: "Tout recommencer, le minimum vital",
		inventaire: [
			{ nom: "Sac de voyage", categorie: "equipement", localisation: "sur_soi", valeur: 60 },
			{ nom: "Tablet d'occasion", categorie: "electronique", localisation: "sur_soi", valeur: 200, etat: "use" },
			{ nom: "Vêtements basiques", categorie: "vetements", quantite: 3, localisation: "sac", valeur: 80 },
			{ nom: "Carnet papier", categorie: "loisirs", localisation: "sac", valeur: 8, description: "Pour écrire ses pensées" },
			{ nom: "Documents d'identité", categorie: "documents", localisation: "sur_soi", valeur: 0 }
		]
	}
};

/**
 * Détermine la situation de départ selon la raison du départ
 */
export function determinerSituation(raisonDepart) {
	const raison = (raisonDepart || '').toLowerCase();

	if (raison.includes('fuite') || raison.includes('urgence') || raison.includes('danger')) {
		return 'fuite_precipitee';
	}
	if (raison.includes('rupture') || raison.includes('séparation') || raison.includes('divorce')) {
		return 'rupture_difficile';
	}
	if (raison.includes('promotion') || raison.includes('opportunité') || raison.includes('mutation')) {
		return 'opportunite_professionnelle';
	}
	if (raison.includes('recommencer') || raison.includes('changer') || raison.includes('nouveau')) {
		return 'nouveau_depart';
	}

	return 'standard';
}

/**
 * Génère les opérations KG pour l'inventaire initial
 */
export function genererOperationsInventaire(situation, cycle = 1) {
	const config = SITUATIONS_DEPART[situation] || SITUATIONS_DEPART.standard;
	const operations = [];

	for (const item of config.inventaire) {
		operations.push({
			op: 'CREER_ENTITE',
			type: 'objet',
			nom: item.nom,
			proprietes: {
				categorie: item.categorie,
				valeur_neuve: item.valeur,
				prix_achat: item.valeur,
				etat: item.etat || 'bon',
				description: item.description || null
			}
		});

		operations.push({
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: item.nom,
			type: 'possede',
			proprietes: {
				quantite: item.quantite || 1,
				depuis_cycle: cycle,
				localisation: item.localisation,
				origine: 'initial'
			}
		});
	}

	return { operations, credits: config.credits };
}
