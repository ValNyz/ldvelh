
/**
 * Service Knowledge Graph pour LDVELH
 * Lecture depuis le KG avec cache intégré
 * 
 */

import {
	withCache,
	cacheInvalidate,
	cacheInvalidateType,
	cacheInvalidatePartie
} from '../cache/sessionCache.js';
import { appliquerOperations } from './kgOperations.js';
import {
	fuzzyFindObjet,
	fuzzyFindTransaction,
	ajouterAliasSiNouveau
} from '../utils/fuzzyMatching.js';

// ============================================================================
// IMPORT DU SERVICE INVENTAIRE (NOUVEAU)
// ============================================================================

import {
	traiterTransaction,
	getRelationsPossede,
	TYPES_TRANSACTION
} from './inventoryService.js';

// Re-export pour usage externe
export { traiterTransaction, getRelationsPossede, TYPES_TRANSACTION };
export { appliquerOperations } from './kgOperations.js';

// ============================================================================
// CONSTANTES DE VALIDATION
// ============================================================================

const JAUGES_CONFIG = {
	energie: { min: 0, max: 5, arrondi: 0.5 },
	moral: { min: 0, max: 5, arrondi: 0.5 },
	sante: { min: 0, max: 5, arrondi: 0.5 },
	credits: { min: 0, max: Infinity, arrondi: 1 }
};

function validerJauge(attribut, valeur) {
	const config = JAUGES_CONFIG[attribut];
	if (!config) return valeur;

	let val = parseFloat(valeur);
	if (isNaN(val)) return config.min;

	val = Math.round(val / config.arrondi) * config.arrondi;
	val = Math.max(config.min, Math.min(config.max, val));

	return val;
}

// ============================================================================
// RECHERCHE D'ENTITÉS
// ============================================================================

export async function trouverEntite(supabase, partieId, nom, type = null) {
	const { data, error } = await supabase.rpc('kg_trouver_entite', {
		p_partie_id: partieId,
		p_nom: nom,
		p_type: type
	});
	if (error) {
		console.error('[KG] Erreur trouverEntite:', error);
		return null;
	}
	return data;
}

export async function getEntite(supabase, entiteId) {
	const { data, error } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('id', entiteId)
		.single();
	if (error) return null;
	return data;
}

// ============================================================================
// ENTITÉS PRINCIPALES (AVEC CACHE)
// ============================================================================

export async function getProtagoniste(supabase, partieId) {
	return withCache(partieId, 'protagoniste', async () => {
		const { data, error } = await supabase
			.from('kg_entites')
			.select('*')
			.eq('partie_id', partieId)
			.eq('type', 'protagoniste')
			.is('cycle_disparition', null)
			.single();
		if (error) return null;
		return data;
	});
}

export async function getIA(supabase, partieId) {
	return withCache(partieId, 'ia', async () => {
		const { data, error } = await supabase
			.from('kg_entites')
			.select('*')
			.eq('partie_id', partieId)
			.eq('type', 'ia')
			.is('cycle_disparition', null)
			.single();
		if (error) return null;
		return data;
	});
}

// ============================================================================
// LISTES D'ENTITÉS (AVEC CACHE)
// ============================================================================

export async function getEntitesParType(supabase, partieId, type) {
	const cacheKey = type === 'personnage' ? 'personnages' :
		type === 'objet' ? 'objets' : type;

	return withCache(partieId, cacheKey, async () => {
		const { data, error } = await supabase
			.from('kg_entites')
			.select('*')
			.eq('partie_id', partieId)
			.eq('type', type)
			.is('cycle_disparition', null)
			.order('nom');
		if (error) return [];
		return data || [];
	});
}

export async function getPersonnages(supabase, partieId) {
	return getEntitesParType(supabase, partieId, 'personnage');
}

export async function getLieux(supabase, partieId) {
	return getEntitesParType(supabase, partieId, 'lieu');
}

// ============================================================================
// LIEUX AVEC HIÉRARCHIE
// ============================================================================

export async function getLieuAvecHierarchie(supabase, partieId, nomLieu) {
	const lieuId = await trouverEntite(supabase, partieId, nomLieu, 'lieu');
	if (!lieuId) return null;

	const lieu = await getEntite(supabase, lieuId);
	if (!lieu) return null;

	const { data: relParent } = await supabase
		.from('kg_relations')
		.select(`cible_id, kg_entites!kg_relations_cible_id_fkey(nom, proprietes)`)
		.eq('source_id', lieuId)
		.eq('type_relation', 'situe_dans')
		.is('cycle_fin', null)
		.single();

	return { ...lieu, parent: relParent?.kg_entites || null };
}

export async function getPnjsFrequentsLieu(supabase, partieId, lieuId) {
	const { data, error } = await supabase
		.from('kg_relations')
		.select(`source_id, proprietes, kg_entites!kg_relations_source_id_fkey(nom, proprietes)`)
		.eq('cible_id', lieuId)
		.eq('type_relation', 'frequente')
		.is('cycle_fin', null);

	if (error || !data) return [];
	return data.map(r => ({
		nom: r.kg_entites.nom,
		regularite: r.proprietes?.regularite || 'parfois',
		periode: r.proprietes?.periode || 'aléatoire'
	}));
}

// ============================================================================
// RELATIONS (AVEC CACHE)
// ============================================================================

export async function getRelationsValentin(supabase, partieId) {
	return withCache(partieId, 'relations', async () => {
		const protagoniste = await getProtagoniste(supabase, partieId);
		if (!protagoniste) return [];

		const { data, error } = await supabase
			.from('kg_v_relations_actives')
			.select('*')
			.eq('partie_id', partieId)
			.eq('source_id', protagoniste.id)
			.eq('cible_type', 'personnage');

		if (error) return [];
		return data || [];
	});
}

export async function getRelationConnait(supabase, partieId, personnageNom) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return null;

	const personnageId = await trouverEntite(supabase, partieId, personnageNom, 'personnage');
	if (!personnageId) return null;

	const { data, error } = await supabase
		.from('kg_relations')
		.select('*')
		.eq('partie_id', partieId)
		.eq('source_id', protagoniste.id)
		.eq('cible_id', personnageId)
		.eq('type_relation', 'connait')
		.is('cycle_fin', null)
		.single();

	if (error) return null;
	return data;
}

export async function getArcsPnj(supabase, partieId, pnjId) {
	const { data, error } = await supabase
		.from('kg_relations')
		.select(`cible_id, proprietes, kg_entites!kg_relations_cible_id_fkey(nom, proprietes)`)
		.eq('source_id', pnjId)
		.eq('type_relation', 'implique_dans')
		.is('cycle_fin', null);

	if (error || !data) return [];
	return data
		.filter(r => r.kg_entites?.proprietes?.type_arc === 'pnj_personnel')
		.map(r => ({
			nom: r.kg_entites.nom,
			progression: r.kg_entites.proprietes?.progression || 0,
			etat: r.kg_entites.proprietes?.etat || 'actif'
		}));
}

// ============================================================================
// INVENTAIRE (AVEC CACHE) - Vue enrichie
// ============================================================================

export async function getInventaire(supabase, partieId) {
	return withCache(partieId, 'inventaire', async () => {
		const { data, error } = await supabase
			.from('kg_v_inventaire')
			.select('*')
			.eq('partie_id', partieId);
		if (error) return [];
		return data || [];
	});
}

// ============================================================================
// ÉTATS
// ============================================================================

export async function getEtatsEntite(supabase, entiteId) {
	const { data, error } = await supabase
		.from('kg_etats')
		.select('attribut, valeur, details, certitude, verite')
		.eq('entite_id', entiteId)
		.is('cycle_fin', null);

	if (error) return {};
	const etats = {};
	for (const e of (data || [])) {
		etats[e.attribut] = {
			valeur: e.valeur,
			details: e.details,
			certitude: e.certitude,
			verite: e.verite
		};
	}
	return etats;
}

export async function getStatsValentin(supabase, partieId, protagonisteOptional = null) {
	return withCache(partieId, 'stats', async () => {
		const protagoniste = protagonisteOptional || await getProtagoniste(supabase, partieId);
		if (!protagoniste) {
			return { energie: 3, moral: 3, sante: 5, credits: 1400 };
		}

		const etats = await getEtatsEntite(supabase, protagoniste.id);
		return {
			energie: validerJauge('energie', etats.energie?.valeur) || 3,
			moral: validerJauge('moral', etats.moral?.valeur) || 3,
			sante: validerJauge('sante', etats.sante?.valeur) || 5,
			credits: validerJauge('credits', etats.credits?.valeur) || 1400
		};
	});
}

// ============================================================================
// ÉVÉNEMENTS (AVEC CACHE)
// ============================================================================

export async function getEvenementsCycle(supabase, partieId, cycle) {
	const { data, error } = await supabase
		.from('kg_evenements')
		.select(`*, kg_entites!kg_evenements_lieu_id_fkey(nom),
      kg_evenement_participants(role, kg_entites(nom, type))`)
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.eq('type', 'passe')
		.order('created_at');

	if (error) return [];
	return data || [];
}

export async function getEvenementsAVenir(supabase, partieId, cycleActuel, options = {}) {
	const {
		limit = 10,
		cycleMin = null,
		skipCache = false
	} = options;

	const fetcher = async () => {
		let query = supabase
			.from('kg_v_evenements_a_venir')
			.select('*')
			.eq('partie_id', partieId)
			.gte('cycle', cycleMin ?? cycleActuel)
			.order('cycle');

		if (limit) {
			query = query.limit(limit);
		}

		const { data, error } = await query;
		if (error) return [];
		return data || [];
	};

	if (skipCache) {
		return fetcher();
	}

	return withCache(partieId, 'evenements', fetcher, `avenir:${cycleMin ?? cycleActuel}`);
}

export async function getTransactionsCycle(supabase, partieId, cycle) {
	const { data, error } = await supabase
		.from('kg_evenements')
		.select('*')
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.eq('categorie', 'transaction')
		.eq('type', 'passe');

	if (error) return [];

	return (data || []).map(evt => ({
		id: evt.id,
		type: evt.titre?.split(':')[0]?.toLowerCase() || 'autre',
		montant: evt.montant,
		description: evt.description || evt.titre,
		objet: evt.description?.match(/objet: (.+)/i)?.[1] || null
	}));
}

// ============================================================================
// ÉCRITURE STATS
// ============================================================================

async function modifierCredits(supabase, partieId, cycle, montant, description = null) {
	const { data, error } = await supabase.rpc('kg_transaction_credits', {
		p_partie_id: partieId,
		p_montant: montant,
		p_cycle: cycle,
		p_description: description
	});

	if (error) {
		console.error('[KG] Erreur modifierCredits:', error);
		return { success: false, erreur: error.message };
	}

	const result = data?.[0];
	if (!result?.success) {
		return { success: false, erreur: result?.erreur, nouveau_solde: result?.nouveau_solde };
	}

	cacheInvalidate(partieId, 'stats');
	return { success: true, nouveau_solde: result.nouveau_solde };
}

async function modifierJauge(supabase, partieId, cycle, attribut, delta) {
	const { data, error } = await supabase.rpc('kg_update_jauge', {
		p_partie_id: partieId,
		p_attribut: attribut,
		p_delta: delta,
		p_cycle: cycle
	});

	if (error) {
		console.error(`[KG] Erreur modifierJauge ${attribut}:`, error);
		return { success: false };
	}

	const result = data?.[0];
	if (!result?.success) {
		return { success: false };
	}

	cacheInvalidate(partieId, 'stats');
	return { success: true, ancienne: result.ancienne_valeur, nouvelle: result.nouvelle_valeur };
}

export async function updateStatsValentin(supabase, partieId, cycle, deltas) {
	const updates = [];

	for (const attr of ['energie', 'moral', 'sante']) {
		const delta = deltas[attr];
		if (!delta || delta === 0) continue;

		const result = await modifierJauge(supabase, partieId, cycle, attr, delta);
		if (result.success) {
			updates.push({ attr, old: result.ancienne, new: result.nouvelle });
		}
	}

	if (deltas.credits && deltas.credits !== 0) {
		const result = await modifierCredits(supabase, partieId, cycle, deltas.credits, 'delta_stats');
		if (result.success) {
			updates.push({ attr: 'credits', new: result.nouveau_solde });
		}
	}

	return updates;
}

// ============================================================================
// CRÉER TRANSACTION
// ============================================================================

export async function creerTransaction(supabase, partieId, cycle, transaction) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return { success: false, error: 'Protagoniste non trouvé' };

	// 1. Vérifier doublon via fuzzy matching
	const transactionsExistantes = await getTransactionsCycle(supabase, partieId, cycle);
	const doublon = fuzzyFindTransaction(transaction, transactionsExistantes, 80);

	if (doublon) {
		console.log(`[KG] Transaction doublon ignorée (${doublon.confiance}%): ${transaction.description}`);
		return { success: false, doublon: true, raison: doublon.raison };
	}

	// 2. Transaction crédits si montant présent
	let nouveauSolde = null;
	if (transaction.montant && transaction.montant !== 0) {
		const txResult = await modifierCredits(
			supabase,
			partieId,
			cycle,
			transaction.montant,
			transaction.description || `${transaction.type}: ${transaction.montant} cr`
		);

		if (!txResult.success) {
			console.log(`[KG] Transaction refusée: ${txResult.erreur}`);
			return { success: false, error: txResult.erreur, solde: txResult.nouveau_solde };
		}
		nouveauSolde = txResult.nouveau_solde;
	}

	// 3. Créer l'événement transaction (pour historique)
	const { data: evt, error: evtError } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: 'passe',
			categorie: 'transaction',
			titre: `${transaction.type}: ${transaction.description || transaction.objet || ''}`,
			description: transaction.objet ? `objet: ${transaction.objet}` : null,
			cycle,
			heure: transaction.heure,
			montant: transaction.montant || 0,
			certitude: 'certain',
			verite: true
		})
		.select()
		.single();

	if (evtError) {
		console.error('[KG] Erreur création événement transaction:', evtError);
	}

	// 4. Traiter l'inventaire via inventoryService
	const inventoryResult = await traiterTransaction(supabase, partieId, cycle, transaction);

	if (!inventoryResult.success && inventoryResult.error) {
		console.warn(`[KG] Avertissement inventaire: ${inventoryResult.error}`);
	}

	return {
		success: true,
		transaction_id: evt?.id,
		nouveau_solde: nouveauSolde,
		inventory: inventoryResult
	};
}

// ============================================================================
// ROLLBACK
// ============================================================================

export async function rollbackKG(supabase, partieId, timestamp) {
	console.log(`[KG] Rollback vers ${timestamp}`);

	const { data: eventsToDelete } = await supabase
		.from('kg_evenements')
		.select('id')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (eventsToDelete?.length > 0) {
		const eventIds = eventsToDelete.map(e => e.id);
		await supabase.from('kg_evenement_participants').delete().in('evenement_id', eventIds);
		await supabase.from('kg_evenements').delete().in('id', eventIds);
	}

	const { data: etatsToDelete } = await supabase
		.from('kg_etats')
		.select('id, entite_id, attribut, cycle_debut')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (etatsToDelete?.length > 0) {
		for (const etat of etatsToDelete) {
			await supabase
				.from('kg_etats')
				.update({ cycle_fin: null })
				.eq('partie_id', partieId)
				.eq('entite_id', etat.entite_id)
				.eq('attribut', etat.attribut)
				.eq('cycle_fin', etat.cycle_debut);
		}
		await supabase.from('kg_etats').delete().in('id', etatsToDelete.map(e => e.id));
	}

	const { data: relationsToDelete } = await supabase
		.from('kg_relations')
		.select('id')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (relationsToDelete?.length > 0) {
		await supabase.from('kg_relations').delete().in('id', relationsToDelete.map(r => r.id));
	}

	await supabase
		.from('kg_relations')
		.update({ cycle_fin: null, raison_fin: null })
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('cycle_fin', 'is', null);

	await supabase
		.from('kg_entites')
		.delete()
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('type', 'in', '("protagoniste","ia")');

	await supabase.from('scenes').delete().eq('partie_id', partieId).gt('created_at', timestamp);

	const { data: lastScene } = await supabase
		.from('scenes')
		.select('id, statut')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: false })
		.limit(1)
		.maybeSingle();

	if (lastScene?.statut !== 'en_cours') {
		await supabase
			.from('scenes')
			.update({ statut: 'en_cours', heure_fin: null, resume: null })
			.eq('id', lastScene.id);
	}

	cacheInvalidatePartie(partieId);
	console.log(`[KG] Rollback terminé`);
}

// ============================================================================
// EXPORT POUR HAIKU
// ============================================================================

export async function getEntitesConnuesPourHaiku(supabase, partieId) {
	const [personnages, lieux, organisations, objets, protagoniste] = await Promise.all([
		getEntitesParType(supabase, partieId, 'personnage'),
		getEntitesParType(supabase, partieId, 'lieu'),
		getEntitesParType(supabase, partieId, 'organisation'),
		getInventaire(supabase, partieId),
		getProtagoniste(supabase, partieId)
	]);

	return {
		protagoniste: protagoniste?.nom || 'Valentin',
		personnages: personnages.map(p => ({ nom: p.nom, alias: p.alias || [] })),
		lieux: lieux.map(l => ({ nom: l.nom, alias: l.alias || [] })),
		organisations: organisations.map(o => ({ nom: o.nom, alias: o.alias || [] })),
		objets: objets.map(o => o.objet_nom)
	};
}

export { cacheInvalidate, cacheInvalidateType, cacheInvalidatePartie };
