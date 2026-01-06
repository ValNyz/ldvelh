/**
 * Opérations d'écriture sur le Knowledge Graph
 * 
 * CORRECTIONS:
 * - Fuzzy matching pour éviter doublons d'événements
 * - Invalidation cache complète (incluant objets)
 */

import {
	cacheInvalidate,
	cacheInvalidateType
} from '../cache/sessionCache.js';
import { fuzzyFindEvenement } from '../utils/fuzzyMatching.js';

// ============================================================================
// HELPERS
// ============================================================================

async function trouverEntite(supabase, partieId, nom, type = null) {
	const { data } = await supabase.rpc('kg_trouver_entite', {
		p_partie_id: partieId,
		p_nom: nom,
		p_type: type
	});
	return data;
}

async function getEntite(supabase, entiteId) {
	const { data } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('id', entiteId)
		.single();
	return data;
}

async function getProtagoniste(supabase, partieId) {
	const { data } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('partie_id', partieId)
		.eq('type', 'protagoniste')
		.is('cycle_disparition', null)
		.single();
	return data;
}

/**
 * Récupère les événements à venir pour fuzzy matching
 */
async function getEvenementsAVenirPourMatch(supabase, partieId, cycleMin) {
	const { data } = await supabase
		.from('kg_evenements')
		.select(`
      id, titre, cycle, heure, lieu_id,
      kg_evenement_participants(kg_entites(nom))
    `)
		.eq('partie_id', partieId)
		.gte('cycle', cycleMin)
		.in('type', ['planifie', 'recurrent'])
		.eq('realise', false)
		.eq('annule', false);

	return (data || []).map(evt => ({
		...evt,
		participants: evt.kg_evenement_participants?.map(p => p.kg_entites?.nom).filter(Boolean) || []
	}));
}

// ============================================================================
// APPLICATION DES OPÉRATIONS
// ============================================================================

/**
 * Applique une liste d'opérations KG
 */
export async function appliquerOperations(supabase, partieId, operations, cycle) {
	const resultats = {
		entites_creees: 0,
		entites_modifiees: 0,
		relations_creees: 0,
		relations_modifiees: 0,
		relations_terminees: 0,
		evenements_crees: 0,
		evenements_ignores: 0,
		etats_modifies: 0,
		erreurs: [],
		contradictions: []
	};

	for (const op of operations) {
		try {
			switch (op.op) {
				case 'CREER_ENTITE':
					await opCreerEntite(supabase, partieId, op, cycle, resultats);
					break;
				case 'MODIFIER_ENTITE':
					await opModifierEntite(supabase, partieId, op, resultats);
					break;
				case 'SUPPRIMER_ENTITE':
					await opSupprimerEntite(supabase, partieId, op, cycle, resultats);
					break;
				case 'CREER_RELATION':
					await opCreerRelation(supabase, partieId, op, cycle, resultats);
					break;
				case 'MODIFIER_RELATION':
					await opModifierRelation(supabase, partieId, op, resultats);
					break;
				case 'TERMINER_RELATION':
					await opTerminerRelation(supabase, partieId, op, cycle, resultats);
					break;
				case 'MODIFIER_ETAT':
					await opModifierEtat(supabase, partieId, op, cycle, resultats);
					break;
				case 'CREER_EVENEMENT':
					await opCreerEvenement(supabase, partieId, op, cycle, resultats);
					break;
				case 'PLANIFIER_EVENEMENT':
					await opPlanifierEvenement(supabase, partieId, op, cycle, resultats);
					break;
				case 'ANNULER_EVENEMENT':
					await opAnnulerEvenement(supabase, partieId, op, resultats);
					break;
				default:
					resultats.erreurs.push(`Opération inconnue: ${op.op}`);
			}
		} catch (err) {
			resultats.erreurs.push(`${op.op} ${op.nom || op.entite || ''}: ${err.message}`);
		}
	}

	invalidateCacheAfterOperations(partieId, resultats, operations);

	return resultats;
}

// ============================================================================
// OPÉRATIONS INDIVIDUELLES
// ============================================================================

async function opCreerEntite(supabase, partieId, op, cycle, resultats) {
	const { data, error } = await supabase.rpc('kg_upsert_entite', {
		p_partie_id: partieId,
		p_type: op.type,
		p_nom: op.nom,
		p_alias: op.alias || [],
		p_proprietes: op.proprietes || {},
		p_cycle: cycle,
		p_confirme: op.confirme !== false
	});

	if (error) throw error;
	resultats.entites_creees++;
	return data;
}

async function opModifierEntite(supabase, partieId, op, resultats) {
	const entiteId = await trouverEntite(supabase, partieId, op.entite);
	if (!entiteId) {
		resultats.erreurs.push(`Entité non trouvée: ${op.entite}`);
		return;
	}

	const updates = { updated_at: new Date().toISOString() };

	if (op.nouveau_nom) updates.nom = op.nouveau_nom;
	if (op.confirme !== undefined) updates.confirme = op.confirme;

	if (op.alias_ajouter?.length > 0) {
		const entite = await getEntite(supabase, entiteId);
		updates.alias = [...new Set([...(entite.alias || []), ...op.alias_ajouter])];
	}

	if (op.proprietes) {
		const entite = await getEntite(supabase, entiteId);
		updates.proprietes = { ...(entite.proprietes || {}), ...op.proprietes };
	}

	const { error } = await supabase
		.from('kg_entites')
		.update(updates)
		.eq('id', entiteId);

	if (error) throw error;
	resultats.entites_modifiees++;
}

async function opSupprimerEntite(supabase, partieId, op, cycle, resultats) {
	const entiteId = await trouverEntite(supabase, partieId, op.entite);
	if (!entiteId) {
		resultats.erreurs.push(`Entité non trouvée: ${op.entite}`);
		return;
	}

	const { error } = await supabase
		.from('kg_entites')
		.update({
			cycle_disparition: cycle,
			raison_disparition: op.raison || null
		})
		.eq('id', entiteId);

	if (error) throw error;
	resultats.entites_modifiees++;
}

async function opCreerRelation(supabase, partieId, op, cycle, resultats) {
	let sourceId = await trouverEntite(supabase, partieId, op.source);
	let cibleId = await trouverEntite(supabase, partieId, op.cible);

	if (!sourceId) {
		const { data } = await supabase.rpc('kg_upsert_entite', {
			p_partie_id: partieId,
			p_type: op.source_type || 'personnage',
			p_nom: op.source,
			p_alias: [],
			p_proprietes: {},
			p_cycle: cycle,
			p_confirme: false
		});
		sourceId = data;
		resultats.entites_creees++;
	}

	if (!cibleId) {
		const { data } = await supabase.rpc('kg_upsert_entite', {
			p_partie_id: partieId,
			p_type: op.cible_type || 'personnage',
			p_nom: op.cible,
			p_alias: [],
			p_proprietes: {},
			p_cycle: cycle,
			p_confirme: false
		});
		cibleId = data;
		resultats.entites_creees++;
	}

	const { data, error } = await supabase.rpc('kg_upsert_relation', {
		p_partie_id: partieId,
		p_source_id: sourceId,
		p_cible_id: cibleId,
		p_type: op.type,
		p_proprietes: op.proprietes || {},
		p_cycle: cycle,
		p_certitude: op.certitude || 'certain',
		p_verite: op.verite !== false,
		p_source_info: op.source_info || null
	});

	if (error) throw error;
	resultats.relations_creees++;
	return data;
}

async function opModifierRelation(supabase, partieId, op, resultats) {
	const sourceId = await trouverEntite(supabase, partieId, op.source);
	const cibleId = await trouverEntite(supabase, partieId, op.cible);

	if (!sourceId || !cibleId) {
		resultats.erreurs.push(`Relation non trouvée: ${op.source} -> ${op.cible}`);
		return;
	}

	const { data: rel } = await supabase
		.from('kg_relations')
		.select('id, proprietes')
		.eq('partie_id', partieId)
		.eq('source_id', sourceId)
		.eq('cible_id', cibleId)
		.eq('type_relation', op.type)
		.is('cycle_fin', null)
		.single();

	if (!rel) {
		resultats.erreurs.push(`Relation non trouvée: ${op.source} -[${op.type}]-> ${op.cible}`);
		return;
	}

	const updates = {
		proprietes: { ...(rel.proprietes || {}), ...(op.proprietes || {}) }
	};
	if (op.certitude) updates.certitude = op.certitude;
	if (op.verite !== undefined) updates.verite = op.verite;

	const { error } = await supabase
		.from('kg_relations')
		.update(updates)
		.eq('id', rel.id);

	if (error) throw error;
	resultats.relations_modifiees++;
}

async function opTerminerRelation(supabase, partieId, op, cycle, resultats) {
	const { data } = await supabase.rpc('kg_terminer_relation', {
		p_partie_id: partieId,
		p_source_nom: op.source,
		p_cible_nom: op.cible,
		p_type: op.type,
		p_cycle: cycle,
		p_raison: op.raison || null
	});

	if (data) {
		resultats.relations_terminees++;
	} else {
		resultats.erreurs.push(`Relation à terminer non trouvée: ${op.source} -[${op.type}]-> ${op.cible}`);
	}
}

async function opModifierEtat(supabase, partieId, op, cycle, resultats) {
	const entiteId = await trouverEntite(supabase, partieId, op.entite);
	if (!entiteId) {
		resultats.erreurs.push(`Entité non trouvée pour état: ${op.entite}`);
		return;
	}

	const { data, error } = await supabase.rpc('kg_set_etat', {
		p_partie_id: partieId,
		p_entite_id: entiteId,
		p_attribut: op.attribut,
		p_valeur: String(op.valeur),
		p_cycle: cycle,
		p_details: op.details || null,
		p_certitude: op.certitude || 'certain',
		p_verite: op.verite !== false
	});

	if (error) throw error;
	if (data) resultats.etats_modifies++;
}

async function opCreerEvenement(supabase, partieId, op, cycle, resultats) {
	let lieuId = null;
	if (op.lieu) {
		lieuId = await trouverEntite(supabase, partieId, op.lieu, 'lieu');
	}

	const { data: evt, error } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: 'passe',
			categorie: op.categorie || 'social',
			titre: op.titre,
			description: op.description || null,
			cycle: op.cycle || cycle,
			heure: op.heure || null,
			lieu_id: lieuId,
			montant: op.montant || null,
			certitude: op.certitude || 'certain',
			verite: op.verite !== false
		})
		.select()
		.single();

	if (error) throw error;

	if (op.participants?.length > 0) {
		await ajouterParticipants(supabase, partieId, evt.id, op.participants);
	}

	resultats.evenements_crees++;
	return evt;
}

/**
 * Planifie un événement avec détection de doublon via fuzzy matching
 */
async function opPlanifierEvenement(supabase, partieId, op, cycle, resultats) {
	// Vérifier doublon via fuzzy matching
	const evenementsExistants = await getEvenementsAVenirPourMatch(
		supabase,
		partieId,
		Math.max(1, (op.cycle_prevu || cycle) - 1)
	);

	const doublon = fuzzyFindEvenement(
		{
			titre: op.titre,
			cycle: op.cycle_prevu,
			heure: op.heure,
			participants: op.participants
		},
		evenementsExistants,
		75 // Seuil
	);

	if (doublon) {
		console.log(`[KG] Événement doublon ignoré (${doublon.confiance}%): "${op.titre}" ≈ "${doublon.evenement.titre}"`);
		resultats.evenements_ignores = (resultats.evenements_ignores || 0) + 1;
		return null;
	}

	// Pas de doublon, créer l'événement
	let lieuId = null;
	if (op.lieu) {
		lieuId = await trouverEntite(supabase, partieId, op.lieu, 'lieu');
	}

	const { data: evt, error } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: op.recurrence ? 'recurrent' : 'planifie',
			categorie: op.categorie || 'social',
			titre: op.titre,
			description: op.description || null,
			cycle: op.cycle_prevu,
			heure: op.heure || null,
			lieu_id: lieuId,
			recurrence: op.recurrence || null,
			realise: false,
			annule: false
		})
		.select()
		.single();

	if (error) throw error;

	if (op.participants?.length > 0) {
		await ajouterParticipants(supabase, partieId, evt.id, op.participants);
	}

	console.log(`[KG] Événement planifié: "${op.titre}" cycle ${op.cycle_prevu}`);
	resultats.evenements_crees++;
	return evt;
}

async function opAnnulerEvenement(supabase, partieId, op, resultats) {
	const { error, count } = await supabase
		.from('kg_evenements')
		.update({
			annule: true,
			raison_annulation: op.raison || null
		})
		.eq('partie_id', partieId)
		.eq('titre', op.titre)
		.eq('realise', false)
		.eq('annule', false);

	if (error) throw error;
	if (count > 0) resultats.evenements_crees++;
}

// ============================================================================
// HELPERS ÉVÉNEMENTS
// ============================================================================

async function ajouterParticipants(supabase, partieId, evenementId, participants) {
	const participantsData = [];

	for (const p of participants) {
		const nom = typeof p === 'string' ? p : p.nom;
		const role = typeof p === 'string' ? 'participant' : (p.role || 'participant');

		let entiteId = await trouverEntite(supabase, partieId, nom);

		if (!entiteId && nom.toLowerCase() === 'valentin') {
			const prot = await getProtagoniste(supabase, partieId);
			entiteId = prot?.id;
		}

		if (entiteId) {
			participantsData.push({ evenement_id: evenementId, entite_id: entiteId, role });
		}
	}

	if (participantsData.length > 0) {
		await supabase.from('kg_evenement_participants').insert(participantsData);
	}
}

// ============================================================================
// INVALIDATION DU CACHE (COMPLÈTE)
// ============================================================================

function invalidateCacheAfterOperations(partieId, resultats, operations) {
	// Entités créées/modifiées
	if (resultats.entites_creees > 0 || resultats.entites_modifiees > 0) {
		cacheInvalidateType(partieId, 'personnages');
		cacheInvalidateType(partieId, 'lieux');
		cacheInvalidateType(partieId, 'objets'); // AJOUTÉ

		// Vérifier si des objets spécifiquement
		const hasObjets = operations.some(op =>
			(op.op === 'CREER_ENTITE' && op.type === 'objet') ||
			(op.op === 'MODIFIER_ENTITE' && op.entite) ||
			(op.op === 'SUPPRIMER_ENTITE' && op.entite)
		);
		if (hasObjets) {
			cacheInvalidate(partieId, 'inventaire');
		}
	}

	// Relations
	if (resultats.relations_creees > 0 || resultats.relations_modifiees > 0 || resultats.relations_terminees > 0) {
		cacheInvalidateType(partieId, 'relations');
		cacheInvalidate(partieId, 'inventaire');
	}

	// États
	if (resultats.etats_modifies > 0) {
		cacheInvalidate(partieId, 'stats');
	}

	// Événements
	if (resultats.evenements_crees > 0) {
		cacheInvalidateType(partieId, 'evenements');
	}
}

// ============================================================================
// MÉTRIQUES
// ============================================================================

export async function logExtraction(supabase, partieId, cycle, sceneId, metrics) {
	const { error } = await supabase.from('kg_extraction_logs').insert({
		partie_id: partieId,
		cycle,
		scene_id: sceneId,
		duree_ms: metrics.duree_ms,
		nb_operations: metrics.nb_operations || 0,
		nb_entites_creees: metrics.entites_creees || 0,
		nb_evenements_crees: metrics.evenements_crees || 0,
		nb_contradictions: metrics.contradictions?.length || 0,
		nb_entites_non_resolues: metrics.entites_non_resolues || 0,
		nb_operations_invalides: metrics.erreurs?.length || 0,
		contradictions: metrics.contradictions || [],
		erreurs: metrics.erreurs || []
	});

	if (error) {
		console.error('[KG] Erreur log extraction:', error);
	}
}
