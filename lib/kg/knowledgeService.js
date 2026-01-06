/**
 * Service de gestion des connaissances de Valentin
 * Gère ce que Valentin sait sur les entités (découverte progressive)
 */

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
 */
export function formatTooltip(entityData) {
	if (!entityData) return null;

	const { entite_type, entite_nom, connaissances, relation_valentin } = entityData;

	// Icône selon type
	const icons = {
		personnage: '👤',
		lieu: '📍',
		organisation: '🏢',
		objet: '📦',
		arc_narratif: '📖'
	};

	// Sélectionner les infos clés à afficher (max 3-4)
	const infosAffichees = [];

	if (entite_type === 'personnage') {
		if (connaissances.metier) infosAffichees.push(connaissances.metier);
		if (connaissances.physique) infosAffichees.push(truncate(connaissances.physique, 30));
		if (connaissances.espece && connaissances.espece !== 'humain') {
			infosAffichees.push(connaissances.espece);
		}
		if (connaissances.hobby) infosAffichees.push(`Aime : ${connaissances.hobby}`);
	}

	if (entite_type === 'lieu') {
		if (connaissances.type_lieu) infosAffichees.push(connaissances.type_lieu);
		if (connaissances.ambiance) infosAffichees.push(connaissances.ambiance);
		if (connaissances.horaires) infosAffichees.push(connaissances.horaires);
	}

	if (entite_type === 'organisation') {
		if (connaissances.domaine) infosAffichees.push(connaissances.domaine);
		if (connaissances.type_org) infosAffichees.push(connaissances.type_org);
	}

	// Relation avec Valentin
	let relationTxt = null;
	if (relation_valentin?.type) {
		const relLabels = {
			connait: 'Connaissance',
			ami_de: 'Ami',
			collegue_de: 'Collègue',
			employe_de: 'Employeur',
			travaille_a: 'Lieu de travail',
			habite: 'Domicile',
			frequente: 'Lieu fréquenté'
		};
		relationTxt = relLabels[relation_valentin.type] || relation_valentin.type;
	}

	return {
		icon: icons[entite_type] || '❓',
		nom: entite_nom,
		type: entite_type,
		infos: infosAffichees.slice(0, 3),
		relation: relationTxt
	};
}

function truncate(str, max) {
	if (!str || str.length <= max) return str;
	return str.slice(0, max - 1) + '…';
}
