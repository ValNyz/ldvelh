/**
 * Service de gestion des Faits pour LDVELH
 * L'extraction est gérée par Haiku, ce service gère lecture/écriture
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
	BUDGET_MAX_FAITS: 20,
	CATEGORIES: ['etat', 'relation', 'evenement', 'promesse', 'connaissance', 'secret', 'trait'],
	SUJET_TYPES: ['pnj', 'lieu', 'valentin', 'monde'],
	CYCLES_RECENTS: 5
};

// ============================================================================
// SÉLECTION DES FAITS POUR LE CONTEXTE
// ============================================================================

/**
 * Sélectionne les faits pertinents pour le contexte actuel
 */
export async function getFaitsPertinents(supabase, partieId, options = {}) {
	const {
		pnjPresents = [],
		lieuActuel = '',
		cycleActuel = 1
	} = options;

	const faitsSelectionnes = [];
	const idsInclus = new Set();

	const ajouter = (fait) => {
		if (idsInclus.has(fait.id) || faitsSelectionnes.length >= CONFIG.BUDGET_MAX_FAITS) return false;
		faitsSelectionnes.push(fait);
		idsInclus.add(fait.id);
		return true;
	};

	// 1. Faits critiques (importance 5)
	const { data: critiques } = await supabase
		.from('faits')
		.select('*')
		.eq('partie_id', partieId)
		.eq('importance', 5)
		.is('cycle_invalidation', null)
		.limit(8);

	(critiques || []).forEach(ajouter);

	// 2. Faits des PNJ présents dans la scène
	if (pnjPresents.length > 0) {
		const { data: faitsPnj } = await supabase
			.from('faits')
			.select('*')
			.eq('partie_id', partieId)
			.in('sujet_nom', pnjPresents)
			.gte('importance', 3)
			.is('cycle_invalidation', null)
			.limit(10);

		(faitsPnj || []).forEach(ajouter);
	}

	// 3. Faits du lieu actuel
	if (lieuActuel) {
		const { data: faitsLieu } = await supabase
			.from('faits')
			.select('*')
			.eq('partie_id', partieId)
			.ilike('sujet_nom', `%${lieuActuel}%`)
			.is('cycle_invalidation', null)
			.limit(5);

		(faitsLieu || []).forEach(ajouter);
	}

	// 4. Promesses actives (toujours pertinentes)
	const { data: promesses } = await supabase
		.from('faits')
		.select('*')
		.eq('partie_id', partieId)
		.eq('categorie', 'promesse')
		.is('cycle_invalidation', null)
		.limit(5);

	(promesses || []).forEach(ajouter);

	// 5. Secrets que Valentin connaît
	const { data: secrets } = await supabase
		.from('faits')
		.select('*')
		.eq('partie_id', partieId)
		.eq('categorie', 'secret')
		.eq('valentin_sait', true)
		.is('cycle_invalidation', null)
		.limit(5);

	(secrets || []).forEach(ajouter);

	// 6. Faits récents importants
	const { data: recents } = await supabase
		.from('faits')
		.select('*')
		.eq('partie_id', partieId)
		.gte('cycle_creation', Math.max(1, cycleActuel - CONFIG.CYCLES_RECENTS))
		.gte('importance', 4)
		.is('cycle_invalidation', null)
		.order('cycle_creation', { ascending: false })
		.limit(10);

	(recents || []).forEach(ajouter);

	return faitsSelectionnes;
}

// ============================================================================
// FORMATAGE POUR LE CONTEXTE
// ============================================================================

/**
 * Formate les faits pour inclusion dans le contexte Claude
 */
export function formaterFaitsPourContexte(faits) {
	if (!faits?.length) return '';

	// Grouper par sujet
	const parSujet = new Map();
	for (const fait of faits) {
		const sujet = fait.sujet_nom;
		if (!parSujet.has(sujet)) {
			parSujet.set(sujet, []);
		}
		parSujet.get(sujet).push(fait);
	}

	let output = '=== FAITS ÉTABLIS ===\n';
	output += '(Cohérence obligatoire — ne pas contredire)\n';

	for (const [sujet, listeFaits] of parSujet) {
		output += `\n## ${sujet.toUpperCase()}\n`;

		// Trier par importance décroissante
		const tries = listeFaits.sort((a, b) => b.importance - a.importance);

		for (const fait of tries) {
			const marqueur = fait.importance >= 5 ? '⚠️' : '•';
			const certitude = fait.certitude && fait.certitude !== 'certain' ? ` [${fait.certitude}]` : '';
			const secret = !fait.valentin_sait ? ' [HORS-CHAMP]' : '';
			output += `${marqueur} ${fait.fait}${certitude}${secret}\n`;
		}
	}

	return output + '\n';
}

// ============================================================================
// SAUVEGARDE (appelé par Haiku)
// ============================================================================

/**
 * Sauvegarde les faits extraits par Haiku
 */
export async function sauvegarderFaits(supabase, partieId, faits, cycleActuel) {
	if (!faits?.length) return { ajoutes: 0, erreurs: [] };

	const resultats = { ajoutes: 0, erreurs: [] };

	for (const fait of faits) {
		// Validation minimale
		if (!fait.sujet_nom || !fait.fait) {
			resultats.erreurs.push('Fait invalide: sujet_nom ou fait manquant');
			continue;
		}

		// Vérifier doublon (même sujet + fait similaire)
		const { data: existing } = await supabase
			.from('faits')
			.select('id')
			.eq('partie_id', partieId)
			.ilike('sujet_nom', fait.sujet_nom)
			.ilike('fait', `%${fait.fait.slice(0, 50)}%`)
			.is('cycle_invalidation', null)
			.maybeSingle();

		if (existing) {
			continue; // Doublon, on skip
		}

		// Insérer le fait
		const { error } = await supabase.from('faits').insert({
			partie_id: partieId,
			sujet_type: fait.sujet_type || 'monde',
			sujet_nom: fait.sujet_nom,
			categorie: fait.categorie || 'evenement',
			fait: fait.fait,
			importance: fait.importance || 4,
			cycle_creation: cycleActuel,
			valentin_sait: fait.valentin_sait !== false,
			certitude: fait.certitude || 'certain'
		});

		if (error) {
			resultats.erreurs.push(`Erreur insertion: ${error.message}`);
		} else {
			resultats.ajoutes++;
		}
	}

	if (resultats.ajoutes > 0) {
		console.log(`[Faits] ${resultats.ajoutes} fait(s) ajouté(s)`);
	}

	return resultats;
}

/**
 * Invalide un fait (quand il n'est plus vrai)
 */
export async function invaliderFait(supabase, partieId, sujetNom, faitPartiel, cycleActuel, raison) {
	const { data: faitTrouve } = await supabase
		.from('faits')
		.select('id')
		.eq('partie_id', partieId)
		.ilike('sujet_nom', sujetNom)
		.ilike('fait', `%${faitPartiel}%`)
		.is('cycle_invalidation', null)
		.maybeSingle();

	if (!faitTrouve) return false;

	const { error } = await supabase
		.from('faits')
		.update({
			cycle_invalidation: cycleActuel,
			raison_invalidation: raison
		})
		.eq('id', faitTrouve.id);

	if (error) {
		console.error('[Faits] Erreur invalidation:', error);
		return false;
	}

	console.log(`[Faits] Invalidé: ${sujetNom} - ${faitPartiel.slice(0, 30)}...`);
	return true;
}

// ============================================================================
// EXPORTS
// ============================================================================

export { CONFIG };
