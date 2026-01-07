/**
 * API Route principale pour LDVELH
 */

import Anthropic from '@anthropic-ai/sdk';
import { supabase } from '../../../lib/supabase.js';

import { MODELS, API_CONFIG } from '../../../lib/constants.js';

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

		if (snapshot) {
			await restoreStateSnapshot(supabase, partieId, snapshot);
		}

		await rollbackKG(supabase, partieId, rollbackTimestamp);

		const messagesToDelete = allMessages.slice(fromIndex);
		if (messagesToDelete.length > 0) {
			await supabase
				.from('chat_messages')
				.delete()
				.in('id', messagesToDelete.map(m => m.id));
		}

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

		const isInitMode = !gameState || !gameState.partie;
		const promptMode = isInitMode ? 'init' : 'light';

		console.log(`[POST] Mode: ${promptMode}, Cycle: ${currentCycle}`);

		let sceneEnCours = null;
		if (!isInitMode) {
			sceneEnCours = await getSceneEnCours(supabase, partieId);
		}

		const contextMessage = isInitMode
			? buildContextInit()
			: (await buildContext(supabase, partieId, gameState, message)).context;

		let systemPrompt;
		if (isInitMode) {
			const { promptText: diversityText } = generateAndFormatConstraints();
			systemPrompt = SYSTEM_PROMPT_INIT + diversityText;
			console.log('[INIT] Contraintes de diversité générées');
		} else {
			systemPrompt = SYSTEM_PROMPT_LIGHT;
		}
		const maxTokens = isInitMode ? API_CONFIG.MAX_TOKENS_INIT : API_CONFIG.MAX_TOKENS_LIGHT;

		let finalParsed = null;
		let finalDisplayText = '';
		let sceneIdPourSauvegarde = sceneEnCours?.id || null;

		await streamClaudeResponse({
			anthropic,
			model: MODELS.MAIN,
			systemPrompt,
			userMessage: contextMessage,
			maxTokens,
			mode: promptMode,
			sseWriter,

			onComplete: async (parsed, displayText, fullJson) => {
				finalParsed = parsed;
				finalDisplayText = displayText;

				let stateForClient = null;

				if (isInitMode && parsed && partieId) {
					// === MODE INIT ===
					const initResult = await processInitMode(supabase, partieId, parsed, 1);
					sceneIdPourSauvegarde = initResult.sceneId;
					stateForClient = buildClientStateFromInit(parsed);

				} else if (!isInitMode && parsed && partieId) {
					// === MODE LIGHT ===
					// processLightMode ne traite plus que les scènes et la mise à jour partie
					const lightResult = await processLightMode(
						supabase,
						partieId,
						parsed,
						currentCycle,
						sceneEnCours
					);

					if (lightResult.scene_changed || !sceneIdPourSauvegarde) {
						sceneIdPourSauvegarde = lightResult.sceneId;
					}

					// Le state client est construit depuis la BDD (pas depuis le JSON Sonnet)
					stateForClient = await buildClientStateFromLight(
						supabase,
						partieId,
						parsed,
						currentCycle
					);
				}

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

				// === EXTRACTION BACKGROUND (5 extracteurs parallèles) ===
				console.log('[POST] Lancement extraction background...');
				const bgStart = Date.now();

				if (!isInitMode && parsed && partieId) {
					// L'extraction est maintenant TOUJOURS lancée (plus de doitExtraire)
					extractionBackground(
						supabase,
						partieId,
						displayText,
						parsed,
						currentCycle,
						sceneIdPourSauvegarde
					).catch(err => console.error('[BG] Erreur extraction:', err));
				}

				await sseWriter.sendSaved();
				console.log(`[POST] Background lancé en ${Date.now() - bgStart}ms`);
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
// HANDLERS GET (INCHANGÉS)
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

	const { data: evenements } = await supabase
		.from('kg_evenements')
		.select('id')
		.eq('partie_id', partieId);

	const evenementIds = (evenements || []).map(e => e.id);

	if (evenementIds.length > 0) {
		await supabase
			.from('kg_evenement_participants')
			.delete()
			.in('evenement_id', evenementIds);
	}

	await Promise.all([
		supabase.from('chat_messages').delete().eq('partie_id', partieId),
		supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
		supabase.from('scenes').delete().eq('partie_id', partieId),
		supabase.from('kg_extraction_logs').delete().eq('partie_id', partieId),
		supabase.from('kg_evenements').delete().eq('partie_id', partieId),
		supabase.from('kg_etats').delete().eq('partie_id', partieId),
		supabase.from('kg_connaissances').delete().eq('partie_id', partieId),
		supabase.from('kg_relations').delete().eq('partie_id', partieId),
		supabase.from('kg_entites').delete().eq('partie_id', partieId)
	]);

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
