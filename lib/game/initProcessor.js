/**
 * Traitement du mode INIT (World Builder)
 * 
 * Crée le monde, les entités, les relations et l'événement d'arrivée.
 * Ne génère PAS de narratif — c'est le rôle du premier appel LIGHT.
 */

import {
	ROMANCE,
	COMPETENCES_VALENTIN,
	STATS_VALENTIN_DEFAUT
} from '../constants.js';
import {
	trouverEntite,
	getProtagoniste
} from '../kg/kgService.js';
import { appliquerOperations } from '../kg/kgOperations.js';

import {
	determinerSituation,
	genererOperationsInventaire,
	SITUATIONS_DEPART
} from './initialInventory.js';

// ============================================================================
// TRAITEMENT PRINCIPAL
// ============================================================================

/**
 * Traite une réponse init et crée le Knowledge Graph initial
 * @returns {object} Résultat avec monde_cree: true et données pour le client
 */
export async function processInitMode(supabase, partieId, parsed, cycle = 1) {
	console.log('[INIT] Création du Knowledge Graph initial (World Builder)');

	const operations = [];

	// 1. Protagoniste (Valentin)
	operations.push(buildValentinOperation(parsed));

	// 2. IA personnelle
	if (parsed.ia?.nom) {
		operations.push(...buildIAOperations(parsed.ia.nom));
	}

	// 3. Monde (station/base)
	if (parsed.monde) {
		operations.push(buildMondeOperation(parsed.monde));
	}

	// 4. Employeur
	if (parsed.employeur) {
		operations.push(...buildEmployeurOperations(parsed));
	}

	// 5. Lieux initiaux
	for (const lieu of (parsed.lieux_initiaux || [])) {
		operations.push(...buildLieuOperations(lieu, parsed.monde?.nom));
	}

	// 6. PNJ initiaux
	for (const pnj of (parsed.pnj_initiaux || [])) {
		operations.push(...buildPnjOperations(pnj));
	}

	// 7. Arcs narratifs globaux
	for (const arc of (parsed.arcs_potentiels || [])) {
		operations.push(...buildArcOperations(arc));
	}

	console.log('[INIT] Operations:', JSON.stringify(operations, null, 2));

	// Appliquer toutes les opérations de base
	const resultats = await appliquerOperations(supabase, partieId, operations, cycle);
	console.log(`[INIT] ${resultats.entites_creees} entités, ${resultats.relations_creees} relations`);

	// ============================================================================
	// 8. INVENTAIRE INITIAL
	// ============================================================================

	const raisonDepart = parsed.valentin?.raison_depart || '';
	const situation = determinerSituation(raisonDepart);

	const creditsInitiaux = parsed.credits_initiaux
		|| parsed.valentin?.credits_initiaux
		|| SITUATIONS_DEPART[situation]?.credits
		|| STATS_VALENTIN_DEFAUT.credits;

	console.log(`[INIT] Situation: ${situation}, Crédits: ${creditsInitiaux}`);

	if (parsed.inventaire_initial?.length > 0) {
		const inventaireOps = [];

		for (const item of parsed.inventaire_initial) {
			inventaireOps.push({
				op: 'CREER_ENTITE',
				type: 'objet',
				nom: item.nom,
				proprietes: {
					categorie: item.categorie || 'equipement',
					valeur_neuve: item.valeur || 0,
					prix_achat: item.valeur || 0,
					etat: item.etat || 'bon',
					description: item.description || null
				}
			});

			inventaireOps.push({
				op: 'CREER_RELATION',
				source: 'Valentin',
				cible: item.nom,
				type: 'possede',
				proprietes: {
					quantite: item.quantite || 1,
					depuis_cycle: cycle,
					localisation: normaliserLocalisation(item.localisation),
					origine: 'initial'
				}
			});
		}

		const invResult = await appliquerOperations(supabase, partieId, inventaireOps, cycle);
		console.log(`[INIT] Inventaire Claude: ${invResult.entites_creees} objets`);

	} else {
		const { operations: invOps } = genererOperationsInventaire(situation, cycle);

		if (invOps.length > 0) {
			const invResult = await appliquerOperations(supabase, partieId, invOps, cycle);
			console.log(`[INIT] Inventaire défaut (${situation}): ${invResult.entites_creees} objets`);
		}
	}

	// ============================================================================
	// 9. ÉTATS INITIAUX
	// ============================================================================

	await initValentinStats(supabase, partieId, cycle, creditsInitiaux);
	await initPnjStats(supabase, partieId, parsed.pnj_initiaux || [], cycle);

	// ============================================================================
	// 10. ÉVÉNEMENT D'ARRIVÉE (pour le premier LIGHT)
	// ============================================================================

	let evenementArriveeId = null;
	const evt = parsed.evenement_arrivee;

	if (evt) {
		evenementArriveeId = await createEvenementArrivee(
			supabase,
			partieId,
			evt,
			parsed.monde?.nom,
			parsed.ia?.nom,
			evt.cycle || 1
		);
		console.log(`[INIT] Événement arrivée créé: ${evenementArriveeId}`);
	}

	// ============================================================================
	// 11. MISE À JOUR PARTIE
	// ============================================================================

	await supabase.from('parties').update({
		cycle_actuel: evt?.cycle || 1,
		jour: evt?.jour,
		date_jeu: evt?.date_jeu,
		heure: evt?.heure || '08h00',
		lieu_actuel: evt?.lieu_actuel,
		pnjs_presents: [] // Personne n'est présent avant le premier LIGHT
	}).eq('id', partieId);

	// ============================================================================
	// RETOUR (pas de narratif, juste les métadonnées)
	// ============================================================================

	return {
		monde_cree: true,
		...resultats,
		situation,
		credits: creditsInitiaux,
		evenement_arrivee_id: evenementArriveeId,
		// Données pour l'affichage client (optionnel)
		monde: {
			nom: parsed.monde?.nom,
			type: parsed.monde?.type,
			ambiance: parsed.monde?.ambiance
		},
		ia_nom: parsed.ia?.nom,
		lieu_depart: evt?.lieu_actuel
	};
}

// ============================================================================
// CRÉATION ÉVÉNEMENT D'ARRIVÉE
// ============================================================================

/**
 * Crée l'événement d'arrivée dans kg_evenements
 * Cet événement sera lu par le contextBuilder pour le premier LIGHT
 */
async function createEvenementArrivee(supabase, partieId, evt, mondeNom, iaNom, cycle) {
	// Trouver l'ID du lieu d'arrivée
	const lieuId = await trouverEntite(supabase, partieId, evt.lieu_actuel, 'lieu');

	// Construire la description enrichie pour le narrateur
	const description = buildDescriptionArrivee(evt, mondeNom, iaNom);

	const { data, error } = await supabase
		.from('kg_evenements')
		.insert({
			partie_id: partieId,
			type: 'arrivee',
			categorie: 'systeme',
			titre: evt.titre || `Arrivée sur ${mondeNom || 'la station'}`,
			description: description,
			cycle: cycle,
			heure: evt.heure,
			lieu_id: lieuId,
			realise: false,
			annule: false,
			certitude: 'certain',
			verite: true
		})
		.select('id')
		.single();

	if (error) {
		console.error('[INIT] Erreur création événement arrivée:', error);
		return null;
	}

	// Ajouter Valentin comme participant
	const protagonisteId = await trouverEntite(supabase, partieId, 'Valentin', 'protagoniste');
	if (protagonisteId && data?.id) {
		await supabase.from('kg_evenement_participants').insert({
			evenement_id: data.id,
			entite_id: protagonisteId,
			role: 'protagoniste'
		});
	}

	// Si premier_contact, l'ajouter comme participant potentiel
	if (evt.premier_contact) {
		const contactId = await trouverEntite(supabase, partieId, evt.premier_contact, 'personnage');
		if (contactId && data?.id) {
			await supabase.from('kg_evenement_participants').insert({
				evenement_id: data.id,
				entite_id: contactId,
				role: 'premier_contact'
			});
		}
	}

	return data?.id;
}

/**
 * Construit la description formatée pour le narrateur
 */
function buildDescriptionArrivee(evt, mondeNom, iaNom) {
	let desc = `=== INSTRUCTIONS PREMIER NARRATIF ===\n\n`;

	desc += `CONTEXTE: ${evt.contexte}\n\n`;
	desc += `TON: ${evt.ton || 'neutre'}\n\n`;

	desc += `ÉLÉMENTS SENSORIELS À INTÉGRER:\n`;
	for (const elem of (evt.elements_sensoriels || [])) {
		desc += `• ${elem}\n`;
	}
	desc += '\n';

	if (evt.premier_contact) {
		desc += `PREMIER CONTACT POSSIBLE: ${evt.premier_contact}\n`;
		desc += `(Tu peux l'introduire ou non selon ce qui est naturel)\n\n`;
	}

	if (iaNom) {
		desc += `IA PERSONNELLE: ${iaNom}\n`;
		desc += `(Doit intervenir avec un premier commentaire sarcastique)\n\n`;
	}

	desc += `RAPPELS:\n`;
	desc += `• C'est la PREMIÈRE impression du joueur — sois immersif\n`;
	desc += `• Établis l'ambiance spatiale (sons, odeurs, sensations)\n`;
	desc += `• Les choix doivent être concrets et immédiats\n`;
	desc += `• Narration 2e personne, ton Becky Chambers\n`;

	return desc;
}

// ============================================================================
// HELPERS
// ============================================================================

function normaliserLocalisation(loc) {
	if (!loc) return 'sur_soi';

	const locLower = loc.toLowerCase();

	const mappings = {
		'sur soi': 'sur_soi',
		'poche': 'sur_soi',
		'poches': 'sur_soi',
		'sac': 'sac_a_dos',
		'sac à dos': 'sac_a_dos',
		'sac a dos': 'sac_a_dos',
		'valise': 'valise',
		'appartement': 'appartement',
		'chez soi': 'appartement',
		'bureau': 'bureau',
		'travail': 'bureau'
	};

	return mappings[locLower] || loc;
}

// ============================================================================
// BUILDERS D'OPÉRATIONS
// ============================================================================

function buildValentinOperation(parsed) {
	return {
		op: 'CREER_ENTITE',
		type: 'protagoniste',
		nom: 'Valentin',
		alias: ['Valentin Nyzam'],
		proprietes: {
			physique: '1m78, brun dégarni, barbe, implants rétiniens',
			traits: ['introverti', 'maladroit en amour', 'curieux', 'romantique malgré lui'],
			raison_depart: parsed.valentin?.raison_depart || null,
			poste: parsed.valentin?.poste || null,
			hobbies: parsed.valentin?.hobbies || ['cuisine'],
			competences: COMPETENCES_VALENTIN
		}
	};
}

function buildIAOperations(iaNom) {
	return [
		{
			op: 'CREER_ENTITE',
			type: 'ia',
			nom: iaNom,
			proprietes: {
				traits: ['sarcastique', 'pragmatique'],
				voix: 'grave, sensuelle'
			}
		},
		{
			op: 'CREER_RELATION',
			source: iaNom,
			cible: 'Valentin',
			type: 'assiste'
		}
	];
}

function buildMondeOperation(monde) {
	return {
		op: 'CREER_ENTITE',
		type: 'lieu',
		nom: monde.nom,
		proprietes: {
			niveau: 'zone',
			type_lieu: monde.type,
			ambiance: monde.ambiance,
			population: monde.population,
			orbite: monde.orbite
		}
	};
}

function buildEmployeurOperations(parsed) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'organisation',
			nom: parsed.employeur.nom,
			proprietes: {
				type_org: 'entreprise',
				domaine: parsed.employeur.type
			}
		},
		{
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: parsed.employeur.nom,
			type: 'employe_de',
			proprietes: { poste: parsed.valentin?.poste }
		}
	];

	if (parsed.monde?.nom) {
		ops.push({
			op: 'CREER_RELATION',
			source: parsed.employeur.nom,
			cible: parsed.monde.nom,
			type: 'siege_de'
		});
	}

	return ops;
}

function buildLieuOperations(lieu, mondeNom) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'lieu',
			nom: lieu.nom,
			proprietes: {
				niveau: 'lieu',
				type_lieu: lieu.type,
				ambiance: lieu.description,
				horaires: lieu.horaires
			}
		}
	];

	const parent = lieu.secteur || mondeNom;
	if (parent) {
		ops.push({
			op: 'CREER_RELATION',
			source: lieu.nom,
			cible: parent,
			type: 'situe_dans'
		});
	}

	for (const freq of (lieu.pnjs_frequents || [])) {
		ops.push({
			op: 'CREER_RELATION',
			source: freq.pnj,
			cible: lieu.nom,
			type: 'frequente',
			proprietes: {
				regularite: freq.regularite || 'parfois',
				periode: freq.periode || 'aléatoire'
			}
		});
	}

	return ops;
}

function buildPnjOperations(pnj) {
	const sexe = (pnj.sexe || '').toUpperCase();
	const age = pnj.age || 0;
	const interetRomantique = (
		sexe === 'F' &&
		age >= ROMANCE.AGE_MIN &&
		age <= ROMANCE.AGE_MAX
	);

	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'personnage',
			nom: pnj.nom,
			alias: [pnj.nom.split(' ')[0]],
			proprietes: {
				sexe,
				age,
				espece: pnj.espece || 'humain',
				metier: pnj.metier,
				physique: pnj.physique,
				traits: pnj.traits || [],
				interet_romantique: interetRomantique
			}
		},
		{
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: pnj.nom,
			type: 'connait',
			proprietes: {
				niveau: 0,
				...(interetRomantique && { etape_romantique: 0 })
			}
		}
	];

	if (pnj.domicile) {
		ops.push({
			op: 'CREER_RELATION',
			source: pnj.nom,
			cible: pnj.domicile,
			type: 'habite'
		});
	}

	// Arcs personnels du PNJ
	for (const arcTitre of (pnj.arcs || [])) {
		ops.push(
			{
				op: 'CREER_ENTITE',
				type: 'arc_narratif',
				nom: arcTitre,
				proprietes: {
					type_arc: 'pnj_personnel',
					description: `Arc personnel de ${pnj.nom}`,
					progression: 0,
					etat: 'actif'
				}
			},
			{
				op: 'CREER_RELATION',
				source: pnj.nom,
				cible: arcTitre,
				type: 'implique_dans',
				proprietes: { role: 'protagoniste' }
			}
		);
	}

	return ops;
}

function buildArcOperations(arc) {
	const ops = [
		{
			op: 'CREER_ENTITE',
			type: 'arc_narratif',
			nom: arc.nom,
			proprietes: {
				type_arc: arc.type,
				description: arc.description,
				obstacles: arc.obstacles || [],
				progression: 0,
				etat: 'actif'
			}
		}
	];

	for (const pnjNom of (arc.pnjs_impliques || [])) {
		ops.push({
			op: 'CREER_RELATION',
			source: pnjNom,
			cible: arc.nom,
			type: 'implique_dans'
		});
	}

	return ops;
}

// ============================================================================
// INITIALISATION DES ÉTATS
// ============================================================================

async function initValentinStats(supabase, partieId, cycle, creditsInitiaux) {
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (!protagoniste) return;

	const statsInitiales = [
		['energie', STATS_VALENTIN_DEFAUT.energie],
		['moral', STATS_VALENTIN_DEFAUT.moral],
		['sante', STATS_VALENTIN_DEFAUT.sante],
		['credits', creditsInitiaux]
	];

	await Promise.all(
		statsInitiales.map(([attr, val]) =>
			supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: protagoniste.id,
				p_attribut: attr,
				p_valeur: val,
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			})
		)
	);
}

async function initPnjStats(supabase, partieId, pnjList, cycle) {
	await Promise.all(
		pnjList.map(async (pnj) => {
			const pnjId = await trouverEntite(supabase, partieId, pnj.nom, 'personnage');
			if (!pnjId) return;

			return supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: pnjId,
				p_attribut: 'disposition',
				p_valeur: 'neutre',
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			});
		})
	);
}
