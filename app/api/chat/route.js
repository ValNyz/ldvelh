import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_NEWCYCLE, SYSTEM_PROMPT_LIGHT } from '../../../lib/prompt';
import { buildContextForClaude } from '../../../lib/contextBuilder';
import { extractPnjFromNarratif, updatePnjContact } from '../../../lib/interactionTracker';
import { extraireFaits, sauvegarderFaits } from '../../../lib/faitsService';
import { insererTransactions, calculerSolde, calculerInventaire } from '../../../lib/financeService';

export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
	process.env.NEXT_PUBLIC_SUPABASE_URL,
	process.env.SUPABASE_SERVICE_KEY
);

// ============================================================================
// FONCTIONS DE RÉPARATION JSON
// ============================================================================

function tryFixJSON(jsonStr) {
	if (!jsonStr || typeof jsonStr !== 'string') return null;
	let fixed = jsonStr.trim();
	if (fixed.startsWith('```json')) fixed = fixed.slice(7);
	if (fixed.startsWith('```')) fixed = fixed.slice(3);
	if (fixed.endsWith('```')) fixed = fixed.slice(0, -3);
	fixed = fixed.trim();
	const firstBrace = fixed.indexOf('{');
	if (firstBrace > 0) fixed = fixed.slice(firstBrace);
	else if (firstBrace === -1) return null;
	try { return JSON.parse(fixed); } catch (e) { }
	let lastValidIndex = -1, braceCount = 0, inString = false, escapeNext = false;
	for (let i = 0; i < fixed.length; i++) {
		const char = fixed[i];
		if (escapeNext) { escapeNext = false; continue; }
		if (char === '\\' && inString) { escapeNext = true; continue; }
		if (char === '"' && !escapeNext) { inString = !inString; continue; }
		if (!inString) {
			if (char === '{') braceCount++;
			if (char === '}') { braceCount--; if (braceCount === 0) lastValidIndex = i; }
		}
	}
	if (lastValidIndex > 0) {
		try { return JSON.parse(fixed.slice(0, lastValidIndex + 1)); } catch (e) { }
	}
	let openBraces = 0, openBrackets = 0;
	inString = false; escapeNext = false;
	for (let i = 0; i < fixed.length; i++) {
		const char = fixed[i];
		if (escapeNext) { escapeNext = false; continue; }
		if (char === '\\' && inString) { escapeNext = true; continue; }
		if (char === '"') { inString = !inString; continue; }
		if (!inString) {
			if (char === '{') openBraces++;
			if (char === '}') openBraces--;
			if (char === '[') openBrackets++;
			if (char === ']') openBrackets--;
		}
	}
	if (inString) fixed += '"';
	while (openBrackets > 0) { fixed += ']'; openBrackets--; }
	while (openBraces > 0) { fixed += '}'; openBraces--; }
	try { return JSON.parse(fixed); } catch (e) { }
	fixed = fixed.replace(/,(\s*[}\]])/g, '$1').replace(/:\s*([}\]])/g, ': null$1').replace(/:\s*,/g, ': null,');
	try { return JSON.parse(fixed); } catch (e) { return null; }
}

function extractJSON(content) {
	if (!content) return null;
	if (content.trim().startsWith('{')) {
		const result = tryFixJSON(content);
		if (result) return result;
	}
	const lastBraceIndex = content.lastIndexOf('\n{');
	if (lastBraceIndex > 0) {
		const result = tryFixJSON(content.slice(lastBraceIndex + 1));
		if (result) return result;
	}
	const firstBraceIndex = content.indexOf('{');
	if (firstBraceIndex >= 0) {
		const result = tryFixJSON(content.slice(firstBraceIndex));
		if (result) return result;
	}
	return null;
}

// ============================================================================
// CHARGEMENT DES DONNÉES
// ============================================================================

async function loadGameState(partieId) {
	const [partie, valentin, ia, pnj, arcs, lieux, aVenir] = await Promise.all([
		supabase.from('parties').select('*').eq('id', partieId).single(),
		supabase.from('valentin').select('*').eq('partie_id', partieId).single(),
		supabase.from('ia_personnelle').select('*').eq('partie_id', partieId).single(),
		supabase.from('pnj').select('*').eq('partie_id', partieId),
		supabase.from('arcs').select('*').eq('partie_id', partieId),
		supabase.from('lieux').select('*').eq('partie_id', partieId),
		supabase.from('a_venir').select('*').eq('partie_id', partieId).eq('realise', false)
	]);

	return {
		partie: partie.data,
		valentin: valentin.data,
		ia: ia.data,
		pnj: pnj.data || [],
		arcs: arcs.data || [],
		lieux: lieux.data || [],
		aVenir: aVenir.data || []
	};
}

async function loadChatMessages(partieId) {
	const { data } = await supabase.from('chat_messages').select('role, content, cycle, created_at')
		.eq('partie_id', partieId).order('created_at', { ascending: true });
	return data || [];
}

// ============================================================================
// TRAITEMENT MODE INIT
// ============================================================================

async function processInitMode(supabase, partieId, init, heure) {
	const updates = [];

	// 1. Mise à jour partie
	updates.push(
		supabase.from('parties').update({
			cycle_actuel: init.cycle || 1,
			jour: init.jour || 'Lundi',
			date_jeu: init.date_jeu,
			heure: heure,
			lieu_actuel: init.lieu_actuel || null,
			pending_full_state: false
		}).eq('id', partieId)
	);

	// 2. Mise à jour Valentin
	if (init.valentin) {
		const valentinUpdate = {};
		if (init.valentin.raison_depart) valentinUpdate.raison_depart = init.valentin.raison_depart;
		if (init.valentin.poste) valentinUpdate.poste = init.valentin.poste;
		if (init.valentin.hobbies_supplementaires?.length > 0) {
			const { data: current } = await supabase.from('valentin').select('hobbies').eq('partie_id', partieId).single();
			const existingHobbies = current?.hobbies || ['Cuisine'];
			valentinUpdate.hobbies = [...existingHobbies, ...init.valentin.hobbies_supplementaires];
		}
		if (Object.keys(valentinUpdate).length > 0) {
			updates.push(supabase.from('valentin').update(valentinUpdate).eq('partie_id', partieId));
		}
	}

	// 3. Mise à jour IA
	if (init.ia?.nom) {
		updates.push(supabase.from('ia_personnelle').update({ nom: init.ia.nom }).eq('partie_id', partieId));
	}

	// 4. PNJ initiaux
	if (init.pnj_initiaux?.length > 0) {
		for (const pnj of init.pnj_initiaux) {
			const { data: existing } = await supabase
				.from('pnj')
				.select('id')
				.eq('partie_id', partieId)
				.ilike('nom', pnj.nom)
				.single();

			if (existing) {
				updates.push(
					supabase.from('pnj').update({
						metier: pnj.metier,
						traits: pnj.traits || [],
						arc: pnj.arc,
						domicile: pnj.domicile,
						est_initial: true
					}).eq('id', existing.id)
				);
			} else {
				updates.push(
					supabase.from('pnj').insert({
						partie_id: partieId,
						nom: pnj.nom,
						metier: pnj.metier,
						physique: pnj.physique || null,
						traits: pnj.traits || [],
						arc: pnj.arc,
						domicile: pnj.domicile,
						relation: 0,
						disposition: 'neutre',
						stat_social: 3,
						stat_travail: 3,
						stat_sante: 3,
						est_initial: true,
						dernier_contact: 1
					})
				);
			}
		}
	}

	// 5. Lieux initiaux
	if (init.lieux_initiaux?.length > 0) {
		const lieuxToInsert = init.lieux_initiaux.map(l => ({
			partie_id: partieId,
			nom: l.nom,
			type: l.type,
			description: l.description
		}));
		updates.push(supabase.from('lieux').insert(lieuxToInsert));
	}

	// 6. Arcs potentiels
	if (init.arcs_potentiels?.length > 0) {
		const arcsToInsert = init.arcs_potentiels.map(a => ({
			partie_id: partieId,
			nom: a.nom,
			type: a.type,
			progression: 0,
			etat: 'actif'
		}));
		updates.push(supabase.from('arcs').insert(arcsToInsert));
	}

	// 7. Monde (stocker comme faits)
	if (init.monde) {
		const faitsMonde = [
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: init.monde.lieu_nom, categorie: 'etat', fait: `Type: ${init.monde.lieu_type}`, importance: 5, cycle_creation: 1, source: 'narrateur', valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: init.monde.lieu_nom, categorie: 'etat', fait: `Position: ${init.monde.lieu_orbite}`, importance: 4, cycle_creation: 1, source: 'narrateur', valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: init.monde.lieu_nom, categorie: 'etat', fait: `Population: ${init.monde.lieu_population}`, importance: 3, cycle_creation: 1, source: 'narrateur', valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: init.monde.lieu_nom, categorie: 'trait', fait: `Ambiance: ${init.monde.lieu_ambiance}`, importance: 4, cycle_creation: 1, source: 'narrateur', valentin_sait: true, certitude: 'certain' }
		];
		updates.push(supabase.from('faits').insert(faitsMonde));
	}

	// 8. Employeur
	if (init.employeur) {
		updates.push(
			supabase.from('faits').insert({
				partie_id: partieId,
				sujet_type: 'monde',
				sujet_nom: init.employeur.nom,
				categorie: 'etat',
				fait: `Employeur de Valentin. Type: ${init.employeur.type}`,
				importance: 5,
				cycle_creation: 1,
				source: 'narrateur',
				valentin_sait: true,
				certitude: 'certain'
			})
		);
	}

	await Promise.all(updates);
}

// ============================================================================
// TRAITEMENT MODE NEWCYCLE
// ============================================================================

async function processNewCycleMode(supabase, partieId, parsed, pnjList) {
	const updates = [];
	const cycle = parsed.nouveau_jour?.cycle || 1;

	// 1. Nouveau jour
	if (parsed.nouveau_jour) {
		updates.push(
			supabase.from('parties').update({
				cycle_actuel: parsed.nouveau_jour.cycle,
				jour: parsed.nouveau_jour.jour,
				date_jeu: parsed.nouveau_jour.date_jeu,
				heure: parsed.heure,
				lieu_actuel: parsed.lieu_actuel || null,
				pending_full_state: false
			}).eq('id', partieId)
		);
	} else {
		updates.push(
			supabase.from('parties').update({
				lieu_actuel: parsed.lieu_actuel || null,
				pending_full_state: false
			}).eq('id', partieId)
		);
	}

	// 2. Réveil Valentin (valeurs absolues)
	if (parsed.reveil_valentin) {
		const rv = parsed.reveil_valentin;
		const valentinUpdate = { updated_at: new Date().toISOString() };

		if (rv.energie !== undefined) valentinUpdate.energie = rv.energie;
		if (rv.moral !== undefined) valentinUpdate.moral = rv.moral;
		if (rv.sante !== undefined) valentinUpdate.sante = rv.sante;

		updates.push(
			supabase.from('valentin').update(valentinUpdate).eq('partie_id', partieId)
		);

		if (rv.evenement_nuit) {
			updates.push(
				supabase.from('faits').insert({
					partie_id: partieId,
					sujet_type: 'valentin',
					sujet_nom: 'Valentin',
					categorie: 'evenement',
					fait: rv.evenement_nuit,
					importance: 2,
					cycle_creation: cycle,
					source: 'narrateur',
					valentin_sait: true,
					certitude: 'certain'
				})
			);
		}
	}

	// 3. Évolutions PNJ
	if (parsed.evolutions_pnj?.length > 0) {
		for (const ev of parsed.evolutions_pnj) {
			const pnj = pnjList.find(p => p.nom.toLowerCase() === ev.nom.toLowerCase());
			if (pnj?.id) {
				const pnjUpdate = { updated_at: new Date().toISOString() };
				if (ev.stat_social !== undefined) pnjUpdate.stat_social = ev.stat_social;
				if (ev.stat_travail !== undefined) pnjUpdate.stat_travail = ev.stat_travail;
				if (ev.stat_sante !== undefined) pnjUpdate.stat_sante = ev.stat_sante;
				if (ev.disposition) pnjUpdate.disposition = ev.disposition;

				updates.push(supabase.from('pnj').update(pnjUpdate).eq('id', pnj.id));

				if (ev.evenement_horschamp) {
					updates.push(
						supabase.from('faits').insert({
							partie_id: partieId,
							sujet_type: 'pnj',
							sujet_id: pnj.id,
							sujet_nom: ev.nom,
							categorie: 'evenement',
							fait: ev.evenement_horschamp,
							importance: 3,
							cycle_creation: cycle,
							source: 'narrateur',
							valentin_sait: false,
							certitude: 'certain'
						})
					);
				}
			}
		}
	}

	// 4. Progression arcs
	if (parsed.progression_arcs?.length > 0) {
		for (const prog of parsed.progression_arcs) {
			const { data: arc } = await supabase
				.from('arcs')
				.select('id')
				.eq('partie_id', partieId)
				.ilike('nom', `%${prog.nom}%`)
				.single();

			if (arc?.id) {
				updates.push(
					supabase.from('arcs').update({ progression: prog.progression }).eq('id', arc.id)
				);
			}
		}
	}

	// 5. Nouveaux lieux
	if (parsed.nouveaux_lieux?.length > 0) {
		const lieuxToInsert = parsed.nouveaux_lieux.map(l => ({
			partie_id: partieId,
			nom: l.nom,
			type: l.type,
			description: l.description
		}));
		updates.push(supabase.from('lieux').insert(lieuxToInsert));
	}

	// 6. Événements à venir
	if (parsed.evenements_a_venir?.length > 0) {
		const evToInsert = parsed.evenements_a_venir.map(ev => ({
			partie_id: partieId,
			cycle_prevu: ev.cycle_prevu,
			evenement: ev.evenement,
			pnj_impliques: ev.pnj_impliques || [],
			realise: false
		}));
		updates.push(supabase.from('a_venir').insert(evToInsert));
	}

	await Promise.all(updates);
}

// ============================================================================
// APPLICATION DES DELTAS (mode light)
// ============================================================================

async function applyDeltas(supabase, partieId, parsed, pnjList, cycle, heure) {
	const results = {
		valentin: null,
		relations: 0,
		pnj: 0,
		transactions: 0,
		competence: null,
		lieu: null
	};

	// 1. Deltas Valentin
	if (parsed.deltas_valentin) {
		const { data: current } = await supabase
			.from('valentin')
			.select('energie, moral, sante')
			.eq('partie_id', partieId)
			.single();

		if (current) {
			const d = parsed.deltas_valentin;
			const newValues = {
				energie: Math.max(1, Math.min(5, (current.energie || 3) + (d.energie || 0))),
				moral: Math.max(1, Math.min(5, (current.moral || 3) + (d.moral || 0))),
				sante: Math.max(1, Math.min(5, (current.sante || 5) + (d.sante || 0))),
				updated_at: new Date().toISOString()
			};

			await supabase.from('valentin').update(newValues).eq('partie_id', partieId);

			results.valentin = {
				energie: newValues.energie,
				moral: newValues.moral,
				sante: newValues.sante
			};
		}
	}

	// 2. Changements de relation + disposition
	if (parsed.changements_relation?.length > 0) {
		for (const change of parsed.changements_relation) {
			if (!change.pnj) continue;

			const pnj = pnjList.find(p =>
				p.nom && (
					p.nom.toLowerCase() === change.pnj.toLowerCase() ||
					p.nom.split(' ')[0].toLowerCase() === change.pnj.toLowerCase()
				)
			);

			if (pnj?.id) {
				const currentRelation = pnj.relation || 0;
				const newRelation = Math.max(0, Math.min(10, currentRelation + (change.delta || 0)));

				const updateData = {
					relation: newRelation,
					updated_at: new Date().toISOString()
				};

				if (change.disposition) {
					updateData.disposition = change.disposition;
				}

				await supabase.from('pnj').update(updateData).eq('id', pnj.id);
				results.relations++;
			}
		}
	}

	// 3. Nouveaux PNJ
	if (parsed.nouveaux_pnj?.length > 0) {
		const toInsert = parsed.nouveaux_pnj.map(p => ({
			partie_id: partieId,
			nom: p.nom,
			metier: p.metier || null,
			physique: p.physique || null,
			traits: p.traits || [],
			relation: 0,
			disposition: 'neutre',
			stat_social: 3,
			stat_travail: 3,
			stat_sante: 3,
			dernier_contact: cycle
		}));

		await supabase.from('pnj').insert(toInsert);
		results.pnj = toInsert.length;
	}

	// 4. Transactions
	if (parsed.transactions?.length > 0) {
		const txResult = await insererTransactions(supabase, partieId, cycle, heure, parsed.transactions);
		results.transactions = txResult.inserted;
	}

	// 5. Progression compétence
	if (parsed.progression_competence?.competence) {
		results.competence = parsed.progression_competence.competence;
	}

	// 6. Nouveau lieu (si découvert)
	if (parsed.nouveau_lieu?.nom) {
		const { data: lieuExistant } = await supabase
			.from('lieux')
			.select('id')
			.eq('partie_id', partieId)
			.ilike('nom', parsed.nouveau_lieu.nom)
			.maybeSingle();

		if (!lieuExistant) {
			await supabase.from('lieux').insert({
				partie_id: partieId,
				nom: parsed.nouveau_lieu.nom,
				type: parsed.nouveau_lieu.type || 'autre',
				secteur: parsed.nouveau_lieu.secteur || null,
				description: parsed.nouveau_lieu.description || null,
				pnj_frequents: parsed.nouveau_lieu.pnj_frequents || [],
				cycles_visites: [cycle]
			});
			results.lieu = parsed.nouveau_lieu.nom;
		}
	}

	// 7. Mise à jour lieu actuel + tracking visite
	if (parsed.lieu_actuel) {
		// Mettre à jour parties
		await supabase.from('parties').update({
			lieu_actuel: parsed.lieu_actuel,
			heure: heure
		}).eq('id', partieId);

		// Tracker la visite (si lieu existe et pas nouveau)
		if (!parsed.nouveau_lieu || parsed.nouveau_lieu.nom !== parsed.lieu_actuel) {
			const { data: lieu } = await supabase
				.from('lieux')
				.select('id, cycles_visites')
				.eq('partie_id', partieId)
				.ilike('nom', parsed.lieu_actuel)
				.maybeSingle();

			if (lieu) {
				const cyclesVisites = lieu.cycles_visites || [];
				if (!cyclesVisites.includes(cycle)) {
					await supabase.from('lieux').update({
						cycles_visites: [...cyclesVisites, cycle]
					}).eq('id', lieu.id);
				}
			}
		}
	}

	// 8. Nouveau cycle flag
	if (parsed.nouveau_cycle === true) {
		await supabase.from('parties').update({
			pending_full_state: true
		}).eq('id', partieId);
	}

	return results;
}

// ============================================================================
// GESTION PARTIES
// ============================================================================

async function deleteGame(partieId) {
	await Promise.all([
		supabase.from('chat_messages').delete().eq('partie_id', partieId),
		supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
		supabase.from('faits').delete().eq('partie_id', partieId),
		supabase.from('finances').delete().eq('partie_id', partieId),
		supabase.from('lieux').delete().eq('partie_id', partieId),
		supabase.from('a_venir').delete().eq('partie_id', partieId),
		supabase.from('arcs').delete().eq('partie_id', partieId),
		supabase.from('pnj').delete().eq('partie_id', partieId),
		supabase.from('ia_personnelle').delete().eq('partie_id', partieId),
		supabase.from('valentin').delete().eq('partie_id', partieId)
	]);
	await supabase.from('parties').delete().eq('id', partieId);
}

async function createNewGame() {
	const { data: partie, error } = await supabase
		.from('parties')
		.insert({
			nom: 'Nouvelle partie',
			cycle_actuel: 1,
			active: true,
			pending_full_state: false,
			options: { faits_enabled: true }
		})
		.select()
		.single();
	if (error) throw error;

	await Promise.all([
		supabase.from('valentin').insert({ partie_id: partie.id }),
		supabase.from('ia_personnelle').insert({ partie_id: partie.id }),
		supabase.from('pnj').insert({
			partie_id: partie.id,
			nom: 'Justine Lépicier',
			age: 32,
			physique: '1m54, 72kg, courbes prononcées, poitrine volumineuse, blonde en désordre, yeux bleus fatigués, cernes',
			relation: 0,
			disposition: 'neutre',
			stat_social: 4,
			stat_travail: 2,
			stat_sante: 2,
			etape_romantique: 0,
			est_initial: true
		})
	]);

	return partie.id;
}

// ============================================================================
// GET HANDLER
// ============================================================================

export async function GET(request) {
	const { searchParams } = new URL(request.url);
	const action = searchParams.get('action');
	const partieId = searchParams.get('partieId');

	if (action === 'load' && partieId) {
		const state = await loadGameState(partieId);
		const messages = await loadChatMessages(partieId);
		return Response.json({ state, messages });
	}
	if (action === 'list') {
		const { data } = await supabase.from('parties')
			.select('id, nom, cycle_actuel, updated_at, created_at, options, pending_full_state')
			.eq('active', true).order('updated_at', { ascending: false });
		return Response.json({ parties: data });
	}
	if (action === 'new') {
		try {
			const partieId = await createNewGame();
			return Response.json({ partieId });
		} catch (e) { return Response.json({ error: e.message }, { status: 500 }); }
	}
	if (action === 'delete' && partieId) {
		await deleteGame(partieId);
		return Response.json({ success: true });
	}
	if (action === 'rename' && partieId) {
		const newName = searchParams.get('name');
		if (newName) {
			await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
			return Response.json({ success: true });
		}
		return Response.json({ error: 'Nom manquant' }, { status: 400 });
	}
	if (action === 'toggle-faits' && partieId) {
		const enabled = searchParams.get('enabled') === 'true';
		const { data: current } = await supabase.from('parties').select('options').eq('id', partieId).single();
		const newOptions = { ...(current?.options || {}), faits_enabled: enabled };
		await supabase.from('parties').update({ options: newOptions }).eq('id', partieId);
		return Response.json({ success: true, faits_enabled: enabled });
	}
	return Response.json({ error: 'Action non reconnue' });
}

// ============================================================================
// DELETE HANDLER
// ============================================================================

export async function DELETE(request) {
	try {
		const { partieId, fromIndex } = await request.json();
		if (!partieId) return Response.json({ error: 'partieId manquant' }, { status: 400 });
		const { data: allMessages } = await supabase.from('chat_messages')
			.select('id, created_at').eq('partie_id', partieId).order('created_at', { ascending: true });
		if (!allMessages || fromIndex >= allMessages.length) return Response.json({ success: true });
		const messagesToDelete = allMessages.slice(fromIndex).map(m => m.id);
		if (messagesToDelete.length > 0) {
			await supabase.from('chat_messages').delete().in('id', messagesToDelete);
		}
		return Response.json({ success: true, deleted: messagesToDelete.length });
	} catch (e) { return Response.json({ error: e.message }, { status: 500 }); }
}

// ============================================================================
// POST HANDLER
// ============================================================================

export async function POST(request) {
	try {
		const { message, partieId, gameState } = await request.json();
		const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

		// Déterminer le mode (INIT, NEWCYCLE ou LIGHT)
		let promptMode = 'light';
		let faitsEnabled = true;

		if (!gameState || !gameState.partie) {
			promptMode = 'init';
			console.log('[MODE] INIT - Lancement de partie');
		} else if (partieId) {
			const { data: partieData } = await supabase
				.from('parties')
				.select('pending_full_state, options')
				.eq('id', partieId)
				.single();

			faitsEnabled = partieData?.options?.faits_enabled !== false;

			if (partieData?.pending_full_state) {
				promptMode = 'newcycle';
				console.log('[MODE] NEWCYCLE - Nouveau cycle');
			} else {
				console.log('[MODE] LIGHT - Message normal');
			}
		}

		// Construire le contexte
		let contextMessage, knownPnj = [];
		if (partieId && gameState?.partie) {
			try {
				const contextResult = await buildContextForClaude(supabase, partieId, gameState, message, null, { faitsEnabled });
				contextMessage = contextResult.context;
				knownPnj = contextResult.pnj || [];
			} catch (err) {
				console.error('Erreur buildContextForClaude:', err);
				contextMessage = `=== ÉTAT ===\n${JSON.stringify(gameState, null, 1)}\n\n=== ACTION ===\n${message}`;
			}
		} else {
			contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
		}

		// Sélectionner le prompt selon le mode
		let systemPrompt, maxTokens;
		switch (promptMode) {
			case 'init':
				systemPrompt = SYSTEM_PROMPT_INIT;
				maxTokens = 8192;
				break;
			case 'newcycle':
				systemPrompt = SYSTEM_PROMPT_NEWCYCLE;
				maxTokens = 4096;
				break;
			default:
				systemPrompt = SYSTEM_PROMPT_LIGHT;
				maxTokens = 4096;
		}

		const { readable, writable } = new TransformStream();
		const writer = writable.getWriter();
		const encoder = new TextEncoder();
		let pnjForTracking = knownPnj;

		(async () => {
			let fullContent = '', parsed = null, displayText = '', cycleForSave = currentCycle;

			try {
				console.log(`[STREAM] Start streaming (${promptMode} mode)...`);
				const streamStart = Date.now();

				const streamResponse = await anthropic.messages.stream({
					model: 'claude-sonnet-4-20250514',
					max_tokens: maxTokens,
					system: systemPrompt,
					messages: [{ role: 'user', content: contextMessage }]
				});

				for await (const event of streamResponse) {
					if (event.type === 'content_block_delta' && event.delta?.text) {
						fullContent += event.delta.text;
						await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: event.delta.text })}\n\n`));
					}
				}
				console.log(`[STREAM] Streaming complete: ${Date.now() - streamStart}ms`);

				// Parser le JSON
				parsed = extractJSON(fullContent);

				// Construire le texte d'affichage
				if (parsed) {
					displayText = '';
					const narratif = parsed.narratif || '';

					// Ajouter l'heure seulement si le narratif ne commence pas déjà par elle
					if (parsed.heure && !narratif.trim().startsWith(`[${parsed.heure}]`)) {
						displayText += `[${parsed.heure}] `;
					}

					displayText += narratif;

					if (parsed.choix?.length > 0) {
						displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
					}

					if (parsed.nouveau_jour?.cycle) {
						cycleForSave = parsed.nouveau_jour.cycle;
					}
				} else {
					displayText = fullContent.replace(/```json[\s\S]*?```/g, '').replace(/\{[\s\S]*\}$/g, '').trim() || "Erreur de génération.";
				}

				// Sauvegarder les messages
				if (partieId) {
					await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'user', content: message, cycle: cycleForSave });
					await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'assistant', content: displayText, cycle: cycleForSave });
				}

				// Charger PNJ si nécessaire
				if (partieId && pnjForTracking.length === 0) {
					const { data } = await supabase.from('pnj').select('*').eq('partie_id', partieId);
					pnjForTracking = data || [];
				}

				// Construire le state pour le client selon le mode
				let stateForClient = null;

				if (promptMode === 'init' && parsed?.init) {
					stateForClient = {
						cycle: parsed.init.cycle || 1,
						jour: parsed.init.jour,
						date_jeu: parsed.init.date_jeu,
						lieu_actuel: parsed.init.lieu_actuel || null,
						valentin: {
							energie: 3,
							moral: 3,
							sante: 5,
							credits: 1400,
							inventaire: [],
							poste: parsed.init.valentin?.poste || null,
							raison_depart: parsed.init.valentin?.raison_depart || null
						},
						ia: parsed.init.ia?.nom ? { nom: parsed.init.ia.nom } : null
					};
				} else if (promptMode === 'newcycle' && parsed?.nouveau_jour) {
					const [credits, inventaire] = await Promise.all([
						calculerSolde(supabase, partieId),
						calculerInventaire(supabase, partieId)
					]);

					stateForClient = {
						cycle: parsed.nouveau_jour.cycle,
						jour: parsed.nouveau_jour.jour,
						date_jeu: parsed.nouveau_jour.date_jeu,
						lieu_actuel: parsed.lieu_actuel || null,
						valentin: parsed.reveil_valentin ? {
							energie: parsed.reveil_valentin.energie,
							moral: parsed.reveil_valentin.moral,
							sante: parsed.reveil_valentin.sante,
							credits,
							inventaire
						} : { credits, inventaire }
					};
				} else if (promptMode === 'light' && parsed && partieId) {
					// Mode LIGHT : appliquer les deltas et récupérer les valeurs finales
					const deltaResults = await applyDeltas(
						supabase, partieId, parsed, pnjForTracking, cycleForSave, parsed.heure
					);
					console.log(`[STREAM] Apply deltas:`, deltaResults);

					// Récupérer le cycle actuel et les crédits/inventaire
					const [partieData, credits, inventaire] = await Promise.all([
						supabase.from('parties')
							.select('cycle_actuel, jour, date_jeu, lieu_actuel')
							.eq('id', partieId)
							.single()
							.then(r => r.data),
						calculerSolde(supabase, partieId),
						calculerInventaire(supabase, partieId)
					]);

					stateForClient = {
						cycle: partieData?.cycle_actuel || cycleForSave,
						jour: partieData?.jour,
						date_jeu: partieData?.date_jeu,
						lieu_actuel: parsed.lieu_actuel || partieData?.lieu_actuel,
						valentin: {
							...(deltaResults.valentin || {}),
							credits,
							inventaire
						}
					};
				}

				// Envoyer le 'done' avec le state final
				await writer.write(encoder.encode(`data: ${JSON.stringify({
					type: 'done',
					displayText,
					heure: parsed?.heure,
					mode: promptMode,
					state: stateForClient
				})}\n\n`));

				await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

			} catch (error) {
				console.error('Streaming error:', error);
				try {
					await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`));
				} catch (e) { }
			} finally {
				try { await writer.close(); } catch (e) { }
			}

			// === TÂCHES EN ARRIÈRE-PLAN (après fermeture du stream) ===
			console.log(`\n========== BACKGROUND TASKS (${promptMode}) ==========`);
			const bgStart = Date.now();

			if (partieId && parsed) {

				// MODE INIT : sauvegarder les données initiales
				if (promptMode === 'init' && parsed.init) {
					const t0 = Date.now();
					await processInitMode(supabase, partieId, parsed.init, parsed.heure);
					console.log(`[BG] Process INIT: ${Date.now() - t0}ms`);
				}

				// MODE NEWCYCLE : sauvegarder les données du nouveau cycle
				else if (promptMode === 'newcycle') {
					const t0 = Date.now();
					await processNewCycleMode(supabase, partieId, parsed, pnjForTracking);
					console.log(`[BG] Process NEWCYCLE: ${Date.now() - t0}ms`);
				}

				// MODE LIGHT : deltas déjà appliqués avant l'envoi du 'done'

				// Mise à jour dernier_contact (tous les modes)
				if (parsed.narratif && pnjForTracking.length > 0) {
					const pnjMentionnes = extractPnjFromNarratif(parsed.narratif, pnjForTracking);
					if (pnjMentionnes.length > 0) {
						await updatePnjContact(supabase, partieId, cycleForSave, pnjMentionnes);
					}
				}

				// Faits (tous les modes)
				if (faitsEnabled) {
					try {
						const extraction = extraireFaits(parsed, cycleForSave);
						if (extraction.nouveaux.length > 0 || extraction.modifies.length > 0) {
							if (promptMode === 'init' || parsed.nouveaux_pnj?.length > 0) {
								const { data } = await supabase.from('pnj').select('*').eq('partie_id', partieId);
								pnjForTracking = data || [];
							}
							const pnjMap = new Map(pnjForTracking.map(p => [p.nom.toLowerCase(), p.id]));
							const resultats = await sauvegarderFaits(supabase, partieId, extraction, pnjMap);
							console.log(`[BG] Faits: +${resultats.ajoutes}, ~${resultats.invalides}`);
						}
					} catch (err) {
						console.error('[BG] Erreur faits:', err);
					}
				}
			}

			console.log(`========== BACKGROUND END: ${Date.now() - bgStart}ms ==========\n`);
		})();

		return new Response(readable, {
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-cache, no-transform',
				'Connection': 'keep-alive',
				'X-Accel-Buffering': 'no'
			}
		});
	} catch (e) {
		console.error('Erreur POST:', e);
		return Response.json({ error: e.message }, { status: 500 });
	}
}
