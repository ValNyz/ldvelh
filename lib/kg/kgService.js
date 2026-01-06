/**
 * Service Knowledge Graph pour LDVELH
 * Lecture depuis le KG avec cache intégré
 * 
 * CORRECTIONS:
 * - Gestion intelligente des quantités (inventaire)
 * - Validation des états (jauges 0-5, crédits >= 0)
 * - Race conditions via transactions SQL
 * - Fuzzy matching pour éviter doublons
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

/**
 * Valide et arrondit une valeur de jauge
 */
function validerJauge(attribut, valeur) {
	const config = JAUGES_CONFIG[attribut];
	if (!config) return valeur;

	let val = parseFloat(valeur);
	if (isNaN(val)) return config.min;

	// Arrondi
	val = Math.round(val / config.arrondi) * config.arrondi;

	// Bornes
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

/**
 * Récupère les relations "possede" avec détails pour fuzzy matching
 */
export async function getRelationsPossede(supabase, partieId) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return [];

	const { data, error } = await supabase
		.from('kg_relations')
		.select('id, cible_id, proprietes, cycle_debut')
		.eq('partie_id', partieId)
		.eq('source_id', protagoniste.id)
		.eq('type_relation', 'possede')
		.is('cycle_fin', null);

	if (error) return [];
	return data || [];
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

export async function getEvenementsAVenir(supabase, partieId, cycleActuel, limit = 10) {
	return withCache(partieId, 'evenements', async () => {
		const { data, error } = await supabase
			.from('kg_v_evenements_a_venir')
			.select('*')
			.eq('partie_id', partieId)
			.order('cycle')
			.limit(limit);
		if (error) return [];
		return data || [];
	}, `avenir:${cycleActuel}`);
}

/**
 * Récupère les transactions du cycle actuel (pour fuzzy matching)
 */
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
		type: evt.titre?.startsWith('achat') ? 'achat' :
			evt.titre?.startsWith('vente') ? 'vente' : 'autre',
		montant: evt.montant,
		description: evt.description || evt.titre,
		objet: evt.description?.match(/objet: (.+)/i)?.[1] || null
	}));
}

// ============================================================================
// ÉCRITURE AVEC VALIDATION ET RACE CONDITION FIX
// ============================================================================


// ============================================================================
// ÉCRITURE AVEC VALIDATION ET RACE CONDITION FIX
// ============================================================================

/**
 * Modifie les crédits de manière atomique (fonction utilitaire)
 * @returns {{ success: boolean, nouveau_solde?: number, erreur?: string }}
 */
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

/**
 * Modifie une jauge de manière atomique (fonction utilitaire)
 * @returns {{ success: boolean, ancienne?: number, nouvelle?: number }}
 */
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

/**
 * Met à jour les stats de Valentin avec validation via fonctions SQL atomiques
 */
export async function updateStatsValentin(supabase, partieId, cycle, deltas) {
	const updates = [];

	// Jauges (énergie, moral, santé)
	for (const attr of ['energie', 'moral', 'sante']) {
		const delta = deltas[attr];
		if (!delta || delta === 0) continue;

		const result = modifierJauge(supabase, partieId, cycle, attr, delta);
		if (result.success) {
			updates.push({ attr, old: result.ancienne, new: result.nouvelle });
		}
	}

	// Crédits
	if (deltas.credits && deltas.credits !== 0) {
		const result = modifierCredits(supabase, partieId, cycle, deltas.credits, 'delta_stats');
		if (result.success) {
			updates.push({ attr: 'credits', new: result.nouveau_solde });
		}
	}

	return updates;
}

/**
 * Crée une transaction avec fuzzy matching et gestion des quantités
 */
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

	// 2. Transaction crédits via fonction atomique
	const txResult = modifierCredits(
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

	const nouveauSolde = txResult.nouveau_solde;

	// 3. Créer l'événement transaction (pour historique)
	const { data: evt, error: evtError } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: 'passe',
			categorie: 'transaction',
			titre: transaction.description || `${transaction.type}: ${transaction.montant} cr`,
			description: transaction.objet ? `objet: ${transaction.objet}` : null,
			cycle,
			heure: transaction.heure,
			montant: transaction.montant,
			certitude: 'certain',
			verite: true
		})
		.select()
		.single();

	if (evtError) {
		console.error('[KG] Erreur création événement transaction:', evtError);
		// Transaction crédits déjà faite, on continue quand même
	}

	// 4. Gestion inventaire - ACHAT
	if (transaction.objet && transaction.montant < 0) {
		await gererAchatObjet(supabase, partieId, cycle, protagoniste.id, transaction);
	}

	// 5. Gestion inventaire - VENTE
	if (transaction.objet && transaction.montant > 0) {
		await gererVenteObjet(supabase, partieId, cycle, protagoniste.id, transaction);
	}

	return { success: true, transaction_id: evt?.id, nouveau_solde: nouveauSolde };
}

/**
 * Gère l'achat d'un objet (création ou incrémentation)
 */
async function gererAchatObjet(supabase, partieId, cycle, protagonisteId, transaction) {
	const quantite = transaction.quantite || 1;

	// Récupérer inventaire et objets existants
	const [inventaire, objets, relationsPossede] = await Promise.all([
		getInventaire(supabase, partieId),
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	// Fuzzy matching sur l'objet
	const match = fuzzyFindObjet(transaction.objet, objets, relationsPossede, 70);

	if (match) {
		// Objet existant trouvé
		const objetId = match.objet.id;

		// Chercher la relation possede existante
		const relExistante = relationsPossede.find(r => r.cible_id === objetId);

		if (relExistante) {
			// Incrémenter la quantité
			const ancienneQte = relExistante.proprietes?.quantite || 1;
			await supabase
				.from('kg_relations')
				.update({
					proprietes: {
						...relExistante.proprietes,
						quantite: ancienneQte + quantite,
						dernier_cycle_utilise: cycle
					}
				})
				.eq('id', relExistante.id);

			console.log(`[KG] Inventaire: +${quantite} ${match.objet.nom} (total: ${ancienneQte + quantite})`);
		} else {
			// Créer la relation (on possède maintenant cet objet)
			await supabase.rpc('kg_upsert_relation', {
				p_partie_id: partieId,
				p_source_id: protagonisteId,
				p_cible_id: objetId,
				p_type: 'possede',
				p_proprietes: { quantite, depuis_cycle: cycle, dernier_cycle_utilise: cycle },
				p_cycle: cycle,
				p_certitude: 'certain',
				p_verite: true,
				p_source_info: null
			});
			console.log(`[KG] Inventaire: nouveau possession ${match.objet.nom} x${quantite}`);
		}

		// Ajouter alias si fuzzy match < 90%
		if (match.ajouterAlias) {
			await ajouterAliasSiNouveau(supabase, objetId, transaction.objet);
		}
	} else {
		// Nouvel objet
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
				proprietes: { quantite, depuis_cycle: cycle, dernier_cycle_utilise: cycle }
			}
		], cycle);

		console.log(`[KG] Inventaire: nouvel objet ${transaction.objet} x${quantite}`);
	}

	cacheInvalidate(partieId, 'inventaire');
	cacheInvalidateType(partieId, 'objets');
}

/**
 * Gère la vente d'un objet (décrémentation ou suppression)
 */
async function gererVenteObjet(supabase, partieId, cycle, protagonisteId, transaction) {
	const quantiteVendue = transaction.quantite || 1;

	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(transaction.objet, objets, relationsPossede, 70);

	if (!match) {
		console.warn(`[KG] Vente: objet non trouvé dans inventaire: ${transaction.objet}`);
		return;
	}

	const objetId = match.objet.id;
	const relExistante = relationsPossede.find(r => r.cible_id === objetId);

	if (!relExistante) {
		console.warn(`[KG] Vente: relation possede non trouvée pour: ${match.objet.nom}`);
		return;
	}

	const ancienneQte = relExistante.proprietes?.quantite || 1;
	const nouvelleQte = ancienneQte - quantiteVendue;

	if (nouvelleQte <= 0) {
		// Terminer la relation (plus de cet objet)
		await supabase
			.from('kg_relations')
			.update({
				cycle_fin: cycle,
				raison_fin: 'vendu'
			})
			.eq('id', relExistante.id);

		console.log(`[KG] Inventaire: ${match.objet.nom} vendu (supprimé)`);
	} else {
		// Décrémenter
		await supabase
			.from('kg_relations')
			.update({
				proprietes: {
					...relExistante.proprietes,
					quantite: nouvelleQte,
					dernier_cycle_utilise: cycle
				}
			})
			.eq('id', relExistante.id);

		console.log(`[KG] Inventaire: -${quantiteVendue} ${match.objet.nom} (reste: ${nouvelleQte})`);
	}

	cacheInvalidate(partieId, 'inventaire');
	cacheInvalidateType(partieId, 'objets');
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
