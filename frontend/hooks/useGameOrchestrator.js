'use client';

import { useState, useCallback, useRef } from 'react';
import { useStreaming } from './useStreaming';
import { stateApi } from '../lib/api';
import { invocationFromState, toInvocationData, withPendingPlayerMessage } from '../lib/game/pendingRoll.mjs';
import { paramsFromServer } from '../lib/game/wizardParams.mjs';
import { buildChatPayload } from '../lib/game/chatRequest.mjs';
import { findLastUserMessage, withTurnIds } from '../lib/game/chatHistory.mjs';

// Game content constants (French — the game is in French)
const MESSAGES = {
	NEW_GAME_NAME: 'Nouvelle partie',
	CANCELLED_SUFFIX: '\n\n*(Annulé)*',
	SAVE_UNCONFIRMED: "La sauvegarde de ce tour n'a pas été confirmée : recharge la partie si le dernier message manque.",
	ROLLBACK_FAILED: 'Retour en arrière impossible.',
	MESSAGE_NOT_SAVED: "Ce message n'est pas encore enregistré : recharge la partie pour le reprendre.",
};

// Protocol tokens for special messages
const PROTOCOL = {
	INIT_TOKEN: '__INIT__',
	ARRIVAL_TOKEN: '__ARRIVEE__',
};

// ============================================================================
// GAME ORCHESTRATOR HOOK
// ============================================================================

/**
 * Encapsulates all game business logic: streaming callbacks,
 * game CRUD handlers, message handlers, world generation.
 *
 * @param {Object} deps - Hook dependencies
 * @param {Object} deps.gameState - from useGameState()
 * @param {Object} deps.games - from useGames()
 * @param {Object} deps.phase - from useGamePhase()
 * @param {Object} deps.tooltips - { refresh }
 * @param {Object} deps.world - { refresh }
 * @param {Object} deps.preferences - { activeProvider }
 */
export function useGameOrchestrator({ gameState: gs, games, phase, tooltips, world, preferences }) {
	const [isExtracting, setIsExtracting] = useState(false);
	const [editingIndex, setEditingIndex] = useState(null);
	const [lastUserMessage, setLastUserMessage] = useState('');
	const [invocationData, setInvocationData] = useState(null);
	// Wizard parameters the server stored for the open game while its world is not created (#88).
	const [storedInitParams, setStoredInitParams] = useState(null);
	const sendingRef = useRef(false);
	const pendingRollRef = useRef(null);

	// The turn is over (answer, roll to invoke, error or cancel): the player can send again.
	const endTurn = useCallback(({ saving = false } = {}) => {
		sendingRef.current = false;
		gs.setLoading(false);
		gs.setSaving(saving);
		setIsExtracting(false);
	}, [gs]);

	// =========================================================================
	// STREAMING CALLBACKS
	// =========================================================================

	const { startStream, cancel, isStreaming } = useStreaming({
		onRollResult: (roll) => {
			// Store roll data in ref — will be attached to the assistant message on first chunk
			pendingRollRef.current = roll;
		},
		onChunk: (content) => {
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant' && last.streaming) {
					return [...prev.slice(0, -1), { ...last, content: last.content + content }];
				}
				// First chunk — attach any pending roll result
				const roll = pendingRollRef.current;
				pendingRollRef.current = null;
				return [...prev, { role: 'assistant', content, streaming: true, ...(roll ? { roll } : {}) }];
			});
		},
		onProgress: (rawJson) => {
			phase.setWorldGenProgress(rawJson);
		},
		onStatus: (data) => {
			if (data?.step === 'director') {
				phase.setDirectorStatus('running');
				phase.setDirectorLabel(data.label || 'Scénario');
			}
		},
		onExtracting: (displayText) => {
			setIsExtracting(true);
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return [...prev.slice(0, -1), {
						...last,
						content: displayText || last.content,
						streaming: false,
						extracting: true
					}];
				}
				return prev;
			});
		},
		onDone: (displayText, data) => {
			endTurn({ saving: true }); // until 'saved'

			// INIT mode: world_info present means world was just created
			if (data?.world_info) {
				phase.setDirectorStatus('done');
				const worldInfo = {
					...data.world_info,
					generation_cost: data?.meta?.narration_cost || null,
				};
				phase.setWorldData(worldInfo);
				phase.setGamePhase(phase.GAME_PHASE.WORLD_READY);
				if (data.world_info.world?.name) gs.setGameName(data.world_info.world.name);
				gs.setGameState(data.game_state);
				return;
			}

			// LIGHT mode: display final narrative, with the ids the turn was saved with (#55)
			const gameData = data?.game_state?.game;
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return withTurnIds([...prev.slice(0, -1), {
						...last,
						content: displayText || last.content,
						streaming: false,
						extracting: false,
						cost: data?.meta?.narration_cost || null,
						cycle: gameData?.current_cycle || null,
						time: gameData?.time || null,
						game_date: gameData?.game_date || null,
						location: gameData?.current_location || null,
					}], data?.meta);
				}
				return prev;
			});

			if (data?.game_state) gs.setGameState(data.game_state);

			if (phase.gamePhase === phase.GAME_PHASE.STARTING_ADVENTURE) {
				phase.setGamePhase(phase.GAME_PHASE.PLAYING);
			}
		},
		onSaved: () => {
			gs.setSaving(false);
			tooltips.refresh();
			world.refresh();
		},
		onSaveUnconfirmed: () => {
			gs.setSaving(false);
			gs.setWarning(MESSAGES.SAVE_UNCONFIRMED);
		},
		onRollPending: (data) => {
			// Fate Core: roll failed, player can invoke aspects
			endTurn();
			// The roll may belong to an earlier action still waiting: show that one (#32).
			if (data.player_message) {
				gs.setMessages(prev => withPendingPlayerMessage(prev, data.player_message));
				setLastUserMessage(data.player_message);
			}
			setInvocationData(toInvocationData(data));
		},
		onWarning: (message) => {
			gs.setWarning(message);
		},
		onError: (err, details, meta = {}) => {
			endTurn();
			// Missing flag (client-side errors) means recoverable; the server says false when replaying would not help.
			gs.setError({ message: err, details, recoverable: meta.recoverable !== false, code: meta.code });
		}
	});

	// The only /chat call: every body is built by buildChatPayload (#55).
	const sendChat = useCallback((extra, gameId = gs.gameId) => (
		startStream('/chat', buildChatPayload({ gameId, preferences }, extra))
	), [startStream, gs.gameId, preferences]);

	// =========================================================================
	// WORLD GENERATION
	// =========================================================================

	// __INIT__ of `id`: with the wizard parameters, or without (the server reuses the
	// ones stored at the first __INIT__, #88).
	const generateWorld = useCallback(async (id, params = null) => {
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		phase.setWorldGenProgress('');
		phase.setGamePhase(phase.GAME_PHASE.GENERATING_WORLD);

		await sendChat({
			message: PROTOCOL.INIT_TOKEN,
			...(params ? {
				engine: params.engine,
				world_config: params.worldConfig,
				character_data: params.characterData,
				manual_entities: params.manualEntities,
			} : {}),
		}, id);
	}, [sendChat, gs, phase]);

	/** Retry the world generation of the open game (after a failure, or on reopening it). */
	const handleRetryWorld = useCallback((params = null) => {
		if (gs.gameId) generateWorld(gs.gameId, params);
	}, [gs.gameId, generateWorld]);

	const handleStartAdventure = useCallback(async () => {
		phase.setGamePhase(phase.GAME_PHASE.STARTING_ADVENTURE);
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		gs.setMessages([]);

		await sendChat({ message: PROTOCOL.ARRIVAL_TOKEN });
	}, [sendChat, gs, phase]);

	// =========================================================================
	// GAME CRUD HANDLERS
	// =========================================================================

	const handleNewGame = useCallback(async () => {
		gs.setError(null);
		gs.setWarning(null);
		gs.setMessages([]);
		gs.replaceGameState(null);
		phase.setWorldGenProgress('');
		phase.setWorldData(null);
		setStoredInitParams(null); // the loaded game's server parameters belong to that game
		phase.setGamePhase(phase.GAME_PHASE.WIZARD);
	}, [gs, phase]);

	// gameId: the wizard edited the parameters of an existing game (world not created yet).
	// onCreated(id): called once the game exists (e.g. to attach the wizard draft to it).
	const handleWizardComplete = useCallback(async (params, { gameId = null, onCreated } = {}) => {
		setStoredInitParams(null); // never fall back on another game's parameters
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		try {
			const id = gameId || await games.createGame(params.engine);
			onCreated?.(id);
			gs.setGameId(id);
			if (!gameId) gs.setGameName(MESSAGES.NEW_GAME_NAME);

			await games.loadGames();
			gs.setLoading(false);
			await generateWorld(id, params);
		} catch (e) {
			gs.setError({ message: e.message });
			gs.setLoading(false);
		}
	}, [games, gs, generateWorld]);

	const handleWizardCancel = useCallback(() => {
		phase.setGamePhase(phase.GAME_PHASE.LIST);
	}, [phase]);

	const handleLoadGame = useCallback(async (id) => {
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		try {
			const data = await games.loadGame(id);
			gs.setGameId(id);
			gs.setGameName(data.state?.game?.name || MESSAGES.NEW_GAME_NAME);
			setStoredInitParams(paramsFromServer(data.init_params));

			if (data.state) {
				gs.replaceGameState(data.state);
			}
			// A Fate roll still waiting for an invocation: show its modal again, and the
			// action it belongs to (not saved yet) at the end of the chat (#32).
			const pending = data.state?.pending_roll;
			setInvocationData(invocationFromState(data.state));

			const loadedMessages = data.messages || [];
			if (pending?.player_message) {
				gs.setMessages([...loadedMessages, { role: 'user', content: pending.player_message }]);
				setLastUserMessage(pending.player_message);
			} else {
				gs.setMessages(loadedMessages);
				setLastUserMessage('');
			}

			if (loadedMessages.length > 0) {
				phase.setGamePhase(phase.GAME_PHASE.PLAYING);
			} else if (data.state?.world_created) {
				if (data.world_info) {
					phase.setWorldData(data.world_info);
				}
				phase.setGamePhase(phase.GAME_PHASE.WORLD_READY);
			} else {
				// Not generated (failed, or left during the generation): the player chooses
				// to retry or to edit the parameters first (#88).
				phase.setGamePhase(phase.GAME_PHASE.WORLD_PENDING);
			}
		} catch (e) {
			gs.setError({ message: e.message });
		} finally {
			gs.setLoading(false);
		}
	}, [games, gs, phase]);

	// True once the game is deleted.
	const handleDeleteGame = useCallback(async (id) => {
		try {
			await games.deleteGame(id);
			if (gs.gameId === id) {
				gs.resetGame();
				phase.resetPhase();
			}
			await games.loadGames();
			return true;
		} catch (e) {
			gs.setError({ message: e.message });
			return false;
		}
	}, [games, gs, phase]);

	const handleRenameGame = useCallback(async (newName) => {
		if (!gs.gameId) return;
		await games.renameGame(gs.gameId, newName);
		gs.setGameName(newName);
		await games.loadGames();
	}, [gs.gameId, games, gs]);

	const handleQuit = useCallback(() => {
		setStoredInitParams(null);
		gs.resetGame();
		phase.resetPhase();
		games.loadGames();
	}, [gs, phase, games]);

	// =========================================================================
	// MESSAGE HANDLERS
	// =========================================================================

	const handleSendMessage = useCallback(async (content) => {
		if (!gs.gameId || sendingRef.current || isExtracting) return;
		sendingRef.current = true;

		setLastUserMessage(content);
		gs.setMessages(prev => [...prev, { role: 'user', content }]);
		gs.setWarning(null);
		gs.setLoading(true);
		gs.setSaving(true);

		await sendChat({ message: content });
	}, [gs.gameId, isExtracting, sendChat, gs]);

	const handleCancel = useCallback(() => {
		if (cancel()) {
			endTurn();
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.streaming || last?.extracting) {
					return [...prev.slice(0, -1), {
						...last,
						streaming: false,
						extracting: false,
						content: last.content + MESSAGES.CANCELLED_SUFFIX
					}];
				}
				return prev;
			});
		}
	}, [cancel, endTurn, gs]);

	// Rollback to `messageId` and show its result; false when refused (the error is shown).
	const rollbackTo = useCallback(async (messageId) => {
		let result;
		try {
			result = await stateApi.rollback(gs.gameId, messageId);
		} catch (e) {
			console.warn('Rollback failed:', e);
			// Not recoverable: "Réessayer" would resend the last action, not the rollback.
			gs.setError({ message: e.message || MESSAGES.ROLLBACK_FAILED, recoverable: false });
			return false;
		}
		gs.setMessages(result.messages || []);
		if (result.state) gs.replaceGameState(result.state);
		// The rollback expires any pending roll: its modal must not come back (#80).
		setInvocationData(invocationFromState(result.state));
		return true;
	}, [gs]);

	const handleEdit = useCallback((index) => {
		setEditingIndex(index);
	}, []);

	const handleCancelEdit = useCallback(() => {
		setEditingIndex(null);
	}, []);

	// Edit / resend / regenerate: rollback to the action `messageId`, then send `content` in
	// its place. A message without id (not saved yet) is refused with an error (#55).
	const rollbackThenSend = useCallback(async (messageId, content) => {
		if (!messageId) {
			gs.setError({ message: MESSAGES.MESSAGE_NOT_SAVED, recoverable: false });
			return;
		}
		if (!await rollbackTo(messageId)) return;

		setEditingIndex(null);
		await handleSendMessage(content);
	}, [gs, rollbackTo, handleSendMessage]);

	const handleSubmitEdit = useCallback(async (content) => {
		const targetMsg = editingIndex === null ? null : gs.messages[editingIndex];
		if (targetMsg) await rollbackThenSend(targetMsg.id, content);
	}, [editingIndex, gs.messages, rollbackThenSend]);

	const handleResend = useCallback(async (index) => {
		const msg = gs.messages[index];
		if (msg?.role === 'user') await rollbackThenSend(msg.id, msg.content);
	}, [gs.messages, rollbackThenSend]);

	// Answer the last action again: works on a just loaded game too (no prior send needed).
	const handleRegenerate = useCallback(async () => {
		const msg = findLastUserMessage(gs.messages);
		if (msg) await rollbackThenSend(msg.id, msg.content);
	}, [gs.messages, rollbackThenSend]);

	const handleRetry = useCallback(() => {
		if (lastUserMessage) handleSendMessage(lastUserMessage);
	}, [lastUserMessage, handleSendMessage]);

	// =========================================================================
	// ASPECT INVOCATION (Fate Core)
	// =========================================================================

	// Resume the pending roll with the invoked aspects (none: the failure stands).
	const resumeRoll = useCallback(async (invokedAspects) => {
		if (!invocationData || !gs.gameId) return;

		setInvocationData(null);
		gs.setLoading(true);
		gs.setSaving(true);
		sendingRef.current = true;

		await sendChat({
			message: lastUserMessage,
			roll_id: invocationData.rollId,
			invoked_aspects: invokedAspects,
		});
	}, [invocationData, gs, lastUserMessage, sendChat]);

	const handleInvoke = useCallback((selectedAspects) => resumeRoll(selectedAspects), [resumeRoll]);
	const handleSkipInvocation = useCallback(() => resumeRoll([]), [resumeRoll]);

	// =========================================================================
	// RETURN
	// =========================================================================

	return {
		// State
		isExtracting,
		isStreaming,
		editingIndex,
		invocationData,
		storedInitParams,

		// Game handlers
		handleNewGame,
		handleLoadGame,
		handleDeleteGame,
		handleRenameGame,
		handleQuit,

		// Message handlers
		handleSendMessage,
		handleCancel,
		handleEdit,
		handleCancelEdit,
		handleSubmitEdit,
		handleResend,
		handleRegenerate,
		handleRetry,

		// Aspect invocation (Fate Core)
		handleInvoke,
		handleSkipInvocation,

		// World generation
		handleStartAdventure,
		handleRetryWorld,
		handleWizardComplete,
		handleWizardCancel,
	};
}
