/**
 * API Route principale pour LDVELH
 * Orchestrateur léger qui délègue aux modules spécialisés
 */

import Anthropic from '@anthropic-ai/sdk';
import { supabase } from '../../../lib/supabase.js';

// Prompts
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_LIGHT } from '../../../lib/prompt.js';

import { generateAndFormatConstraints } from '../../../lib/diversity/diversityConstraints.js';

// Context
import { buildContext, buildContextInit } from '../../../lib/context/contextBuilder.js';

// Game processors
import { processInitMode } from '../../../lib/game/initProcessor.js';
import { processLightMode, extractionBackground, ensureSceneExists } from '../../../lib/game/lightProcessor.js';
import {
	loadGameState,
	loadChatMessages,
	normalizeGameState,
	buildClientStateFromInit,
	buildClientStateFromLight,
	createStateSnapshot,
	restoreStateSnapshot
} from '../../../lib/game/gameState.js';

// KG
import { rollbackKG } from '../../../lib/kg/kgService.js';

// Scene
import { getSceneEnCours } from '../../../lib/scene/sceneService.js';

// API helpers
import { SSEWriter, streamClaudeResponse } from '../../../lib/api/streamHandler.js';
import { parseAndValidate } from '../../../lib/api/responseParser.js';

// Errors
import { errorToResponse, LDVELHError } from '../../../lib/errors.js';

// ============================================================================
// CONFIGURATION
// ============================================================================

export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const MODEL = 'claude-sonnet-4-5';

// ============================================================================
// GET HANDLER
// ============================================================================

export async function GET(request) {
	try {
		const { searchParams } = new URL(request.url);
		const action = searchParams.get('action');
		const partieId = searchParams.get('partieId');

		switch (action) {
			case 'load':
				return await handleLoad(partieId);

			case 'list':
				return await handleList();

			case 'new':
				return await handleNew();

			case 'delete':
				return await handleDelete(partieId);

			case 'rename':
				const newName = searchParams.get('name');
				return await handleRename(partieId, newName);

			default:
				return Response.json({ error: 'Action non reconnue' }, { status: 400 });
		}
	} catch (e) {
		return errorToResponse(e);
	}
}

// ============================================================================
// DELETE HANDLER (édition de messages)
// ============================================================================

export async function DELETE(request) {
	try {
		const { partieId, fromIndex } = await request.json();

		if (!partieId) {
			return Response.json({ error: 'partieId manquant' }, { status: 400 });
		}

		// Récupérer tous les messages
		const { data: allMessages } = await supabase
			.from('chat_messages')
			.select('id, created_at, cycle, state_snapshot')
			.eq('partie_id', partieId)
			.order('created_at', { ascending: true });

		if (!allMessages || fromIndex >= allMessages.length) {
			return Response.json({ success: true });
		}

		const rollbackTimestamp = allMessages[fromIndex].created_at;
		const snapshot = allMessages[fromIndex].state_snapshot;

		// Restaurer l'état depuis le snapshot
		if (snapshot) {
			await restoreStateSnapshot(supabase, partieId, snapshot);
		}

		// Rollback le KG
		await rollbackKG(supabase, partieId, rollbackTimestamp);

		// Supprimer les messages
		const messagesToDelete = allMessages.slice(fromIndex);
		if (messagesToDelete.length > 0) {
			await supabase
				.from('chat_messages')
				.delete()
				.in('id', messagesToDelete.map(m => m.id));
		}

		// Charger le nouvel état
		const newState = await loadGameState(supabase, partieId);

		return Response.json({
			success: true,
			deleted: messagesToDelete.length,
			state: newState
		});

	} catch (e) {
		return errorToResponse(e);
	}
}

// ============================================================================
// POST HANDLER (message principal)
// ============================================================================

export async function POST(request) {
	const sseWriter = new SSEWriter();

	// Lancer le traitement async
	handlePostAsync(request, sseWriter).catch(async (e) => {
		console.error('[POST] Erreur non catchée:', e);
		await sseWriter.sendError(e.message, null, false);
		await sseWriter.close();
	});

	return sseWriter.getResponse();
}

async function handlePostAsync(request, sseWriter) {
	try {
		const { message, partieId, gameState } = await request.json();
		const currentCycle = gameState?.partie?.cycle_actuel || 1;

		// Déterminer le mode
		const isInitMode = !gameState || !gameState.partie;
		const promptMode = isInitMode ? 'init' : 'light';

		console.log(`[POST] Mode: ${promptMode}, Cycle: ${currentCycle}`);

		// Récupérer la scène en cours (mode light)
		let sceneEnCours = null;
		if (!isInitMode) {
			sceneEnCours = await getSceneEnCours(supabase, partieId);
		}

		// Construire le contexte
		const contextMessage = isInitMode
			? buildContextInit()
			: (await buildContext(supabase, partieId, gameState, message)).context;

		// Configuration du prompt
		// const systemPrompt = isInitMode ? SYSTEM_PROMPT_INIT : SYSTEM_PROMPT_LIGHT;
		// remplacé par :
		let systemPrompt;
		if (isInitMode) {
			// Générer les contraintes de diversité
			const { promptText: diversityText } = generateAndFormatConstraints();

			// Injecter les contraintes dans le prompt
			systemPrompt = SYSTEM_PROMPT_INIT + diversityText;

			console.log('[INIT] Contraintes de diversité générées');
		} else {
			systemPrompt = SYSTEM_PROMPT_LIGHT;
		}
		const maxTokens = isInitMode ? 8192 : 4096;

		// Variables pour le traitement post-stream
		let finalParsed = null;
		let finalDisplayText = '';
		let sceneIdPourSauvegarde = sceneEnCours?.id || null;

		// Stream la réponse Claude
		await streamClaudeResponse({
			anthropic,
			model: MODEL,
			systemPrompt,
			userMessage: contextMessage,
			maxTokens,
			mode: promptMode,
			sseWriter,

			onComplete: async (parsed, displayText, fullJson) => {
				finalParsed = parsed;
				finalDisplayText = displayText;

				// Traitement selon le mode
				let stateForClient = null;

				if (isInitMode && parsed && partieId) {
					// === MODE INIT ===
					const initResult = await processInitMode(supabase, partieId, parsed, 1);
					sceneIdPourSauvegarde = initResult.sceneId;
					stateForClient = buildClientStateFromInit(parsed);

				} else if (!isInitMode && parsed && partieId) {
					// === MODE LIGHT ===
					const lightResult = await processLightMode(
						supabase,
						partieId,
						parsed,
						currentCycle,
						sceneEnCours
					);

					// Mettre à jour l'ID de scène si changement
					if (lightResult.scene_changed || !sceneIdPourSauvegarde) {
						sceneIdPourSauvegarde = lightResult.sceneId;
					}

					// Construire le state client
					stateForClient = await buildClientStateFromLight(
						supabase,
						partieId,
						parsed,
						currentCycle
					);
				}

				// Envoyer done au client
				await sseWriter.sendDone(displayText, stateForClient);

				// === SAUVEGARDE ===
				if (partieId) {
					await saveMessages(
						supabase,
						partieId,
						sceneIdPourSauvegarde,
						message,
						displayText,
						currentCycle
					);
				}

				// === TÂCHES BACKGROUND ===
				console.log('[POST] Lancement tâches background...');
				const bgStart = Date.now();

				// Extraction KG (mode light uniquement)
				if (!isInitMode && parsed && partieId) {
					extractionBackground(
						supabase,
						partieId,
						displayText,
						parsed,
						currentCycle,
						sceneEnCours?.id
					).catch(err => console.error('[BG] Erreur extraction:', err));
				}

				await sseWriter.sendSaved();
				console.log(`[POST] Background terminé: ${Date.now() - bgStart}ms`);
			}
		});

	} catch (e) {
		console.error('[POST] Erreur:', e);
		await sseWriter.sendError(
			e instanceof LDVELHError ? e.message : 'Erreur serveur',
			e instanceof LDVELHError ? e.details : null,
			true
		);
	} finally {
		await sseWriter.close();
	}
}

// ============================================================================
// HANDLERS GET
// ============================================================================

async function handleLoad(partieId) {
	if (!partieId) {
		return Response.json({ error: 'partieId manquant' }, { status: 400 });
	}

	console.log('[LOAD] Chargement partie:', partieId);

	const [state, messages] = await Promise.all([
		loadGameState(supabase, partieId),
		loadChatMessages(supabase, partieId)
	]);

	return Response.json({ state, messages });
}

async function handleList() {
	const { data } = await supabase
		.from('parties')
		.select('id, nom, cycle_actuel, updated_at, created_at')
		.eq('active', true)
		.order('updated_at', { ascending: false });

	return Response.json({ parties: data || [] });
}

async function handleNew() {
	const { data: partie, error } = await supabase
		.from('parties')
		.insert({
			nom: 'Nouvelle partie',
			cycle_actuel: 1,
			active: true
		})
		.select()
		.single();

	if (error) {
		throw error;
	}

	return Response.json({ partieId: partie.id });
}

async function handleDelete(partieId) {
	if (!partieId) {
		return Response.json({ error: 'partieId manquant' }, { status: 400 });
	}

	// Récupérer les IDs des événements
	const { data: evenements } = await supabase
		.from('kg_evenements')
		.select('id')
		.eq('partie_id', partieId);

	const evenementIds = (evenements || []).map(e => e.id);

	// Supprimer les participants
	if (evenementIds.length > 0) {
		await supabase
			.from('kg_evenement_participants')
			.delete()
			.in('evenement_id', evenementIds);
	}

	// Supprimer les tables (parallèle)
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

	// Supprimer la partie
	await supabase.from('parties').delete().eq('id', partieId);

	return Response.json({ success: true });
}

async function handleRename(partieId, newName) {
	if (!partieId || !newName) {
		return Response.json({ error: 'Paramètres manquants' }, { status: 400 });
	}

	await supabase
		.from('parties')
		.update({ nom: newName })
		.eq('id', partieId);

	return Response.json({ success: true });
}

// ============================================================================
// HELPERS
// ============================================================================

async function saveMessages(supabase, partieId, sceneId, userMessage, assistantMessage, cycle) {
	// Snapshot avant ce message (pour rollback)
	const snapshot = await createStateSnapshot(supabase, partieId);

	await supabase.from('chat_messages').insert([
		{
			partie_id: partieId,
			scene_id: sceneId,
			role: 'user',
			content: userMessage,
			cycle,
			state_snapshot: snapshot
		},
		{
			partie_id: partieId,
			scene_id: sceneId,
			role: 'assistant',
			content: assistantMessage,
			cycle,
			state_snapshot: null
		}
	]);
}
