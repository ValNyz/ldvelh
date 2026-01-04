
/**
 * Service de gestion des Faits pour LDVELH
 * VERSION AVEC ASPECT pour déduplication fine
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
	MAX_FAITS_PAR_ECHANGE: 3,
	MAX_MODIFS_PAR_ECHANGE: 2,
	MIN_LONGUEUR_FAIT: 10,
	MAX_LONGUEUR_FAIT: 300,
	BUDGET_TOKENS_DEFAULT: 2500,
	TOKENS_PAR_FAIT: 40,
	CYCLES_RECENTS: 5,

	CATEGORIES: ['etat', 'relation', 'evenement', 'promesse', 'connaissance', 'secret', 'trait', 'objectif'],
	SUJET_TYPES: ['pnj', 'lieu', 'valentin', 'monde', 'objet'],
	CERTITUDES: ['certain', 'probable', 'rumeur'],

	// Aspects valides par catégorie
	ASPECTS: {
		etat: ['situation_pro', 'situation_perso', 'sante', 'logement', 'finance', 'apparence', 'projet'],
		trait: ['personnalite', 'habitude', 'preference', 'competence', 'physique'],
		relation: ['avec_valentin', 'familiale', 'professionnelle', 'amicale', 'conflictuelle'],
		connaissance: ['lieu', 'personne', 'technique', 'social', 'historique'],
		evenement: ['recent', 'passe', 'planifie'],
		promesse: ['faite', 'recue'],
		secret: ['personnel', 'professionnel', 'relationnel'],
		objectif: ['court_terme', 'long_terme']
	}
};

// ============================================================================
// VALIDATION
// ============================================================================

function validerFait(fait, cycleActuel) {
	if (!fait?.sujet_nom || !fait?.fait) return null;

	const sujetNom = fait.sujet_nom.trim();
	const description = fait.fait.trim();

	if (sujetNom.length < 2 || description.length < CONFIG.MIN_LONGUEUR_FAIT) return null;
	if (description.length > CONFIG.MAX_LONGUEUR_FAIT) return null;

	// Normalisation sujet_type
	let sujetType = 'monde';
	if (fait.sujet_type && CONFIG.SUJET_TYPES.includes(fait.sujet_type.toLowerCase())) {
		sujetType = fait.sujet_type.toLowerCase();
	}

	// Normalisation catégorie
	let categorie = 'evenement';
	if (fait.categorie && CONFIG.CATEGORIES.includes(fait.categorie.toLowerCase())) {
		categorie = fait.categorie.toLowerCase();
	}

	// Normalisation aspect
	let aspect = fait.aspect?.toLowerCase() || null;
	const aspectsValides = CONFIG.ASPECTS[categorie] || [];
	if (aspect && !aspectsValides.includes(aspect)) {
		aspect = null; // Aspect invalide, on le supprime
	}

	// Importance
	let importance = 3;
	if (fait.importance !== undefined) {
		importance = Math.min(5, Math.max(1, parseInt(fait.importance, 10) || 3));
	}

	// Certitude
	let certitude = 'certain';
	if (fait.certitude && CONFIG.CERTITUDES.includes(fait.certitude.toLowerCase())) {
		certitude = fait.certitude.toLowerCase();
	}

	return {
		sujet_type: sujetType,
		sujet_nom: sujetNom,
		categorie,
		aspect,
		fait: description,
		importance,
		valentin_sait: fait.valentin_sait !== false,
		certitude,
		cycle_creation: cycleActuel
	};
}

// ============================================================================
// EXTRACTION
// ============================================================================

function extraireFaits(claudeResponse, cycleActuel) {
	const result = {
		nouveaux: [],
		modifies: [],
		stats: { nouveaux_valides: 0, modifies_valides: 0 }
	};

	if (!claudeResponse || typeof claudeResponse !== 'object') return result;

	// Extraire nouveaux faits
	const faitsNouveaux = claudeResponse.faits_nouveaux;
	if (Array.isArray(faitsNouveaux)) {
		for (const faitBrut of faitsNouveaux.slice(0, CONFIG.MAX_FAITS_PAR_ECHANGE)) {
			const faitValide = validerFait(faitBrut, cycleActuel);
			if (faitValide) {
				// Éviter doublons dans cette extraction
				const existe = result.nouveaux.some(f =>
					f.sujet_nom.toLowerCase() === faitValide.sujet_nom.toLowerCase() &&
					f.categorie === faitValide.categorie &&
					f.aspect === faitValide.aspect
				);
				if (!existe) {
					result.nouveaux.push(faitValide);
					result.stats.nouveaux_valides++;
				}
			}
		}
	}

	// Extraire modifications
	const faitsModifies = claudeResponse.faits_modifies;
	if (Array.isArray(faitsModifies)) {
		for (const modif of faitsModifies.slice(0, CONFIG.MAX_MODIFS_PAR_ECHANGE)) {
			if (!modif?.fait_original || !modif?.sujet_nom || !modif?.raison) continue;
			result.modifies.push({
				fait_original: modif.fait_original.trim(),
				sujet_nom: modif.sujet_nom.trim(),
				aspect: modif.aspect?.toLowerCase() || null,
				raison: modif.raison.trim(),
				cycle_invalidation: cycleActuel
			});
			result.stats.modifies_valides++;
		}
	}

	return result;
}

// ============================================================================
// SAUVEGARDE (via RPC PostgreSQL)
// ============================================================================

async function sauvegarderFaits(supabase, partieId, extraction, pnjMap = new Map()) {
	const resultats = { ajoutes: 0, mis_a_jour: 0, invalides: 0, erreurs: [] };

	if (extraction.nouveaux.length === 0 && extraction.modifies.length === 0) {
		return resultats;
	}

	// 1. Upsert des nouveaux faits via RPC batch
	if (extraction.nouveaux.length > 0) {
		const faitsFormatted = extraction.nouveaux.map(fait => ({
			sujet_type: fait.sujet_type,
			sujet_id: fait.sujet_type === 'pnj' ? pnjMap.get(fait.sujet_nom.toLowerCase()) || null : null,
			sujet_nom: fait.sujet_nom,
			categorie: fait.categorie,
			aspect: fait.aspect,
			fait: fait.fait,
			importance: fait.importance,
			cycle_creation: fait.cycle_creation,
			valentin_sait: fait.valentin_sait,
			certitude: fait.certitude
		}));

		const { data, error } = await supabase.rpc('upsert_faits_batch', {
			p_partie_id: partieId,
			p_faits: faitsFormatted
		});

		if (error) {
			resultats.erreurs.push(`Erreur upsert batch: ${error.message}`);
		} else if (data) {
			resultats.ajoutes = data.inserted || 0;
			resultats.mis_a_jour = data.updated || 0;
		}
	}

	// 2. Invalider les faits modifiés
	for (const modif of extraction.modifies) {
		try {
			// Recherche par sujet + aspect si fourni
			let query = supabase
				.from('faits')
				.select('id, fait')
				.eq('partie_id', partieId)
				.ilike('sujet_nom', `%${modif.sujet_nom}%`)
				.is('cycle_invalidation', null);

			if (modif.aspect) {
				query = query.eq('aspect', modif.aspect);
			}

			const { data: faitsTrouves } = await query;

			// Trouver le fait le plus proche du texte original
			const faitCorrespondant = faitsTrouves?.find(f => {
				const mots1 = modif.fait_original.toLowerCase().split(/\s+/).filter(m => m.length > 3);
				const mots2 = f.fait.toLowerCase().split(/\s+/).filter(m => m.length > 3);
				const communs = mots1.filter(m => mots2.includes(m));
				return communs.length >= Math.min(mots1.length, mots2.length) * 0.4;
			});

			if (faitCorrespondant) {
				await supabase
					.from('faits')
					.update({
						cycle_invalidation: modif.cycle_invalidation,
						raison_invalidation: modif.raison
					})
					.eq('id', faitCorrespondant.id);

				resultats.invalides++;
			}
		} catch (err) {
			resultats.erreurs.push(`Erreur invalidation: ${err.message}`);
		}
	}

	return resultats;
}

// ============================================================================
// SÉLECTION POUR CONTEXTE (inchangé)
// ============================================================================

async function selectionnerFaitsPertinents(supabase, partieId, options = {}) {
	const {
		pnjPresents = [],
		lieuActuel = '',
		cycleActuel = 1,
		budgetTokens = CONFIG.BUDGET_TOKENS_DEFAULT
	} = options;

	const faitsSelectionnes = [];
	let tokensUtilises = 0;
	const idsInclus = new Set();

	const ajouterFait = (fait) => {
		if (idsInclus.has(fait.id)) return false;
		if (tokensUtilises + CONFIG.TOKENS_PAR_FAIT > budgetTokens) return false;
		faitsSelectionnes.push(fait);
		idsInclus.add(fait.id);
		tokensUtilises += CONFIG.TOKENS_PAR_FAIT;
		return true;
	};

	// Requêtes parallèles par priorité
	const [critiques, faitsPnj, promesses, faitsLieu, recents, faitsValentin, faitsCycleActuel, importants] = await Promise.all([
		supabase.from('faits').select('*')
			.eq('partie_id', partieId).eq('importance', 5)
			.is('cycle_invalidation', null)
			.then(r => r.data || []),

		pnjPresents.length > 0
			? supabase.from('faits').select('*')
				.eq('partie_id', partieId).eq('sujet_type', 'pnj')
				.in('sujet_nom', pnjPresents).gte('importance', 2)
				.is('cycle_invalidation', null)
				.then(r => r.data || [])
			: [],

		supabase.from('faits').select('*')
			.eq('partie_id', partieId).eq('categorie', 'promesse')
			.is('cycle_invalidation', null).limit(10)
			.then(r => r.data || []),

		lieuActuel
			? supabase.from('faits').select('*')
				.eq('partie_id', partieId).eq('sujet_type', 'lieu')
				.ilike('sujet_nom', `%${lieuActuel}%`)
				.is('cycle_invalidation', null).limit(8)
				.then(r => r.data || [])
			: [],

		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.gte('cycle_creation', Math.max(1, cycleActuel - CONFIG.CYCLES_RECENTS))
			.gte('importance', 3).is('cycle_invalidation', null)
			.order('cycle_creation', { ascending: false }).limit(15)
			.then(r => r.data || []),

		supabase.from('faits').select('*')
			.eq('partie_id', partieId).eq('sujet_type', 'valentin')
			.gte('importance', 3).is('cycle_invalidation', null).limit(12)
			.then(r => r.data || []),

		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.eq('cycle_creation', cycleActuel)
			.is('cycle_invalidation', null)
			.order('created_at', { ascending: false })
			.limit(20)
			.then(r => r.data || []),

		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.gte('importance', 4)
			.is('cycle_invalidation', null)
			.order('importance', { ascending: false })
			.limit(30)
			.then(r => r.data || [])

	]);

	// Ajouter par priorité
	[critiques, faitsPnj, promesses, faitsLieu, recents, faitsValentin, faitsCycleActuel, importants]
		.forEach(groupe => groupe.forEach(ajouterFait));

	return faitsSelectionnes;
}

// ============================================================================
// FORMATAGE CONTEXTE
// ============================================================================

function formaterFaitsPourContexte(faits) {
	if (!faits?.length) return '';

	const parSujet = new Map();
	for (const fait of faits) {
		if (!parSujet.has(fait.sujet_nom)) parSujet.set(fait.sujet_nom, []);
		parSujet.get(fait.sujet_nom).push(fait);
	}

	let output = '\n=== FAITS ÉTABLIS (COHÉRENCE OBLIGATOIRE) ===\n';

	for (const [sujet, sujetFaits] of parSujet) {
		output += `\n## ${sujet.toUpperCase()}\n`;
		for (const fait of sujetFaits.sort((a, b) => b.importance - a.importance)) {
			const marqueur = fait.importance >= 4 ? '⚠️' : '•';
			const certitude = fait.certitude !== 'certain' ? ` [${fait.certitude}]` : '';
			const secret = !fait.valentin_sait ? ' [HORS-CHAMP]' : '';
			output += `${marqueur} ${fait.fait}${certitude}${secret}\n`;
		}
	}

	output += '\n⚠️ NE PAS CONTREDIRE ces faits. Si un fait change, utilise faits_modifies.\n';
	return output;
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	CONFIG,
	extraireFaits,
	validerFait,
	sauvegarderFaits,
	selectionnerFaitsPertinents,
	formaterFaitsPourContexte,
};
