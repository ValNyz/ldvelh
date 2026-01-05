/**
 * Service Knowledge Graph pour LDVELH
 * Gestion lecture/écriture du graphe d'entités, relations, événements, états
 */

// ============================================================================
// LECTURE — ENTITÉS
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

	return data; // UUID ou null
}

/**
 * Récupère une entité complète par ID
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

/**
 * Récupère le protagoniste (Valentin)
 */
export async function getProtagoniste(supabase, partieId) {
	const { data, error } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('partie_id', partieId)
		.eq('type', 'protagoniste')
		.is('cycle_disparition', null)
		.single();

	if (error) return null;
	return data;
}

/**
 * Récupère l'IA personnelle
 */
export async function getIA(supabase, partieId) {
	const { data, error } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('partie_id', partieId)
		.eq('type', 'ia')
		.is('cycle_disparition', null)
		.single();

	if (error) return null;
	return data;
}

/**
 * Récupère toutes les entités d'un type
 */
export async function getEntitesParType(supabase, partieId, type) {
	const { data, error } = await supabase
		.from('kg_entites')
		.select('*')
		.eq('partie_id', partieId)
		.eq('type', type)
		.is('cycle_disparition', null)
		.order('nom');

	if (error) return [];
	return data || [];
}

/**
 * Récupère tous les personnages (PNJ)
 */
export async function getPersonnages(supabase, partieId) {
	return getEntitesParType(supabase, partieId, 'personnage');
}

/**
 * Récupère tous les lieux
 */
export async function getLieux(supabase, partieId) {
	return getEntitesParType(supabase, partieId, 'lieu');
}

/**
 * Récupère un lieu par nom avec sa hiérarchie
 */
export async function getLieuAvecHierarchie(supabase, partieId, nomLieu) {
	const lieuId = await trouverEntite(supabase, partieId, nomLieu, 'lieu');
	if (!lieuId) return null;

	const lieu = await getEntite(supabase, lieuId);
	if (!lieu) return null;

	// Chercher le parent (relation situe_dans)
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

// PNJ fréquents d'un lieu
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
// LECTURE — RELATIONS
// ============================================================================

/**
 * Récupère les relations d'une entité (sortantes et entrantes)
 */
export async function getRelationsEntite(supabase, partieId, entiteId, options = {}) {
	const { actives = true, types = null, direction = 'both' } = options;

	let query = supabase
		.from('kg_v_relations_actives')
		.select('*')
		.eq('partie_id', partieId);

	if (direction === 'source' || direction === 'both') {
		query = query.or(`source_id.eq.${entiteId}`);
	}
	if (direction === 'cible' || direction === 'both') {
		query = query.or(`cible_id.eq.${entiteId}`);
	}

	if (types?.length > 0) {
		query = query.in('type_relation', types);
	}

	const { data, error } = await query;
	if (error) return [];
	return data || [];
}

/**
 * Récupère la relation "connait" entre Valentin et un personnage
 */
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

/**
 * Récupère toutes les relations de Valentin avec les personnages
 */
export async function getRelationsValentin(supabase, partieId) {
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
}

/**
 * Récupère l'inventaire de Valentin
 */
export async function getInventaire(supabase, partieId) {
	const { data, error } = await supabase
		.from('kg_v_inventaire')
		.select('*')
		.eq('partie_id', partieId);

	if (error) return [];
	return data || [];
}

// ============================================================================
// LECTURE — ÉTATS
// ============================================================================

/**
 * Récupère les états actuels d'une entité
 */
export async function getEtatsEntite(supabase, entiteId) {
	const { data, error } = await supabase
		.from('kg_etats')
		.select('attribut, valeur, details, certitude, verite')
		.eq('entite_id', entiteId)
		.is('cycle_fin', null);

	if (error) return {};

	// Convertir en objet { attribut: valeur }
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

/**
 * Récupère un état spécifique
 */
export async function getEtat(supabase, entiteId, attribut) {
	const { data, error } = await supabase
		.from('kg_etats')
		.select('valeur, details')
		.eq('entite_id', entiteId)
		.eq('attribut', attribut)
		.is('cycle_fin', null)
		.single();

	if (error) return null;
	return data?.valeur;
}

/**
 * Récupère les stats de Valentin (énergie, moral, santé, crédits)
 */
export async function getStatsValentin(supabase, partieId) {
	const protagoniste = await getProtagoniste(supabase, partieId);

	if (!protagoniste) {
		return { energie: 3, moral: 3, sante: 5, credits: 1400 };
	}

	const etats = await getEtatsEntite(supabase, protagoniste.id);

	const result = {
		energie: parseInt(etats.energie?.valeur) || 3,
		moral: parseInt(etats.moral?.valeur) || 3,
		sante: parseInt(etats.sante?.valeur) || 5,
		credits: parseInt(etats.credits?.valeur) || 1400
	};

	return result;
}

// ============================================================================
// LECTURE — ÉVÉNEMENTS
// ============================================================================

/**
 * Récupère les événements d'un cycle
 */
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

/**
 * Récupère les événements planifiés à venir
 */
export async function getEvenementsAVenir(supabase, partieId, cycleActuel, limit = 10) {
	const { data, error } = await supabase
		.from('kg_v_evenements_a_venir')
		.select('*')
		.eq('partie_id', partieId)
		.gte('cycle', cycleActuel)
		.order('cycle')
		.limit(limit);

	if (error) return [];
	return data || [];
}

/**
 * Récupère les événements impliquant une entité
 */
export async function getEvenementsEntite(supabase, partieId, entiteId, limit = 20) {
	const { data, error } = await supabase
		.from('kg_evenement_participants')
		.select(`
		  role,
		  kg_evenements(*)
		`)
		.eq('entite_id', entiteId)
		.order('kg_evenements(cycle)', { ascending: false })
		.limit(limit);

	if (error) return [];
	return (data || []).map(d => ({ ...d.kg_evenements, role: d.role }));
}

// ============================================================================
// ÉCRITURE — OPÉRATIONS KG
// ============================================================================

/**
 * Applique une liste d'opérations KG (depuis Haiku)
 * Retourne les résultats et erreurs
 */
export async function appliquerOperations(supabase, partieId, operations, cycle) {
	const resultats = {
		entites_creees: 0,
		entites_modifiees: 0,
		relations_creees: 0,
		relations_modifiees: 0,
		relations_terminees: 0,
		evenements_crees: 0,
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
					await opPlanifierEvenement(supabase, partieId, op, resultats);
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

	return resultats;
}

// --- Opérations individuelles ---

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
	// Résoudre source et cible
	let sourceId = await trouverEntite(supabase, partieId, op.source);
	let cibleId = await trouverEntite(supabase, partieId, op.cible);

	// Créer les entités manquantes si besoin
	if (!sourceId) {
		sourceId = await supabase.rpc('kg_upsert_entite', {
			p_partie_id: partieId,
			p_type: op.source_type || 'personnage',
			p_nom: op.source,
			p_alias: [],
			p_proprietes: {},
			p_cycle: cycle,
			p_confirme: false
		}).then(r => r.data);
		resultats.entites_creees++;
	}

	if (!cibleId) {
		cibleId = await supabase.rpc('kg_upsert_entite', {
			p_partie_id: partieId,
			p_type: op.cible_type || 'personnage',
			p_nom: op.cible,
			p_alias: [],
			p_proprietes: {},
			p_cycle: cycle,
			p_confirme: false
		}).then(r => r.data);
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

	// Récupérer la relation existante
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
	// Résoudre le lieu si fourni
	let lieuId = null;
	if (op.lieu) {
		lieuId = await trouverEntite(supabase, partieId, op.lieu, 'lieu');
	}

	// Créer l'événement
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

	// Ajouter les participants
	if (op.participants?.length > 0) {
		const participants = [];
		for (const p of op.participants) {
			const nom = typeof p === 'string' ? p : p.nom;
			const role = typeof p === 'string' ? 'participant' : (p.role || 'participant');

			let entiteId = await trouverEntite(supabase, partieId, nom);

			// Créer l'entité si pas trouvée (protagoniste = Valentin)
			if (!entiteId && nom.toLowerCase() === 'valentin') {
				const prot = await getProtagoniste(supabase, partieId);
				entiteId = prot?.id;
			}

			if (entiteId) {
				participants.push({
					evenement_id: evt.id,
					entite_id: entiteId,
					role
				});
			}
		}

		if (participants.length > 0) {
			await supabase.from('kg_evenement_participants').insert(participants);
		}
	}

	resultats.evenements_crees++;
	return evt;
}

async function opPlanifierEvenement(supabase, partieId, op, resultats) {
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

	// Ajouter les participants
	if (op.participants?.length > 0) {
		const participants = [];
		for (const nom of op.participants) {
			const entiteId = await trouverEntite(supabase, partieId, nom);
			if (entiteId) {
				participants.push({ evenement_id: evt.id, entite_id: entiteId, role: 'participant' });
			}
		}
		if (participants.length > 0) {
			await supabase.from('kg_evenement_participants').insert(participants);
		}
	}

	resultats.evenements_crees++;
}

async function opAnnulerEvenement(supabase, partieId, op, resultats) {
	const { error } = await supabase
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
	resultats.evenements_crees++; // Compte comme modification
}

// ============================================================================
// ÉCRITURE — FONCTIONS DE COMMODITÉ
// ============================================================================

/**
 * Met à jour les stats de Valentin (raccourci)
 */
export async function updateStatsValentin(supabase, partieId, cycle, deltas) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	const stats = await getStatsValentin(supabase, partieId);

	const nouveauxEtats = [];

	if (deltas.energie !== undefined && deltas.energie !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.energie + deltas.energie));
		nouveauxEtats.push({ attribut: 'energie', valeur: String(newVal) });
	}

	if (deltas.moral !== undefined && deltas.moral !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.moral + deltas.moral));
		nouveauxEtats.push({ attribut: 'moral', valeur: String(newVal) });
	}

	if (deltas.sante !== undefined && deltas.sante !== 0) {
		const newVal = Math.max(1, Math.min(5, stats.sante + deltas.sante));
		nouveauxEtats.push({ attribut: 'sante', valeur: String(newVal) });
	}

	if (deltas.credits !== undefined && deltas.credits !== 0) {
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
}

/**
 * Crée une transaction (achat/vente) comme événement
 */
export async function creerTransaction(supabase, partieId, cycle, transaction) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	// Créer l'événement transaction
	const evt = await opCreerEvenement(supabase, partieId, {
		titre: transaction.description || `${transaction.type}: ${transaction.montant} cr`,
		categorie: 'transaction',
		cycle,
		heure: transaction.heure,
		montant: transaction.montant,
		participants: ['Valentin']
	}, cycle, { evenements_crees: 0 });

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

	// Si c'est un achat d'objet, créer la relation possede
	if (transaction.objet && transaction.montant < 0) {
		const operations = [{
			op: 'CREER_ENTITE',
			type: 'objet',
			nom: transaction.objet,
			proprietes: {
				valeur: Math.abs(transaction.montant),
				etat: 'neuf'
			}
		}, {
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: transaction.objet,
			type: 'possede',
			proprietes: { quantite: transaction.quantite || 1 }
		}];

		await appliquerOperations(supabase, partieId, operations, cycle);
	}

	// Si c'est une vente, terminer la relation possede
	if (transaction.objet && transaction.montant > 0) {
		await supabase.rpc('kg_terminer_relation', {
			p_partie_id: partieId,
			p_source_nom: 'Valentin',
			p_cible_nom: transaction.objet,
			p_type: 'possede',
			p_cycle: cycle,
			p_raison: 'vendu'
		});
	}
}

// ============================================================================
// ROLLBACK KG (pour édition de messages)
// ============================================================================

/**
 * Restaure le KG à un état antérieur basé sur un timestamp
 * Supprime tout ce qui a été créé après ce timestamp
 */
export async function rollbackKG(supabase, partieId, timestamp) {
	console.log(`[KG] Rollback vers ${timestamp}`);

	// 1. Supprimer les événements créés après
	const { data: eventsToDelete } = await supabase
		.from('kg_evenements')
		.select('id')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (eventsToDelete?.length > 0) {
		const eventIds = eventsToDelete.map(e => e.id);
		await supabase
			.from('kg_evenement_participants')
			.delete()
			.in('evenement_id', eventIds);
		await supabase
			.from('kg_evenements')
			.delete()
			.in('id', eventIds);
		console.log(`[KG] ${eventsToDelete.length} événements supprimés`);
	}

	// 2. Supprimer les états créés après et restaurer les précédents
	const { data: etatsToDelete } = await supabase
		.from('kg_etats')
		.select('id, entite_id, attribut, cycle_debut')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (etatsToDelete?.length > 0) {
		// Pour chaque état supprimé, rouvrir l'état précédent
		for (const etat of etatsToDelete) {
			// Rouvrir l'état précédent (retirer cycle_fin)
			await supabase
				.from('kg_etats')
				.update({ cycle_fin: null })
				.eq('partie_id', partieId)
				.eq('entite_id', etat.entite_id)
				.eq('attribut', etat.attribut)
				.eq('cycle_fin', etat.cycle_debut);
		}

		// Supprimer les nouveaux états
		await supabase
			.from('kg_etats')
			.delete()
			.in('id', etatsToDelete.map(e => e.id));
		console.log(`[KG] ${etatsToDelete.length} états rollback`);
	}

	// 3. Supprimer les relations créées après
	const { data: relationsToDelete } = await supabase
		.from('kg_relations')
		.select('id')
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	if (relationsToDelete?.length > 0) {
		await supabase
			.from('kg_relations')
			.delete()
			.in('id', relationsToDelete.map(r => r.id));
		console.log(`[KG] ${relationsToDelete.length} relations supprimées`);
	}

	// 4. Rouvrir les relations fermées après ce timestamp
	await supabase
		.from('kg_relations')
		.update({ cycle_fin: null, raison_fin: null })
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('cycle_fin', 'is', null);

	// 5. Supprimer les entités créées après (sauf protagoniste/IA)
	await supabase
		.from('kg_entites')
		.delete()
		.eq('partie_id', partieId)
		.gt('created_at', timestamp)
		.not('type', 'in', '("protagoniste","ia")');

	// 6. Supprimer les scènes créées après
	await supabase
		.from('scenes')
		.delete()
		.eq('partie_id', partieId)
		.gt('created_at', timestamp);

	// 7. Rouvrir la dernière scène (si elle était fermée)
	const { data: lastScene } = await supabase
		.from('scenes')
		.select('id, statut')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: false })
		.limit(1)
		.maybeSingle();

	if (lastScene && lastScene.statut !== 'en_cours') {
		await supabase
			.from('scenes')
			.update({ statut: 'en_cours', heure_fin: null, resume: null })
			.eq('id', lastScene.id);
	}

	console.log(`[KG] Rollback terminé`);
}

// ============================================================================
// MÉTRIQUES
// ============================================================================

/**
 * Log une extraction pour métriques
 */
export async function logExtraction(supabase, partieId, cycle, sceneId, metrics) {
	const { error } = await supabase.from('kg_extraction_logs').insert({
		partie_id: partieId,
		cycle,
		scene_id: sceneId,
		duree_ms: metrics.duree_ms,
		nb_operations: metrics.nb_operations || 0,
		nb_entites_creees: metrics.entites_creees || 0,
		nb_relations_creees: metrics.relations_creees || 0,
		nb_evenements_crees: metrics.evenements_crees || 0,
		nb_etats_modifies: metrics.etats_modifies || 0,
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

// ============================================================================
// EXPORT LISTE ENTITÉS (pour prompt Haiku)
// ============================================================================

/**
 * Génère la liste des entités connues pour le prompt Haiku
 */
export async function getEntitesConnuesPourHaiku(supabase, partieId) {
	const [personnages, lieux, organisations, objets] = await Promise.all([
		getEntitesParType(supabase, partieId, 'personnage'),
		getEntitesParType(supabase, partieId, 'lieu'),
		getEntitesParType(supabase, partieId, 'organisation'),
		getInventaire(supabase, partieId)
	]);

	const protagoniste = await getProtagoniste(supabase, partieId);

	return {
		protagoniste: protagoniste?.nom || 'Valentin',
		personnages: personnages.map(p => ({
			nom: p.nom,
			alias: p.alias || []
		})),
		lieux: lieux.map(l => ({
			nom: l.nom,
			alias: l.alias || []
		})),
		organisations: organisations.map(o => ({
			nom: o.nom,
			alias: o.alias || []
		})),
		objets: objets.map(o => o.objet_nom)
	};
}
