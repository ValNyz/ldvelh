/**
 * Service de gestion des Faits pour LDVELH
 * 
 * Module découplé pour l'extraction, le stockage et la récupération
 * des faits narratifs. Peut être activé/désactivé via les options.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
	// Limites par échange
	MAX_FAITS_PAR_ECHANGE: 5,
	MAX_MODIFS_PAR_ECHANGE: 3,

	// Limites globales
	MAX_FAITS_ACTIFS_PARTIE: 500,

	// Seuils de qualité
	MIN_LONGUEUR_FAIT: 10,
	MAX_LONGUEUR_FAIT: 300,
	MIN_LONGUEUR_SUJET: 2,
	MAX_LONGUEUR_SUJET: 100,

	// Sélection contexte
	BUDGET_TOKENS_DEFAULT: 2500,
	TOKENS_PAR_FAIT: 40,
	CYCLES_RECENTS: 5,

	// Valeurs autorisées
	CATEGORIES: ['etat', 'relation', 'evenement', 'promesse', 'connaissance', 'secret', 'trait', 'objectif'],
	SUJET_TYPES: ['pnj', 'lieu', 'valentin', 'monde', 'objet'],
	CERTITUDES: ['certain', 'probable', 'rumeur', 'mensonge'],
	SOURCES: ['observation', 'dialogue', 'inference', 'narrateur', 'correction_joueur']
};

// ============================================================================
// UTILITAIRES
// ============================================================================

/**
 * Calcule une similarité simple entre deux textes (Jaccard sur mots)
 */
function similarite(texte1, texte2) {
	const mots1 = new Set(texte1.toLowerCase().split(/\s+/).filter(m => m.length > 2));
	const mots2 = new Set(texte2.toLowerCase().split(/\s+/).filter(m => m.length > 2));

	const intersection = new Set([...mots1].filter(m => mots2.has(m)));
	const union = new Set([...mots1, ...mots2]);

	return union.size > 0 ? intersection.size / union.size : 0;
}

// ============================================================================
// VALIDATION D'UN FAIT
// ============================================================================

/**
 * Valide et normalise un fait extrait par Claude
 */
function validerFait(fait, cycleActuel) {
	if (!fait || typeof fait !== 'object') return null;
	if (!fait.sujet_nom || typeof fait.sujet_nom !== 'string') return null;
	if (!fait.fait || typeof fait.fait !== 'string') return null;

	const sujetNom = fait.sujet_nom.trim();
	const description = fait.fait.trim();

	if (sujetNom.length < CONFIG.MIN_LONGUEUR_SUJET || sujetNom.length > CONFIG.MAX_LONGUEUR_SUJET) {
		return null;
	}

	if (description.length < CONFIG.MIN_LONGUEUR_FAIT || description.length > CONFIG.MAX_LONGUEUR_FAIT) {
		return null;
	}

	// Rejeter les descriptions trop vagues
	const motsVagues = ['quelque chose', 'un truc', 'des trucs', 'machin'];
	if (motsVagues.some(m => description.toLowerCase().includes(m))) {
		return null;
	}

	// Normalisation
	let sujetType = 'monde';
	if (fait.sujet_type && CONFIG.SUJET_TYPES.includes(fait.sujet_type.toLowerCase())) {
		sujetType = fait.sujet_type.toLowerCase();
	}

	let categorie = 'evenement';
	if (fait.categorie && CONFIG.CATEGORIES.includes(fait.categorie.toLowerCase())) {
		categorie = fait.categorie.toLowerCase();
	}

	let importance = 3;
	if (fait.importance !== undefined) {
		const parsed = parseInt(fait.importance, 10);
		if (!isNaN(parsed)) {
			importance = Math.min(5, Math.max(1, parsed));
		}
	}

	let certitude = 'certain';
	if (fait.certitude && CONFIG.CERTITUDES.includes(fait.certitude.toLowerCase())) {
		certitude = fait.certitude.toLowerCase();
	}

	return {
		sujet_type: sujetType,
		sujet_nom: sujetNom,
		categorie: categorie,
		fait: description,
		importance: importance,
		valentin_sait: fait.valentin_sait !== false,
		certitude: certitude,
		source: 'observation',
		cycle_creation: cycleActuel
	};
}

// ============================================================================
// EXTRACTION DES FAITS
// ============================================================================

/**
 * Extrait et valide les faits depuis la réponse JSON de Claude
 * Limites PAR ÉCHANGE (pas par cycle)
 */
function extraireFaits(claudeResponse, cycleActuel) {
	const result = {
		nouveaux: [],
		modifies: [],
		stats: { nouveaux_valides: 0, modifies_valides: 0 }
	};

	if (!claudeResponse || typeof claudeResponse !== 'object') {
		return result;
	}

	// Extraire les faits nouveaux (max 5 par échange)
	const faitsNouveaux = claudeResponse.faits_nouveaux;
	if (Array.isArray(faitsNouveaux)) {
		const faitsATester = faitsNouveaux.slice(0, CONFIG.MAX_FAITS_PAR_ECHANGE);

		for (const faitBrut of faitsATester) {
			const faitValide = validerFait(faitBrut, cycleActuel);

			if (faitValide) {
				// Vérifier doublon dans cette extraction
				const estDoublon = result.nouveaux.some(f =>
					f.sujet_nom.toLowerCase() === faitValide.sujet_nom.toLowerCase() &&
					similarite(f.fait, faitValide.fait) > 0.8
				);

				if (!estDoublon) {
					result.nouveaux.push(faitValide);
					result.stats.nouveaux_valides++;
				}
			}
		}
	}

	// Extraire les faits modifiés (max 3 par échange)
	const faitsModifies = claudeResponse.faits_modifies;
	if (Array.isArray(faitsModifies)) {
		const modifsATester = faitsModifies.slice(0, CONFIG.MAX_MODIFS_PAR_ECHANGE);

		for (const modif of modifsATester) {
			if (!modif || typeof modif !== 'object') continue;

			const faitOriginal = modif.fait_original?.trim();
			const sujetNom = modif.sujet_nom?.trim();
			const raison = modif.raison?.trim();

			if (!faitOriginal || faitOriginal.length < 5) continue;
			if (!sujetNom || sujetNom.length < 2) continue;
			if (!raison || raison.length < 3) continue;

			result.modifies.push({
				fait_original: faitOriginal,
				sujet_nom: sujetNom,
				raison: raison,
				cycle_invalidation: cycleActuel
			});
			result.stats.modifies_valides++;
		}
	}

	return result;
}

// ============================================================================
// SAUVEGARDE DES FAITS
// ============================================================================

/**
 * Sauvegarde les nouveaux faits et invalide les faits modifiés
 */
async function sauvegarderFaits(supabase, partieId, extraction, pnjMap = new Map()) {
	const resultats = { ajoutes: 0, invalides: 0, erreurs: [] };

	// 1. Insérer les nouveaux faits
	if (extraction.nouveaux.length > 0) {
		const faitsAInserer = extraction.nouveaux.map(fait => ({
			partie_id: partieId,
			sujet_type: fait.sujet_type,
			sujet_id: fait.sujet_type === 'pnj' ? pnjMap.get(fait.sujet_nom.toLowerCase()) || null : null,
			sujet_nom: fait.sujet_nom,
			categorie: fait.categorie,
			fait: fait.fait,
			importance: fait.importance,
			cycle_creation: fait.cycle_creation,
			source: fait.source,
			valentin_sait: fait.valentin_sait,
			certitude: fait.certitude
		}));

		const { error } = await supabase.from('faits').insert(faitsAInserer);
		if (error) {
			resultats.erreurs.push(`Erreur insertion: ${error.message}`);
		} else {
			resultats.ajoutes = faitsAInserer.length;
		}
	}

	// 2. Invalider les faits modifiés
	for (const modif of extraction.modifies) {
		try {
			// Recherche du fait à invalider
			const { data: faitsTrouves } = await supabase
				.from('faits')
				.select('id, fait')
				.eq('partie_id', partieId)
				.ilike('sujet_nom', `%${modif.sujet_nom}%`)
				.is('cycle_invalidation', null);

			// Trouver le fait le plus proche
			const faitCorrespondant = faitsTrouves?.find(f => {
				return similarite(f.fait, modif.fait_original) > 0.5;
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
// SÉLECTION DES FAITS POUR LE CONTEXTE
// ============================================================================

/**
 * Sélectionne les faits pertinents pour le contexte Claude
 */
async function selectionnerFaitsPertinents(supabase, partieId, {
	pnjPresents = [],
	lieuActuel = '',
	cycleActuel = 1,
	budgetTokens = CONFIG.BUDGET_TOKENS_DEFAULT
}) {
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

	const ajouterPlusieurs = (faits) => {
		for (const fait of faits || []) {
			if (!ajouterFait(fait)) break;
		}
	};

	// Charger toutes les catégories en parallèle
	const [critiques, faitsPnj, promesses, faitsLieu, recents, faitsValentin, importants] = await Promise.all([
		// P1: Critiques (importance 5)
		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.eq('importance', 5)
			.is('cycle_invalidation', null)
			.order('cycle_creation', { ascending: false })
			.then(r => r.data || []),

		// P2: PNJ présents
		pnjPresents.length > 0
			? supabase.from('faits').select('*')
				.eq('partie_id', partieId)
				.eq('sujet_type', 'pnj')
				.in('sujet_nom', pnjPresents)
				.gte('importance', 2)
				.is('cycle_invalidation', null)
				.order('importance', { ascending: false })
				.then(r => r.data || [])
			: Promise.resolve([]),

		// P3: Promesses actives
		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.eq('categorie', 'promesse')
			.is('cycle_invalidation', null)
			.order('importance', { ascending: false })
			.limit(10)
			.then(r => r.data || []),

		// P4: Lieu actuel
		lieuActuel
			? supabase.from('faits').select('*')
				.eq('partie_id', partieId)
				.eq('sujet_type', 'lieu')
				.ilike('sujet_nom', `%${lieuActuel}%`)
				.is('cycle_invalidation', null)
				.limit(8)
				.then(r => r.data || [])
			: Promise.resolve([]),

		// P5: Récents (derniers 5 cycles)
		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.gte('cycle_creation', Math.max(1, cycleActuel - CONFIG.CYCLES_RECENTS))
			.gte('importance', 3)
			.is('cycle_invalidation', null)
			.order('cycle_creation', { ascending: false })
			.limit(15)
			.then(r => r.data || []),

		// P6: Valentin
		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.eq('sujet_type', 'valentin')
			.gte('importance', 3)
			.is('cycle_invalidation', null)
			.order('importance', { ascending: false })
			.limit(12)
			.then(r => r.data || []),

		// P7: Importants (remplissage)
		supabase.from('faits').select('*')
			.eq('partie_id', partieId)
			.gte('importance', 4)
			.is('cycle_invalidation', null)
			.order('importance', { ascending: false })
			.limit(30)
			.then(r => r.data || [])
	]);

	// Ajouter par priorité
	ajouterPlusieurs(critiques);
	ajouterPlusieurs(faitsPnj);
	ajouterPlusieurs(promesses);
	ajouterPlusieurs(faitsLieu);
	ajouterPlusieurs(recents);
	ajouterPlusieurs(faitsValentin);
	ajouterPlusieurs(importants);

	return faitsSelectionnes;
}

// ============================================================================
// FORMATAGE POUR LE PROMPT
// ============================================================================

/**
 * Formate les faits pour injection dans le contexte Claude
 */
function formaterFaitsPourContexte(faits) {
	if (!faits || faits.length === 0) return '';

	// Grouper par sujet
	const parSujet = new Map();
	for (const fait of faits) {
		const key = fait.sujet_nom;
		if (!parSujet.has(key)) {
			parSujet.set(key, []);
		}
		parSujet.get(key).push(fait);
	}

	let output = '\n=== FAITS ÉTABLIS (COHÉRENCE OBLIGATOIRE) ===\n';

	for (const [sujet, sujetFaits] of parSujet) {
		const tries = sujetFaits.sort((a, b) => b.importance - a.importance);

		output += `\n## ${sujet.toUpperCase()}\n`;

		for (const fait of tries) {
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
// ADDON AU PROMPT SYSTEM
// ============================================================================

const PROMPT_ADDON_FAITS = `

## EXTRACTION DES FAITS

À chaque réponse, identifie les faits nouveaux ou modifiés pour la cohérence future.
Maximum 5 faits nouveaux et 3 modifications par réponse.

Dans ton JSON, ajoute :

"faits_nouveaux": [
  {
    "sujet_type": "pnj",
    "sujet_nom": "Justine Lépicier",
    "categorie": "etat",
    "fait": "A perdu son emploi au Café Luna",
    "importance": 4,
    "valentin_sait": true,
    "certitude": "certain"
  }
],

"faits_modifies": [
  {
    "fait_original": "Travaille au Café Luna",
    "sujet_nom": "Justine Lépicier",
    "raison": "A été licenciée"
  }
]

### Types de sujets
pnj | lieu | valentin | monde | objet

### Catégories
etat | relation | evenement | promesse | connaissance | secret | trait | objectif

### Règles
- 0 à 5 faits nouveaux par réponse MAX
- Privilégie : relations durables, états, promesses, secrets
- NE PAS extraire : ambiance, émotions passagères, détails vestimentaires
- Importance 5 = changerait fondamentalement les interactions futures
- Importance 1 = enrichissement optionnel
`;

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
	similarite,
	PROMPT_ADDON_FAITS
};
