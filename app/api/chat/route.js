import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_LIGHT } from '../../../lib/prompt';
import { buildContext, buildContextInit } from '../../../lib/contextBuilder';
import {
	getProtagoniste,
	getStatsValentin,
	getInventaire,
	updateStatsValentin,
	creerTransaction,
	appliquerOperations,
	trouverEntite,
	rollbackKG
} from '../../../lib/kgService';
import { extraireEtAppliquer, doitExtraire } from '../../../lib/kgExtractor';
import {
	getSceneEnCours,
	creerScene,
	fermerScene,
	ajouterPnjImpliques,
	doitAnalyserIntermediaire,
	marquerAnalysee
} from '../../../lib/sceneService';

export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
	process.env.NEXT_PUBLIC_SUPABASE_URL,
	process.env.SUPABASE_SERVICE_KEY
);
//
// Constantes pour l'intérêt romantique
const AGE_MIN_ROMANCE = 25;
const AGE_MAX_ROMANCE = 45;

// ============================================================================
// PARSING JSON
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

	// Tenter réparation
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

	// Fermer les accolades manquantes
	if (inString) fixed += '"';
	while (braceCount > 0) { fixed += '}'; braceCount--; }

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
// CHARGEMENT ÉTAT (depuis KG)
// ============================================================================

async function loadGameState(partieId) {
	const [partie, protagoniste, stats, inventaire] = await Promise.all([
		supabase.from('parties').select('*').eq('id', partieId).single().then(r => r.data),
		getProtagoniste(supabase, partieId),
		getStatsValentin(supabase, partieId),
		getInventaire(supabase, partieId)
	]);

	// Récupérer l'IA
	const { data: iaData } = await supabase
		.from('kg_entites')
		.select('nom, proprietes')
		.eq('partie_id', partieId)
		.eq('type', 'ia')
		.single();

	return {
		partie,
		valentin: {
			...protagoniste?.proprietes,  // D'abord les propriétés statiques (compétences, traits...)
			...stats,                     // ENSUITE les stats (écrase credits, energie, etc.)
			inventaire: inventaire.map(i => i.objet_nom)
		},
		ia: iaData ? { nom: iaData.nom, ...iaData.proprietes } : null
	};
}

async function loadChatMessages(partieId) {
	const { data } = await supabase.from('chat_messages')
		.select('role, content, cycle, scene_id, created_at')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: true });
	return data || [];
}

// ============================================================================
// GESTION DES SCÈNES
// ============================================================================

async function gererChangementScene(partieId, cycle, ancienLieu, nouveauLieu, heure, pnjsPresents) {
	const sceneEnCours = await getSceneEnCours(supabase, partieId);

	if (sceneEnCours && ancienLieu && nouveauLieu &&
		ancienLieu.toLowerCase() !== nouveauLieu.toLowerCase()) {
		console.log(`[SCENE] Changement: ${ancienLieu} → ${nouveauLieu}`);

		// Fermer l'ancienne scène
		await fermerScene(supabase, sceneEnCours.id, heure, pnjsPresents);

		// Extraction KG en background sur la scène terminée
		extraireSceneEnBackground(partieId, sceneEnCours.id, cycle);

		// Créer la nouvelle scène
		const nouvelleScene = await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
		return nouvelleScene;
	}

	if (!sceneEnCours && nouveauLieu) {
		console.log(`[SCENE] Création première scène: ${nouveauLieu}`);
		return await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
	}

	return sceneEnCours;
}

async function extraireSceneEnBackground(partieId, sceneId, cycle) {
	try {
		// Récupérer les messages de la scène
		const { data: messages } = await supabase
			.from('chat_messages')
			.select('role, content')
			.eq('scene_id', sceneId)
			.order('created_at');

		if (!messages?.length) return;

		// Concaténer les narratifs
		const narratif = messages
			.filter(m => m.role === 'assistant')
			.map(m => m.content)
			.join('\n\n');

		if (narratif.trim()) {
			const result = await extraireEtAppliquer(supabase, partieId, narratif, cycle, sceneId);

			if (result.success && result.resume) {
				await marquerAnalysee(supabase, sceneId, result.resume);
			}
		}
	} catch (err) {
		console.error('[SCENE] Erreur extraction background:', err);
	}
}

// ============================================================================
// TRAITEMENT MODE INIT (création KG)
// ============================================================================

async function processInitMode(partieId, parsed, cycle) {
	console.log('[INIT] Création du Knowledge Graph initial');

	const operations = [];

	// 1. Créer le protagoniste (Valentin)
	operations.push({
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
			competences: {
				informatique: 5, systemes: 4, recherche: 4,
				social: 2, cuisine: 3, bricolage: 3,
				observation: 3, culture: 3, sang_froid: 3,
				pedagogie: 3, physique: 3, administration: 3, jeux: 3,
				discretion: 2, negociation: 2, empathie: 2,
				art: 2, commerce: 2, leadership: 2, xenologie: 2,
				medical: 1, pilotage: 1, mensonge: 1, survie: 1,
				intimidation: 1, seduction: 1, droit: 1, botanique: 1
			}
		}
	});

	// 2. Créer l'IA
	if (parsed.ia?.nom) {
		operations.push({
			op: 'CREER_ENTITE',
			type: 'ia',
			nom: parsed.ia.nom,
			proprietes: {
				traits: ['sarcastique', 'pragmatique'],
				voix: 'grave, sensuelle'
			}
		});

		operations.push({
			op: 'CREER_RELATION',
			source: parsed.ia.nom,
			cible: 'Valentin',
			type: 'assiste'
		});
	}

	// 3. Créer le monde (station/base)
	if (parsed.monde) {
		operations.push({
			op: 'CREER_ENTITE',
			type: 'lieu',
			nom: parsed.monde.nom,
			proprietes: {
				niveau: 'zone',
				type_lieu: parsed.monde.type,
				ambiance: parsed.monde.ambiance,
				population: parsed.monde.population,
				orbite: parsed.monde.orbite
			}
		});
	}

	// 4. Créer l'employeur
	if (parsed.employeur) {
		operations.push({
			op: 'CREER_ENTITE',
			type: 'organisation',
			nom: parsed.employeur.nom,
			proprietes: {
				type_org: 'entreprise',
				domaine: parsed.employeur.type
			}
		});

		operations.push({
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: parsed.employeur.nom,
			type: 'employe_de',
			proprietes: { poste: parsed.valentin?.poste }
		});

		if (parsed.monde?.nom) {
			operations.push({
				op: 'CREER_RELATION',
				source: parsed.employeur.nom,
				cible: parsed.monde.nom,
				type: 'siege_de'
			});
		}
	}

	// 5. Créer les lieux initiaux
	for (const lieu of (parsed.lieux_initiaux || [])) {
		operations.push({
			op: 'CREER_ENTITE',
			type: 'lieu',
			nom: lieu.nom,
			proprietes: {
				niveau: 'lieu',
				type_lieu: lieu.type,
				ambiance: lieu.description,
				horaires: lieu.horaires
			}
		});

		// Lier au secteur ou à la station
		const parent = lieu.secteur || parsed.monde?.nom;
		if (parent) {
			operations.push({
				op: 'CREER_RELATION',
				source: lieu.nom,
				cible: parent,
				type: 'situe_dans'
			});
		}

		// Relations "frequente" pour les PNJ fréquents
		for (const freq of (lieu.pnjs_frequents || [])) {
			operations.push({
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
	}

	// 6. Créer les PNJ initiaux
	for (const pnj of (parsed.pnj_initiaux || [])) {
		// Déterminer si intérêt romantique potentiel
		const sexe = (pnj.sexe || '').toUpperCase();
		const age = pnj.age || 0;
		const interetRomantique = (
			sexe === 'F' &&
			age >= AGE_MIN_ROMANCE &&
			age <= AGE_MAX_ROMANCE
		);

		operations.push({
			op: 'CREER_ENTITE',
			type: 'personnage',
			nom: pnj.nom,
			alias: [pnj.nom.split(' ')[0]], // Prénom comme alias
			proprietes: {
				sexe: sexe,
				age: pnj.age,
				espece: pnj.espece || 'humain',
				metier: pnj.metier,
				physique: pnj.physique,
				traits: pnj.traits || [],
				interet_romantique: interetRomantique
			}
		});

		// Relation initiale avec Valentin (niveau 0)
		operations.push({
			op: 'CREER_RELATION',
			source: 'Valentin',
			cible: pnj.nom,
			type: 'connait',
			proprietes: {
				niveau: 0,
				// etape_romantique seulement si intérêt potentiel
				...(interetRomantique && { etape_romantique: 0 })
			}
		});

		// Lieu de domicile si connu
		if (pnj.domicile) {
			operations.push({
				op: 'CREER_RELATION',
				source: pnj.nom,
				cible: pnj.domicile,
				type: 'habite'
			});
		}

		// Créer les arcs personnels du PNJ comme entités
		for (const arcTitre of (pnj.arcs || [])) {
			operations.push({
				op: 'CREER_ENTITE',
				type: 'arc_narratif',
				nom: arcTitre,
				proprietes: {
					type_arc: 'pnj_personnel',
					description: `Arc personnel de ${pnj.nom}`,
					progression: 0,
					etat: 'actif'
				}
			});

			// Lier le PNJ à son arc
			operations.push({
				op: 'CREER_RELATION',
				source: pnj.nom,
				cible: arcTitre,
				type: 'implique_dans',
				proprietes: { role: 'protagoniste' }
			});
		}
	}

	// 7. Créer les arcs narratifs
	for (const arc of (parsed.arcs_potentiels || [])) {
		operations.push({
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
		});

		// Lier les PNJ impliqués
		for (const pnjNom of (arc.pnjs_impliques || [])) {
			operations.push({
				op: 'CREER_RELATION',
				source: pnjNom,
				cible: arc.nom,
				type: 'implique_dans'
			});
		}
	}

	// 8. États initiaux de Valentin
	const valentinId = await trouverEntite(supabase, partieId, 'Valentin', 'protagoniste');

	// Appliquer toutes les opérations
	const resultats = await appliquerOperations(supabase, partieId, operations, cycle);
	console.log(`[INIT] ${resultats.entites_creees} entités, ${resultats.relations_creees} relations`);

	// États initiaux (après création des entités)
	const protagoniste = await getProtagoniste(supabase, partieId);
	if (protagoniste) {
		for (const [attr, val] of [['energie', '3'], ['moral', '3'], ['sante', '5'], ['credits', '1400']]) {
			await supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: protagoniste.id,
				p_attribut: attr,
				p_valeur: val,
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			});
		}
	}

	// États initiaux des PNJ (stats)
	for (const pnj of (parsed.pnj_initiaux || [])) {
		const pnjId = await trouverEntite(supabase, partieId, pnj.nom, 'personnage');
		if (pnjId) {
			await supabase.rpc('kg_set_etat', {
				p_partie_id: partieId,
				p_entite_id: pnjId,
				p_attribut: 'disposition',
				p_valeur: 'neutre',
				p_cycle: cycle,
				p_details: null,
				p_certitude: 'certain',
				p_verite: true
			});
		}
	}

	// Mettre à jour la partie
	await supabase.from('parties').update({
		cycle_actuel: parsed.cycle || 1,
		jour: parsed.jour,
		date_jeu: parsed.date_jeu,
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel
	}).eq('id', partieId);

	// Créer la première scène
	if (parsed.lieu_actuel) {
		await creerScene(supabase, partieId, 1, parsed.lieu_actuel, parsed.heure);
	}

	return resultats;
}

// ============================================================================
// TRAITEMENT MODE LIGHT
// ============================================================================

async function processLightMode(partieId, parsed, cycle, sceneEnCours) {
	const resultats = {
		stats_updated: false,
		transactions: 0,
		scene_changed: false
	};

	// 1. Deltas Valentin (stats)
	if (parsed.deltas_valentin) {
		const d = parsed.deltas_valentin;
		if (d.energie || d.moral || d.sante) {
			await updateStatsValentin(supabase, partieId, cycle, d);
			resultats.stats_updated = true;
		}
	}

	// 2. Transactions
	if (parsed.transactions?.length > 0) {
		for (const tx of parsed.transactions) {
			await creerTransaction(supabase, partieId, cycle, {
				type: tx.type,
				montant: tx.montant,
				description: tx.description,
				objet: tx.objet,
				quantite: tx.quantite,
				heure: parsed.heure
			});
			resultats.transactions++;
		}
	}

	// 3. Changement de lieu = changement de scène
	const ancienLieu = sceneEnCours?.lieu;
	const nouveauLieu = parsed.lieu_actuel;

	if (nouveauLieu && ancienLieu && nouveauLieu.toLowerCase() !== ancienLieu.toLowerCase()) {
		await gererChangementScene(partieId, cycle, ancienLieu, nouveauLieu, parsed.heure, parsed.pnjs_presents);
		resultats.scene_changed = true;
	}

	// 4. Mise à jour partie
	await supabase.from('parties').update({
		heure: parsed.heure,
		lieu_actuel: parsed.lieu_actuel || ancienLieu,
		pnjs_presents: parsed.pnjs_presents || []
	}).eq('id', partieId);

	// 5. Ajouter PNJ à la scène
	if (parsed.pnjs_presents?.length > 0 && sceneEnCours?.id) {
		await ajouterPnjImpliques(supabase, sceneEnCours.id, parsed.pnjs_presents);
	}

	// 6. Nouveau cycle
	if (parsed.nouveau_cycle) {
		await supabase.from('parties').update({
			cycle_actuel: cycle + 1,
			jour: parsed.nouveau_jour?.jour,
			date_jeu: parsed.nouveau_jour?.date_jeu
		}).eq('id', partieId);

		// Fermer la scène en cours
		if (sceneEnCours?.id) {
			await fermerScene(supabase, sceneEnCours.id, parsed.heure, parsed.pnjs_presents);
			extraireSceneEnBackground(partieId, sceneEnCours.id, cycle);
		}
	}

	return resultats;
}

// ============================================================================
// EXTRACTION KG EN BACKGROUND
// ============================================================================

async function extractionBackground(partieId, narratif, parsed, cycle, sceneId) {
	// Vérifier si extraction nécessaire
	if (!doitExtraire(narratif, parsed)) {
		console.log('[KG] Extraction non nécessaire');
		return;
	}

	console.log('[KG] Lancement extraction background...');

	try {
		const result = await extraireEtAppliquer(supabase, partieId, narratif, cycle, sceneId);

		if (result.success) {
			console.log(`[KG] Extraction OK: ${result.metrics.nb_operations} ops`);
		} else {
			console.warn('[KG] Extraction avec erreurs:', result.metrics.erreurs);
		}
	} catch (err) {
		console.error('[KG] Erreur extraction:', err);
	}
}

// ============================================================================
// GESTION PARTIES
// ============================================================================

async function createNewGame() {
	const { data: partie, error } = await supabase.from('parties').insert({
		nom: 'Nouvelle partie',
		cycle_actuel: 1,
		active: true
	}).select().single();

	if (error) throw error;
	return partie.id;
}

async function deleteGame(partieId) {
	// 1. Récupérer les IDs des événements pour supprimer les participants
	const { data: evenements } = await supabase
		.from('kg_evenements')
		.select('id')
		.eq('partie_id', partieId);

	const evenementIds = (evenements || []).map(e => e.id);

	// 2. Supprimer les participants d'événements
	if (evenementIds.length > 0) {
		await supabase
			.from('kg_evenement_participants')
			.delete()
			.in('evenement_id', evenementIds);
	}

	// 3. Supprimer les tables principales (en parallèle)
	await Promise.all([
		supabase.from('chat_messages').delete().eq('partie_id', partieId),
		supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
		supabase.from('scenes').delete().eq('partie_id', partieId),
		supabase.from('kg_extraction_logs').delete().eq('partie_id', partieId),
		supabase.from('kg_evenements').delete().eq('partie_id', partieId),
		supabase.from('kg_etats').delete().eq('partie_id', partieId),
		supabase.from('kg_relations').delete().eq('partie_id', partieId),
		supabase.from('kg_entites').delete().eq('partie_id', partieId)
	]);

	// 4. Supprimer la partie
	await supabase.from('parties').delete().eq('id', partieId);
}

// ============================================================================
// GET HANDLER
// ============================================================================

export async function GET(request) {
	const { searchParams } = new URL(request.url);
	const action = searchParams.get('action');
	const partieId = searchParams.get('partieId');

	if (action === 'load' && partieId) {
		console.log('[LOAD] Chargement partie:', partieId);
		const state = await loadGameState(partieId);
		console.log('[LOAD] State chargé:', JSON.stringify(state?.valentin, null, 2));

		const messages = await loadChatMessages(partieId);
		return Response.json({ state, messages });
	}

	if (action === 'list') {
		const { data } = await supabase.from('parties')
			.select('id, nom, cycle_actuel, updated_at, created_at')
			.eq('active', true)
			.order('updated_at', { ascending: false });
		return Response.json({ parties: data });
	}

	if (action === 'new') {
		try {
			const partieId = await createNewGame();
			return Response.json({ partieId });
		} catch (e) {
			return Response.json({ error: e.message }, { status: 500 });
		}
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
			.select('id, created_at, cycle, state_snapshot')
			.eq('partie_id', partieId)
			.order('created_at', { ascending: true });

		if (!allMessages || fromIndex >= allMessages.length) {
			return Response.json({ success: true });
		}

		const rollbackTimestamp = allMessages[fromIndex].created_at;

		// Récupérer le snapshot du message à éditer
		const snapshot = allMessages[fromIndex].state_snapshot;

		// Restaurer l'état parties depuis le snapshot
		if (snapshot) {
			await supabase
				.from('parties')
				.update({
					cycle_actuel: snapshot.cycle_actuel,
					jour: snapshot.jour,
					date_jeu: snapshot.date_jeu,
					heure: snapshot.heure,
					lieu_actuel: snapshot.lieu_actuel,
					pnjs_presents: snapshot.pnjs_presents
				})
				.eq('id', partieId);
		}

		// Rollback le KG
		await rollbackKG(supabase, partieId, rollbackTimestamp);

		// Supprimer les messages
		const messagesToDelete = allMessages.slice(fromIndex);
		if (messagesToDelete.length > 0) {
			await supabase.from('chat_messages')
				.delete()
				.in('id', messagesToDelete.map(m => m.id));
		}

		const newState = await loadGameState(partieId);

		return Response.json({
			success: true,
			deleted: messagesToDelete.length,
			state: newState
		});
	} catch (e) {
		console.error('[DELETE] Erreur:', e);
		return Response.json({ error: e.message }, { status: 500 });
	}
}

// ============================================================================
// POST HANDLER
// ============================================================================

export async function POST(request) {
	try {
		const { message, partieId, gameState } = await request.json();
		const currentCycle = gameState?.partie?.cycle_actuel || 1;

		// Déterminer le mode
		let promptMode = 'light';
		let sceneEnCours = null;

		if (!gameState || !gameState.partie) {
			promptMode = 'init';
			console.log('[MODE] INIT - Lancement de partie');
		} else {
			console.log('[MODE] LIGHT - Message normal');
			sceneEnCours = await getSceneEnCours(supabase, partieId);
		}

		// Construire le contexte
		let contextMessage;
		if (promptMode === 'init') {
			contextMessage = buildContextInit();
		} else {
			const result = await buildContext(supabase, partieId, gameState, message);
			contextMessage = result.context;
			sceneEnCours = result.sceneEnCours || sceneEnCours;
		}

		// Sélectionner le prompt
		const systemPrompt = promptMode === 'init' ? SYSTEM_PROMPT_INIT : SYSTEM_PROMPT_LIGHT;
		const maxTokens = promptMode === 'init' ? 8192 : 4096;

		// Stream
		const { readable, writable } = new TransformStream();
		const writer = writable.getWriter();
		const encoder = new TextEncoder();

		(async () => {
			let fullContent = '';
			let parsed = null;
			let displayText = '';

			try {
				console.log(`[STREAM] Context:`, contextMessage);
				console.log(`[STREAM] Start streaming (${promptMode} mode)...`);
				const streamStart = Date.now();

				const streamResponse = await anthropic.messages.stream({
					model: 'claude-sonnet-4-20250514',
					temperature: 0.65,
					max_tokens: maxTokens,
					system: [{ type: 'text', text: systemPrompt, cache_control: { type: 'ephemeral' } }],
					messages: [{ role: 'user', content: contextMessage }]
				});

				for await (const event of streamResponse) {
					if (event.type === 'content_block_delta' && event.delta?.text) {
						fullContent += event.delta.text;
						await writer.write(encoder.encode(
							`data: ${JSON.stringify({ type: 'chunk', content: event.delta.text })}\n\n`
						));
					}
				}
				console.log(`[STREAM] Complete: ${Date.now() - streamStart}ms`);

				// Parser le JSON
				parsed = extractJSON(fullContent);
				console.log(`[STREAM] Parsed:`, JSON.stringify(parsed, null, 2));

				// Construire le texte d'affichage
				if (parsed) {
					displayText = '';
					if (parsed.heure) displayText += `[${parsed.heure}] `;
					displayText += parsed.narratif || '';
					if (parsed.choix?.length > 0) {
						displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
					}
				} else {
					displayText = fullContent.replace(/```json[\s\S]*?```/g, '').trim() || 'Erreur de génération.';
				}

				// Construire le state pour le client
				let stateForClient = null;
				let sceneIdPourSauvegarde = sceneEnCours?.id || null;

				if (promptMode === 'init' && parsed && partieId) {
					await processInitMode(partieId, parsed, 1);

					// Récupérer la scène créée
					const { data: nouvelleScene } = await supabase
						.from('scenes')
						.select('id')
						.eq('partie_id', partieId)
						.eq('statut', 'en_cours')
						.order('created_at', { ascending: false })
						.limit(1)
						.maybeSingle();
					sceneIdPourSauvegarde = nouvelleScene?.id || null;

					stateForClient = {
						cycle: parsed.cycle || 1,
						jour: parsed.jour,
						date_jeu: parsed.date_jeu,
						heure: parsed.heure,
						lieu_actuel: parsed.lieu_actuel,
						pnjs_presents: parsed.pnjs_presents || [],
						valentin: { energie: 3, moral: 3, sante: 5, credits: 1400 }
					};

				} else if (promptMode === 'light' && parsed && partieId) {
					const lightResults = await processLightMode(partieId, parsed, currentCycle, sceneEnCours);
					console.log(`[STREAM] Light Mode process ended:`, lightResults);

					// Si changement de scène, récupérer la nouvelle
					if (lightResults.scene_changed || !sceneIdPourSauvegarde) {
						const { data: nouvelleScene } = await supabase
							.from('scenes')
							.select('id')
							.eq('partie_id', partieId)
							.eq('statut', 'en_cours')
							.order('created_at', { ascending: false })
							.limit(1)
							.maybeSingle();
						sceneIdPourSauvegarde = nouvelleScene?.id || null;
					}

					// UNE SEULE requête combinée : partie + stats + inventaire
					const [partieData, stats, inventaire] = await Promise.all([
						supabase
							.from('parties')
							.select('jour, date_jeu')
							.eq('id', partieId)
							.single()
							.then(r => r.data),
						getStatsValentin(supabase, partieId),
						getInventaire(supabase, partieId)
					]);

					stateForClient = {
						cycle: parsed.nouveau_cycle ? currentCycle + 1 : currentCycle,
						jour: parsed.nouveau_jour?.jour || partieData?.jour,
						date_jeu: parsed.nouveau_jour?.date_jeu || partieData?.date_jeu,
						heure: parsed.heure,
						lieu_actuel: parsed.lieu_actuel,
						pnjs_presents: parsed.pnjs_presents || [],
						valentin: {
							...stats,
							inventaire: inventaire.map(i => i.objet_nom)
						}
					};
				}

				// Sauvegarder les messages APRÈS le traitement
				if (partieId) {
					// Snapshot de l'état AVANT ce message (pour rollback)
					const { data: partieAvant } = await supabase
						.from('parties')
						.select('cycle_actuel, jour, date_jeu, heure, lieu_actuel, pnjs_presents')
						.eq('id', partieId)
						.single();

					await supabase.from('chat_messages').insert([
						{
							partie_id: partieId,
							scene_id: sceneIdPourSauvegarde,
							role: 'user',
							content: message,
							cycle: currentCycle,
							state_snapshot: partieAvant
						},
						{
							partie_id: partieId,
							scene_id: sceneIdPourSauvegarde,
							role: 'assistant',
							content: displayText,
							cycle: currentCycle,
							state_snapshot: null
						}
					]);
				}

				// Envoyer done
				await writer.write(encoder.encode(
					`data: ${JSON.stringify({ type: 'done', displayText, state: stateForClient })}\n\n`
				));

				console.log(`\n========== BACKGROUND TASKS (${promptMode}) ==========`);
				const bgStart = Date.now();

				// Extraction KG en background (après envoi au client)
				if (partieId && parsed && promptMode === 'light') {
					extractionBackground(partieId, displayText, parsed, currentCycle, sceneEnCours?.id)
						.catch(err => console.error('[BG] Erreur:', err));
				}

				await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

				console.log(`========== BACKGROUND END: ${Date.now() - bgStart}ms ==========\n`);

			} catch (error) {
				console.error('Streaming error:', error);
				await writer.write(encoder.encode(
					`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`
				));
			} finally {
				await writer.close();
			}
		})();

		return new Response(readable, {
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-cache, no-transform',
				'Connection': 'keep-alive'
			}
		});

	} catch (e) {
		console.error('Erreur POST:', e);
		return Response.json({ error: e.message }, { status: 500 });
	}
}
