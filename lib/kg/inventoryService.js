// ============================================================================
// lib/kg/inventoryService.js
// ============================================================================

import { trouverEntite, getEntite, getProtagoniste, getEntitesParType } from './kgService.js';
import { cacheInvalidate, cacheInvalidateType } from '../cache/sessionCache.js';
import { fuzzyFindObjet, ajouterAliasSiNouveau } from '../utils/fuzzyMatching.js';

export const TYPES_TRANSACTION = [
	// Économiques
	'achat', 'vente', 'salaire', 'loyer', 'facture',
	'amende', 'pourboire', 'service', 'remboursement',
	// Transferts
	'don', 'cadeau_recu', 'pret', 'emprunt', 'retour_pret',
	// État
	'perte', 'oubli', 'vol', 'destruction', 'reparation', 'degradation',
	// Déplacement
	'deplacement', 'rangement', 'recuperation'
];

/**
 * Récupère les relations "possede" avec détails
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

/**
 * Traite une transaction selon son type
 */
export async function traiterTransaction(supabase, partieId, cycle, tx) {
	switch (tx.type) {
		case 'achat':
			return gererAchat(supabase, partieId, cycle, tx);
		case 'vente':
			return gererVente(supabase, partieId, cycle, tx);
		case 'don':
			return gererDon(supabase, partieId, cycle, tx);
		case 'cadeau_recu':
			return gererCadeauRecu(supabase, partieId, cycle, tx);
		case 'deplacement':
		case 'rangement':
		case 'recuperation':
			return gererDeplacement(supabase, partieId, cycle, tx);
		case 'perte':
		case 'oubli':
		case 'vol':
			return gererPerte(supabase, partieId, cycle, tx);
		case 'destruction':
			return gererDestruction(supabase, partieId, cycle, tx);
		case 'degradation':
		case 'reparation':
			return gererChangementEtat(supabase, partieId, cycle, tx);
		case 'pret':
			return gererPret(supabase, partieId, cycle, tx);
		case 'emprunt':
			return gererEmprunt(supabase, partieId, cycle, tx);
		case 'retour_pret':
			return gererRetourPret(supabase, partieId, cycle, tx);
		default:
			// Transactions financières simples (salaire, loyer, etc.)
			return { success: true, type: 'financier' };
	}
}

/**
 * Gère un achat avec les nouvelles propriétés
 */
async function gererAchat(supabase, partieId, cycle, tx) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return { success: false, error: 'Protagoniste non trouvé' };

	if (!tx.objet) return { success: true, type: 'financier' };

	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	const quantite = tx.quantite || 1;

	if (match) {
		const relExistante = relationsPossede.find(r => r.cible_id === match.objet.id);

		if (relExistante) {
			const ancienneQte = relExistante.proprietes?.quantite || 1;
			await supabase.from('kg_relations').update({
				proprietes: {
					...relExistante.proprietes,
					quantite: ancienneQte + quantite,
					dernier_cycle_utilise: cycle
				}
			}).eq('id', relExistante.id);
		} else {
			await supabase.rpc('kg_upsert_relation', {
				p_partie_id: partieId,
				p_source_id: protagoniste.id,
				p_cible_id: match.objet.id,
				p_type: 'possede',
				p_proprietes: {
					quantite,
					depuis_cycle: cycle,
					localisation: tx.localisation || 'sur_soi',
					origine: 'achat'
				},
				p_cycle: cycle,
				p_certitude: 'certain',
				p_verite: true,
				p_source_info: null
			});
		}

		if (match.ajouterAlias) {
			await ajouterAliasSiNouveau(supabase, match.objet.id, tx.objet);
		}
	} else {
		// Nouvel objet
		const { data: newObjet } = await supabase.rpc('kg_upsert_entite', {
			p_partie_id: partieId,
			p_type: 'objet',
			p_nom: tx.objet,
			p_alias: [],
			p_proprietes: {
				categorie: tx.categorie || null,
				valeur_neuve: tx.valeur_neuve || Math.abs(tx.montant || 0),
				prix_achat: Math.abs(tx.montant || 0),
				etat: tx.etat || 'neuf'
			},
			p_cycle: cycle,
			p_confirme: true
		});

		await supabase.rpc('kg_upsert_relation', {
			p_partie_id: partieId,
			p_source_id: protagoniste.id,
			p_cible_id: newObjet,
			p_type: 'possede',
			p_proprietes: {
				quantite,
				depuis_cycle: cycle,
				localisation: tx.localisation || 'sur_soi',
				origine: 'achat'
			},
			p_cycle: cycle,
			p_certitude: 'certain',
			p_verite: true,
			p_source_info: null
		});
	}

	cacheInvalidate(partieId, 'inventaire');
	cacheInvalidateType(partieId, 'objets');
	return { success: true };
}

/**
 * Gère un don à un PNJ
 */
async function gererDon(supabase, partieId, cycle, tx) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return { success: false, error: 'Protagoniste non trouvé' };

	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const objetId = match.objet.id;
	const relExistante = relationsPossede.find(r => r.cible_id === objetId);
	if (!relExistante) return { success: false, error: `Non possédé: ${tx.objet}` };

	const quantiteDonnee = tx.quantite || 1;
	const ancienneQte = relExistante.proprietes?.quantite || 1;

	// Retirer de l'inventaire de Valentin
	if (quantiteDonnee >= ancienneQte) {
		await supabase.from('kg_relations').update({
			cycle_fin: cycle,
			raison_fin: `donné à ${tx.pnj_name || 'inconnu'}`
		}).eq('id', relExistante.id);
	} else {
		await supabase.from('kg_relations').update({
			proprietes: { ...relExistante.proprietes, quantite: ancienneQte - quantiteDonnee }
		}).eq('id', relExistante.id);
	}

	// Ajouter à l'inventaire du PNJ
	if (tx.pnj_name) {
		const pnjId = await trouverEntite(supabase, partieId, tx.pnj_name, 'personnage');
		if (pnjId) {
			await supabase.rpc('kg_upsert_relation', {
				p_partie_id: partieId,
				p_source_id: pnjId,
				p_cible_id: objetId,
				p_type: 'possede',
				p_proprietes: { quantite: quantiteDonnee, depuis_cycle: cycle, origine: 'don_valentin' },
				p_cycle: cycle,
				p_certitude: 'certain',
				p_verite: true,
				p_source_info: null
			});
		}
	}

	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}

/**
 * Gère un cadeau reçu
 */
async function gererCadeauRecu(supabase, partieId, cycle, tx) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return { success: false, error: 'Protagoniste non trouvé' };

	// Créer l'objet
	const { data: objetId } = await supabase.rpc('kg_upsert_entite', {
		p_partie_id: partieId,
		p_type: 'objet',
		p_nom: tx.objet,
		p_alias: [],
		p_proprietes: {
			categorie: tx.categorie || null,
			valeur_neuve: tx.valeur_neuve || 0,
			prix_achat: 0,
			etat: tx.etat || 'bon',
			origine_cadeau: tx.pnj_name || null
		},
		p_cycle: cycle,
		p_confirme: true
	});

	// Créer la relation possède
	await supabase.rpc('kg_upsert_relation', {
		p_partie_id: partieId,
		p_source_id: protagoniste.id,
		p_cible_id: objetId,
		p_type: 'possede',
		p_proprietes: {
			quantite: tx.quantite || 1,
			depuis_cycle: cycle,
			localisation: tx.localisation || 'sur_soi',
			origine: `cadeau_de_${tx.pnj_name || 'inconnu'}`
		},
		p_cycle: cycle,
		p_certitude: 'certain',
		p_verite: true,
		p_source_info: null
	});

	cacheInvalidate(partieId, 'inventaire');
	cacheInvalidateType(partieId, 'objets');
	return { success: true };
}

/**
 * Gère un déplacement d'objet
 */
async function gererDeplacement(supabase, partieId, cycle, tx) {
	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const relExistante = relationsPossede.find(r => r.cible_id === match.objet.id);
	if (!relExistante) return { success: false, error: `Non possédé: ${tx.objet}` };

	await supabase.from('kg_relations').update({
		proprietes: {
			...relExistante.proprietes,
			localisation: tx.localisation_vers || tx.localisation,
			dernier_cycle_utilise: cycle
		}
	}).eq('id', relExistante.id);

	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}

/**
 * Gère une perte/oubli/vol
 */
async function gererPerte(supabase, partieId, cycle, tx) {
	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const relExistante = relationsPossede.find(r => r.cible_id === match.objet.id);
	if (!relExistante) return { success: false, error: `Non possédé: ${tx.objet}` };

	const quantitePerdue = tx.quantite || 1;
	const ancienneQte = relExistante.proprietes?.quantite || 1;

	if (quantitePerdue >= ancienneQte) {
		await supabase.from('kg_relations').update({
			cycle_fin: cycle,
			raison_fin: tx.type
		}).eq('id', relExistante.id);
	} else {
		await supabase.from('kg_relations').update({
			proprietes: { ...relExistante.proprietes, quantite: ancienneQte - quantitePerdue }
		}).eq('id', relExistante.id);
	}

	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}

/**
 * Gère un changement d'état (dégradation/réparation)
 */
async function gererChangementEtat(supabase, partieId, cycle, tx) {
	const objets = await getEntitesParType(supabase, partieId, 'objet');
	const relationsPossede = await getRelationsPossede(supabase, partieId);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const nouvelEtat = tx.nouvel_etat || (tx.type === 'reparation' ? 'bon' : 'endommage');

	await supabase.from('kg_entites').update({
		proprietes: { ...match.objet.proprietes, etat: nouvelEtat },
		updated_at: new Date().toISOString()
	}).eq('id', match.objet.id);

	cacheInvalidateType(partieId, 'objets');
	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}

async function gererVente(supabase, partieId, cycle, tx) {
	// Réutilise la logique de perte
	return gererPerte(supabase, partieId, cycle, { ...tx, type: 'vente' });
}

async function gererDestruction(supabase, partieId, cycle, tx) {
	return gererPerte(supabase, partieId, cycle, { ...tx, type: 'destruction' });
}

async function gererPret(supabase, partieId, cycle, tx) {
	// Marquer comme prêté mais pas supprimé
	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const relExistante = relationsPossede.find(r => r.cible_id === match.objet.id);
	if (!relExistante) return { success: false, error: `Non possédé: ${tx.objet}` };

	await supabase.from('kg_relations').update({
		proprietes: {
			...relExistante.proprietes,
			localisation: 'prete',
			prete_a: tx.pnj_name,
			prete_depuis_cycle: cycle
		}
	}).eq('id', relExistante.id);

	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}

async function gererEmprunt(supabase, partieId, cycle, tx) {
	// Similaire à cadeau_recu mais avec flag "emprunté"
	return gererCadeauRecu(supabase, partieId, cycle, {
		...tx,
		localisation: 'sur_soi'
	});
}

async function gererRetourPret(supabase, partieId, cycle, tx) {
	// Récupérer un objet prêté
	const [objets, relationsPossede] = await Promise.all([
		getEntitesParType(supabase, partieId, 'objet'),
		getRelationsPossede(supabase, partieId)
	]);

	const match = fuzzyFindObjet(tx.objet, objets, relationsPossede, 70);
	if (!match) return { success: false, error: `Objet non trouvé: ${tx.objet}` };

	const relExistante = relationsPossede.find(r => r.cible_id === match.objet.id);
	if (!relExistante) return { success: false, error: `Non possédé: ${tx.objet}` };

	await supabase.from('kg_relations').update({
		proprietes: {
			...relExistante.proprietes,
			localisation: 'sur_soi',
			prete_a: null,
			prete_depuis_cycle: null
		}
	}).eq('id', relExistante.id);

	cacheInvalidate(partieId, 'inventaire');
	return { success: true };
}
