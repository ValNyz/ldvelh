/**
 * Service de gestion des connaissances de Valentin
 * Gère ce que Valentin sait sur les entités (découverte progressive)
 */

import { normaliserTexte, calculerConfiance } from '../utils/fuzzyMatching.js';

// ============================================================================
// APPRENTISSAGE
// ============================================================================

/**
 * Enregistre une nouvelle connaissance de Valentin
 */
export async function apprendre(supabase, partieId, entiteId, attribut, valeur, cycle, sourceType = 'observation') {
	const { data, error } = await supabase
		.rpc('kg_apprendre', {
			p_partie_id: partieId,
			p_entite_id: entiteId,
			p_attribut: attribut,
			p_valeur: String(valeur),
			p_cycle: cycle,
			p_source_type: sourceType
		});

	if (error) {
		console.error('[Connaissances] Erreur apprendre:', error);
		return null;
	}

	return data;
}

/**
 * Sync les connaissances depuis une opération CREER_ENTITE ou MODIFIER_ENTITE
 */
export async function syncFromOperation(supabase, partieId, entiteId, operation, cycle) {
	const visible = operation.visible || {};
	const results = [];

	for (const [attribut, valeur] of Object.entries(visible)) {
		if (valeur !== null && valeur !== undefined) {
			// Déterminer la source selon le contexte
			const sourceType = inferSourceType(attribut);
			const id = await apprendre(supabase, partieId, entiteId, attribut, valeur, cycle, sourceType);
			if (id) results.push({ attribut, valeur });
		}
	}

	return results;
}

/**
 * Infère le type de source selon l'attribut
 */
function inferSourceType(attribut) {
	const observables = ['physique', 'espece', 'taille', 'couleur', 'apparence', 'vetements'];
	const conversationnels = ['nom', 'prenom', 'metier', 'age', 'hobby', 'origine', 'famille'];

	if (observables.some(o => attribut.toLowerCase().includes(o))) {
		return 'observation';
	}
	if (conversationnels.some(c => attribut.toLowerCase().includes(c))) {
		return 'conversation';
	}
	return 'observation';
}

// ============================================================================
// RÉCUPÉRATION POUR TOOLTIPS
// ============================================================================

/**
 * Récupère toutes les données tooltip pour une partie
 * Retourne un Map nom/alias → données tooltip
 */
export async function getTooltipsData(supabase, partieId) {
	const { data, error } = await supabase
		.from('kg_v_tooltip')
		.select('*')
		.eq('partie_id', partieId);

	if (error) {
		console.error('[Connaissances] Erreur getTooltipsData:', error);
		return new Map();
	}

	// Construire un index par nom et alias
	const tooltipMap = new Map();

	for (const entity of data || []) {
		// Clé principale : nom
		tooltipMap.set(entity.entite_nom.toLowerCase(), entity);

		// Clés secondaires : alias
		if (entity.alias?.length > 0) {
			for (const alias of entity.alias) {
				tooltipMap.set(alias.toLowerCase(), entity);
			}
		}
	}

	return tooltipMap;
}

/**
 * Récupère les connaissances pour une entité spécifique
 */
export async function getConnaissancesEntite(supabase, partieId, entiteId) {
	const { data, error } = await supabase
		.from('kg_connaissances')
		.select('attribut, valeur, source_type, cycle_decouverte')
		.eq('partie_id', partieId)
		.eq('entite_id', entiteId)
		.order('cycle_decouverte', { ascending: true });

	if (error) {
		console.error('[Connaissances] Erreur getConnaissancesEntite:', error);
		return [];
	}

	return data || [];
}

// ============================================================================
// FORMATAGE TOOLTIP
// ============================================================================

/**
 * Formate les données pour affichage tooltip
 * Affiche TOUTES les connaissances de Valentin
 */
export function formatTooltip(entityData) {
	if (!entityData) return null;

	const { entite_type, entite_nom, connaissances, relation_valentin } = entityData;

	const icons = {
		personnage: '👤',
		lieu: '📍',
		organisation: '🏢',
		objet: '📦',
		arc_narratif: '📖',
		ia: '🤖'
	};

	// Relation avec Valentin
	let relationTxt = null;
	if (relation_valentin?.type) {
		const relLabels = {
			connait: 'Connaissance',
			ami_de: 'Ami',
			collegue_de: 'Collègue',
			superieur_de: 'Supérieur',
			employe_de: 'Employeur',
			travaille_a: 'Lieu de travail',
			habite: 'Domicile',
			frequente: 'Lieu fréquenté',
			possede: 'Possédé'
		};
		relationTxt = relLabels[relation_valentin.type] || relation_valentin.type;
	}

	// Formater TOUTES les connaissances
	const infos = [];
	if (connaissances && typeof connaissances === 'object') {
		// Ordre de priorité pour l'affichage
		const ordre = ['metier', 'physique', 'espece', 'age', 'domicile', 'hobby', 'traits', 'type_lieu', 'ambiance', 'horaires', 'domaine', 'type_org'];

		// D'abord les clés prioritaires
		for (const key of ordre) {
			if (connaissances[key]) {
				infos.push(formatConnaissance(key, connaissances[key]));
			}
		}

		// Puis le reste (sauf 'nom' qui est déjà en titre)
		for (const [key, val] of Object.entries(connaissances)) {
			if (!ordre.includes(key) && key !== 'nom' && val) {
				infos.push(formatConnaissance(key, val));
			}
		}
	}

	return {
		icon: icons[entite_type] || '❓',
		nom: entite_nom,
		type: entite_type,
		infos,
		relation: relationTxt
	};
}

/**
 * Formate une connaissance individuelle pour affichage
 */
function formatConnaissance(key, value) {
	const labels = {
		metier: 'Métier',
		physique: 'Apparence',
		espece: 'Espèce',
		age: 'Âge',
		domicile: 'Domicile',
		hobby: 'Hobby',
		traits: 'Traits',
		type_lieu: 'Type',
		ambiance: 'Ambiance',
		horaires: 'Horaires',
		domaine: 'Domaine',
		type_org: 'Type',
		voix: 'Voix',
		occupation: 'Occupation'
	};

	const label = labels[key] || key;
	const val = Array.isArray(value) ? value.join(', ') : value;

	return `${label}: ${truncate(String(val), 50)}`;
}

function truncate(str, max) {
	if (!str || str.length <= max) return str;
	return str.slice(0, max - 1) + '…';
}

/**
 * Cherche une entité par fuzzy matching
 * @param {string} text - Texte à matcher (ex: "Priya", "le Bar Eclipse")
 * @param {Map} tooltipMap - Map des entités
 * @param {number} seuil - Score minimum (défaut: 70)
 * @returns {object|null} - Données de l'entité ou null
 */
/**
 * Cherche une entité par fuzzy matching
 */
export function fuzzyMatchEntity(text, tooltipMap, seuil = 70) {
	if (!text || !tooltipMap || tooltipMap.size === 0) return null;

	const textNorm = normaliser(text);

	// 1. Match exact (après normalisation)
	for (const [key, entity] of tooltipMap) {
		if (normaliser(key) === textNorm) {
			return entity;
		}
	}

	// 2. Fuzzy matching sur toutes les entités
	let meilleurMatch = null;
	let meilleurScore = 0;

	for (const [key, entity] of tooltipMap) {
		// Construire un objet candidat pour calculerConfiance
		const candidat = {
			nom: key,
			alias: entity.alias || []
		};

		const { confiance } = calculerConfiance(text, candidat);

		if (confiance > meilleurScore && confiance >= seuil) {
			meilleurScore = confiance;
			meilleurMatch = entity;
		}
	}

	return meilleurMatch;
}
