/**
 * API Route principale pour LDVELH
 * 
 * Gère 3 modes :
 * - INIT (World Builder) : Crée le monde, pas de narratif
 * - FIRST LIGHT : Premier narratif basé sur l'événement d'arrivée
 * - LIGHT : Narratif normal
 */

import Anthropic from '@anthropic-ai/sdk';
import { supabase } from '../../../lib/supabase.js';

import { MODELS, API_CONFIG } from '../../../lib/constants.js';

// Prompts
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_LIGHT } from '../../../lib/prompt.js';

import { generateAndFormatConstraints } from '../../../lib/diversity/diversityConstraints.js';

// Context
import { buildContext, buildContextInit, marquerArriveeRealisee } from '../../../lib/context/contextBuilder.js';

// Game processors
import { processInitMode } from '../../../lib/game/initProcessor.js';
import { processLightMode, extractionBackground } from '../../../lib/game/lightProcessor.js';
import {
	loadGameState,
	loadChatMessages,
	buildClientStateFromInit,
	buildClientStateFromLight,
	createStateSnapshot,
	restoreStateSnapshot
} from '../../../lib/game/gameState.js';

// KG
import { rollbackKG } from '../../../lib/kg/kgService.js';

// API helpers
import { SSEWriter, streamClaudeResponse } from '../../../lib/api/streamHandler.js';

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

		// =====================================================================
		// DÉTERMINER LE MODE
		// =====================================================================
		const isInitMode = !gameState || !gameState.partie;

		let promptMode, contextMessage, systemPrompt, maxTokens;
		let contextData = null;

		if (isInitMode) {
			// =================================================================
			// MODE INIT (World Builder)
			// =================================================================
			promptMode = 'init';
			contextMessage = buildContextInit();
			const { promptText: diversityText } = generateAndFormatConstraints();
			systemPrompt = SYSTEM_PROMPT_INIT + diversityText;
			maxTokens = API_CONFIG.MAX_TOKENS_INIT;

			console.log('[POST] Mode: INIT (World Builder)');

		} else {
			// =================================================================
			// MODE LIGHT (normal ou premier)
			// Le contexte détecte automatiquement si c'est le premier light
			// =================================================================
			contextData = await buildContext(supabase, partieId, gameState, message || '');

			if (contextData.isFirstLight) {
				promptMode = 'first_light';
				console.log('[POST] Mode: FIRST LIGHT (Premier narratif)');
			} else {
				promptMode = 'light';
				console.log(`[POST] Mode: LIGHT, Cycle: ${currentCycle}`);
			}

			contextMessage = contextData.context;
			systemPrompt = SYSTEM_PROMPT_LIGHT;
			maxTokens = API_CONFIG.MAX_TOKENS_LIGHT;
		}

		// =====================================================================
		// APPEL CLAUDE
		// =====================================================================

		await streamClaudeResponse({
			anthropic,
			model: MODELS.MAIN,
			systemPrompt,
			userMessage: contextMessage,
			maxTokens,
			mode: promptMode === 'first_light' ? 'light' : promptMode, // Pour le parser
			sseWriter,

			onComplete: async (parsed, displayText, fullJson) => {

				// =============================================================
				// MODE INIT : Pas de narratif, juste le monde
				// =============================================================
				if (isInitMode && parsed && partieId) {
					const initResult = await processInitMode(supabase, partieId, parsed, 1);

					// Envoyer au client un état "monde créé" sans narratif
					await sseWriter.sendDone(null, {
						monde_cree: true,
						monde: initResult.monde,
						ia_nom: initResult.ia_nom,
						lieu_depart: initResult.lieu_depart,
						credits: initResult.credits,
						// Passer les données complètes pour affichage
						evenement_arrivee: parsed.evenement_arrivee
					});

					// Pas de sauvegarde de message (pas de narratif)
					await sseWriter.sendSaved();
					return;
				}

				// =============================================================
				// MODE FIRST LIGHT : Premier narratif
				// =============================================================
				if (promptMode === 'first_light' && parsed && partieId) {
					// Traiter comme un light normal
					await processLightMode(supabase, partieId, parsed, currentCycle);

					// Marquer l'événement d'arrivée comme réalisé
					await marquerArriveeRealisee(supabase, partieId);

					// Construire l'état client
					const stateForClient = await buildClientStateFromLight(
						supabase,
						partieId,
						parsed,
						currentCycle
					);

					await sseWriter.sendDone(displayText, stateForClient);

					// Sauvegarder le premier message avec action spéciale
					const lieu = parsed?.lieu_actuel || gameState?.partie?.lieu_actuel;
					const pnjsPresents = parsed?.pnjs_presents || [];
					await saveMessages(
						supabase,
						partieId,
						'__ARRIVEE__', // Action spéciale pour le premier message
						displayText,
						currentCycle,
						lieu,
						pnjsPresents
					);

					// Extraction background
					extractionBackground(supabase, partieId, displayText, parsed, currentCycle)
						.catch(err => console.error('[BG] Erreur extraction:', err));

					await sseWriter.sendSaved();
					return;
				}

				// =============================================================
				// MODE LIGHT NORMAL
				// =============================================================
				if (!isInitMode && parsed && partieId) {
					await processLightMode(supabase, partieId, parsed, currentCycle);

					const stateForClient = await buildClientStateFromLight(
						supabase,
						partieId,
						parsed,
						currentCycle
					);

					await sseWriter.sendDone(displayText, stateForClient);

					// Sauvegarder les messages
					const lieu = parsed?.lieu_actuel || gameState?.partie?.lieu_actuel;
					const pnjsPresents = parsed?.pnjs_presents || [];
					await saveMessages(supabase, partieId, message, displayText, currentCycle, lieu, pnjsPresents);

					// Extraction background
					extractionBackground(supabase, partieId, displayText, parsed, currentCycle)
						.catch(err => console.error('[BG] Erreur extraction:', err));

					await sseWriter.sendSaved();
				}
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

async function saveMessages(supabase, partieId, userMessage, assistantMessage, cycle, lieu, pnjsPresents) {
	const snapshot = await createStateSnapshot(supabase, partieId);

	await supabase.from('chat_messages').insert([
		{
			partie_id: partieId,
			role: 'user',
			content: userMessage,
			cycle,
			lieu,
			pnjs_presents: pnjsPresents || [],
			state_snapshot: snapshot
		},
		{
			partie_id: partieId,
			role: 'assistant',
			content: assistantMessage,
			cycle,
			lieu,
			pnjs_presents: pnjsPresents || [],
			state_snapshot: null
		}
	]);
}
