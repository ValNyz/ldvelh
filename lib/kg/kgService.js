/**
 * Service Knowledge Graph pour LDVELH
 * Lecture depuis le KG avec cache intégré
 */

import {
	withCache,
	cacheInvalidate,
	cacheInvalidateType,
	cacheInvalidatePartie
} from '../cache/sessionCache.js';
import { appliquerOperations } from './kgOperations.js';

// Ré-exporter les opérations
export { appliquerOperations } from './kgOperations.js';

// ============================================================================
// RECHERCHE D'ENTITÉS
// ============================================================================

/**
 * Trouve une entité par nom ou alias
 */
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

/**
 * Récupère une entité complète par ID (sans cache - trop de variantes)
 */
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

/**
 * Récupère le protagoniste (Valentin)
 */
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

/**
 * Récupère l'IA personnelle
 */
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

/**
 * Récupère toutes les entités d'un type
 */
export async function getEntitesParType(supabase, partieId, type) {
	return withCache(partieId, type === 'personnage' ? 'personnages' : type, async () => {
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
		.select(`
      cible_id,
      kg_entites!kg_relations_cible_id_fkey(nom, proprietes)
    `)
		.eq('source_id', lieuId)
		.eq('type_relation', 'situe_dans')
		.is('cycle_fin', null)
		.single();

	return {
		...lieu,
		parent: relParent?.kg_entites || null
	};
}

export async function getPnjsFrequentsLieu(supabase, partieId, lieuId) {
	const { data, error } = await supabase
		.from('kg_relations')
		.select(`
      source_id,
      proprietes,
      kg_entites!kg_relations_source_id_fkey(nom, proprietes)
    `)
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

/**
 * Récupère toutes les relations de Valentin avec les personnages
 */
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
		.select(`
      cible_id,
      proprietes,
      kg_entites!kg_relations_cible_id_fkey(nom, proprietes)
    `)
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
// INVENTAIRE (AVEC CACHE)
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
			energie: parseInt(etats.energie?.valeur) || 3,
			moral: parseInt(etats.moral?.valeur) || 3,
			sante: parseInt(etats.sante?.valeur) || 5,
			credits: parseInt(etats.credits?.valeur) || 1400
		};
	});
}

// ============================================================================
// ÉVÉNEMENTS (AVEC CACHE)
// ============================================================================

export async function getEvenementsCycle(supabase, partieId, cycle) {
	const { data, error } = await supabase
		.from('kg_evenements')
		.select(`
      *,
      kg_entites!kg_evenements_lieu_id_fkey(nom),
      kg_evenement_participants(
        role,
        kg_entites(nom, type)
      )
    `)
		.eq('partie_id', partieId)
		.eq('cycle', cycle)
		.eq('type', 'passe')
		.order('created_at');

	if (error) return [];
	return data || [];
}

export async function getEvenementsAVenir(supabase, partieId, cycleActuel, limit = 10) {
	return withCache(partieId, 'evenements', async () => {
		const { data, error } = await supabase
			.from('kg_v_evenements_a_venir')
			.select('*')
			.eq('partie_id', partieId)
			.gte('cycle', cycleActuel)
			.order('cycle')
			.limit(limit);

		if (error) return [];
		return data || [];
	}, `avenir:${cycleActuel}`);
}

// ============================================================================
// ÉCRITURE AVEC INVALIDATION
// ============================================================================

export async function updateStatsValentin(supabase, partieId, cycle, deltas) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	const stats = await getStatsValentin(supabase, partieId, protagoniste);
	const nouveauxEtats = [];

	if (deltas.energie && deltas.energie !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.energie + deltas.energie));
		nouveauxEtats.push({ attribut: 'energie', valeur: String(newVal) });
	}

	if (deltas.moral && deltas.moral !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.moral + deltas.moral));
		nouveauxEtats.push({ attribut: 'moral', valeur: String(newVal) });
	}

	if (deltas.sante && deltas.sante !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.sante + deltas.sante));
		nouveauxEtats.push({ attribut: 'sante', valeur: String(newVal) });
	}

	if (deltas.credits && deltas.credits !== 0) {
		const newVal = stats.credits + deltas.credits;
		nouveauxEtats.push({ attribut: 'credits', valeur: String(newVal) });
	}

	for (const etat of nouveauxEtats) {
		await supabase.rpc('kg_set_etat', {
			p_partie_id: partieId,
			p_entite_id: protagoniste.id,
			p_attribut: etat.attribut,
			p_valeur: etat.valeur,
			p_cycle: cycle,
			p_details: null,
			p_certitude: 'certain',
			p_verite: true
		});
	}

	// Invalider le cache
	cacheInvalidate(partieId, 'stats');
}

export async function creerTransaction(supabase, partieId, cycle, transaction) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	// Créer l'événement
	const { data: evt } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: 'passe',
			categorie: 'transaction',
			titre: transaction.description || `${transaction.type}: ${transaction.montant} cr`,
			cycle,
			heure: transaction.heure,
			montant: transaction.montant,
			certitude: 'certain',
			verite: true
		})
		.select()
		.single();

	// Mettre à jour les crédits
	const stats = await getStatsValentin(supabase, partieId);
	await supabase.rpc('kg_set_etat', {
		p_partie_id: partieId,
		p_entite_id: protagoniste.id,
		p_attribut: 'credits',
		p_valeur: String(stats.credits + transaction.montant),
		p_cycle: cycle,
		p_details: { transaction_id: evt?.id },
		p_certitude: 'certain',
		p_verite: true
	});

	// Invalider les caches
	cacheInvalidate(partieId, 'stats');

	// Si achat d'objet
	if (transaction.objet && transaction.montant < 0) {
		await appliquerOperations(supabase, partieId, [
			{
				op: 'CREER_ENTITE',
				type: 'objet',
				nom: transaction.objet,
				proprietes: { valeur: Math.abs(transaction.montant), etat: 'neuf' }
			},
			{
				op: 'CREER_RELATION',
				source: 'Valentin',
				cible: transaction.objet,
				type: 'possede',
				proprietes: { quantite: transaction.quantite || 1 }
			}
		], cycle);
		cacheInvalidate(partieId, 'inventaire');
	}

	// Si vente
	if (transaction.objet && transaction.montant > 0) {
		await supabase.rpc('kg_terminer_relation', {
			p_partie_id: partieId,
			p_source_nom: 'Valentin',
			p_cible_nom: transaction.objet,
			p_type: 'possede',
			p_cycle: cycle,
			p_raison: 'vendu'
		});
		cacheInvalidate(partieId, 'inventaire');
	}
}

// ============================================================================
// ROLLBACK
// ============================================================================

export async function rollbackKG(supabase, partieId, timestamp) {
	console.log(`[KG] Rollback vers ${timestamp}`);

	// 1. Événements
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

	// 2. États
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

	// 3. Relations
	const { data: relationsToDelete } = await supabase
		.from('kg_relations')
		.select('id')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (relationsToDelete?.length > 0) {
		await supabase.from('kg_relations').delete().in('id', relationsToDelete.map(r => r.id));
	}

	// 4. Rouvrir relations fermées
	await supabase
		.from('kg_relations')
		.update({ cycle_fin: null, raison_fin: null })
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('cycle_fin', 'is', null);

	// 5. Entités
	await supabase
		.from('kg_entites')
		.delete()
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('type', 'in', '("protagoniste","ia")');

	// 6. Scènes
	await supabase.from('scenes').delete().eq('partie_id', partieId).gt('created_at', timestamp);

	// 7. Rouvrir dernière scène
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

	// Invalider tout le cache
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

// Exporter les fonctions d'invalidation pour usage externe
export { cacheInvalidate, cacheInvalidateType, cacheInvalidatePartie };
