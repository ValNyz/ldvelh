'use client';

import { useState, useCallback, useRef } from 'react';
import { useStreaming } from './useStreaming';
import { stateApi } from '../lib/api';
import { invocationFromState, toInvocationData, withPendingPlayerMessage } from '../lib/game/pendingRoll.mjs';
import { paramsFromServer } from '../lib/game/wizardParams.mjs';
import { buildChatPayload } from '../lib/game/chatRequest.mjs';
import { findLastUserMessage } from '../lib/game/chatHistory.mjs';
import {
	startLiveTurn, nextTurnStatus, turnActivity, withChunk, withExtracting, withAnswer, withLiveTurn,
} from '../lib/game/liveTurn.mjs';

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

	// The turn is over (answer, roll to invoke, error or cancel): the player can send again.
	const endTurn = useCallback(({ saving = false } = {}) => {
		sendingRef.current = false;
		gs.setLoading(false);
		gs.setSaving(saving);
		setIsExtracting(false);
	}, [gs]);

	// =========================================================================
	// LIVE TURNS (#143)
	// =========================================================================

	// Leaving a game cuts nothing: its /chat stream runs on, its events update its live turn
	// (lib/game/liveTurn.mjs) and reach the screen only while that game is open.
	// The open game, set synchronously (stream events may come before the next render).
	const openGameRef = useRef(null);
	const turnsRef = useRef(new Map()); // gameId -> { turn }: the stream running for that game

	const showGame = useCallback((id) => {
		openGameRef.current = id;
		gs.setGameId(id);
	}, [gs]);

	// Turn flags of the open game, from its live turn (none: the player can send).
	const showTurnActivity = useCallback((turn) => {
		const activity = turnActivity(turn);
		sendingRef.current = activity.sending;
		gs.setLoading(activity.loading);
		gs.setSaving(activity.saving);
		setIsExtracting(activity.extracting);
	}, [gs]);

	// Callbacks of the stream of `live`: each event updates the live turn first, then the
	// screen only when the turn's game is the open one.
	const turnCallbacks = useCallback((live) => {
		const { gameId } = live.turn;
		const shown = () => openGameRef.current === gameId && turnsRef.current.get(gameId) === live;
		// Event `type` moves the turn status and, with `edit`, its messages (and the chat when shown).
		const apply = (type, edit = null) => {
			const { turn } = live;
			live.turn = { ...turn, status: nextTurnStatus(turn.status, type), messages: edit ? edit(turn.messages) : turn.messages };
			const visible = shown();
			if (visible && edit) gs.setMessages(edit);
			return visible;
		};

		return {
			onRollResult: (roll) => {
				// Attached to the answer on its first chunk
				live.turn = { ...live.turn, roll };
			},
			onChunk: (content) => {
				const { roll } = live.turn;
				live.turn = { ...live.turn, roll: null };
				apply('chunk', messages => withChunk(messages, content, roll));
			},
			onProgress: (rawJson) => {
				if (shown()) phase.setWorldGenProgress(rawJson);
			},
			onStatus: (data) => {
				if (shown() && data?.step === 'director') {
					phase.setDirectorStatus('running');
					phase.setDirectorLabel(data.label || 'Scénario');
				}
			},
			onExtracting: (displayText) => {
				if (apply('extracting', messages => withExtracting(messages, displayText))) setIsExtracting(true);
			},
			onDone: (displayText, data) => {
				// INIT mode: world_info present means world was just created
				if (data?.world_info) {
					if (!apply('done')) return;
					endTurn({ saving: true }); // until 'saved'
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
				if (!apply('done', messages => withAnswer(messages, displayText, data))) return;
				endTurn({ saving: true }); // until 'saved'
				if (data?.game_state) gs.setGameState(data.game_state);

				if (phase.gamePhase === phase.GAME_PHASE.STARTING_ADVENTURE) {
					phase.setGamePhase(phase.GAME_PHASE.PLAYING);
				}
			},
			onSaved: () => {
				if (!apply('saved')) return;
				gs.setSaving(false);
				tooltips.refresh();
				world.refresh();
			},
			onSaveUnconfirmed: () => {
				if (!apply('save_unconfirmed')) return;
				gs.setSaving(false);
				gs.setWarning(MESSAGES.SAVE_UNCONFIRMED);
			},
			onRollPending: (data) => {
				// Fate Core: roll failed, player can invoke aspects. Not saved: a reopened game
				// gets it back from its state (pending_roll).
				if (!apply('roll_pending')) return;
				endTurn();
				// The roll may belong to an earlier action still waiting: show that one (#32).
				if (data.player_message) {
					gs.setMessages(prev => withPendingPlayerMessage(prev, data.player_message));
					setLastUserMessage(data.player_message);
				}
				setInvocationData(toInvocationData(data));
			},
			onWarning: (message) => {
				if (shown()) gs.setWarning(message);
			},
			onError: (err, details, meta = {}) => {
				if (!apply('error')) return;
				endTurn();
				// Missing flag (client-side errors) means recoverable; the server says false when replaying would not help.
				gs.setError({ message: err, details, recoverable: meta.recoverable !== false, code: meta.code });
			},
		};
	}, [gs, phase, tooltips, world, endTurn]);

	const { startStream, cancel } = useStreaming();

	// The only /chat call: every body is built by buildChatPayload (#55). The turn of
	// `gameId` shows `playerMessage` (none for protocol tokens) when that game is reopened.
	const sendChat = useCallback(async (extra, { gameId = gs.gameId, playerMessage = null } = {}) => {
		const live = { turn: startLiveTurn(gameId, playerMessage) };
		turnsRef.current.set(gameId, live);
		try {
			return await startStream('/chat', buildChatPayload({ gameId, preferences }, extra), {
				key: gameId,
				callbacks: turnCallbacks(live),
			});
		} finally {
			if (turnsRef.current.get(gameId) === live) turnsRef.current.delete(gameId);
		}
	}, [startStream, turnCallbacks, gs.gameId, preferences]);

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
		}, { gameId: id });
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
			showGame(id);
			if (!gameId) gs.setGameName(MESSAGES.NEW_GAME_NAME);

			await games.loadGames();
			gs.setLoading(false);
			await generateWorld(id, params);
		} catch (e) {
			gs.setError({ message: e.message });
			gs.setLoading(false);
		}
	}, [games, gs, generateWorld, showGame]);

	const handleWizardCancel = useCallback(() => {
		phase.setGamePhase(phase.GAME_PHASE.LIST);
	}, [phase]);

	const handleLoadGame = useCallback(async (id) => {
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		// Taken before the load: the turn may end while the game loads (#143).
		const live = turnsRef.current.get(id);
		try {
			const data = await games.loadGame(id);
			showGame(id);
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
			const savedMessages = pending?.player_message
				? [...loadedMessages, { role: 'user', content: pending.player_message }]
				: loadedMessages;
			// The turn still running in this game (left during its narration) goes on at the
			// end of the chat, unless the loaded history already holds it (#143).
			const turn = live?.turn;
			const shownMessages = withLiveTurn(savedMessages, turn);
			const liveShown = shownMessages !== savedMessages;
			gs.setMessages(shownMessages);
			const liveAction = liveShown ? turn.messages.find(m => m.role === 'user')?.content : null;
			setLastUserMessage(liveAction || pending?.player_message || '');
			showTurnActivity(liveShown ? turn : null);

			if (shownMessages.length > 0) {
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
			gs.setLoading(false);
		}
	}, [games, gs, phase, showGame, showTurnActivity]);

	// True once the game is deleted.
	const handleDeleteGame = useCallback(async (id) => {
		try {
			await games.deleteGame(id);
			if (gs.gameId === id) {
				openGameRef.current = null;
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

	// Leaving cuts nothing: the game's stream runs on in the background, its events no
	// longer reach the screen (#143).
	const handleQuit = useCallback(() => {
		openGameRef.current = null;
		setStoredInitParams(null);
		setInvocationData(null);
		gs.resetGame();
		showTurnActivity(null);
		phase.resetPhase();
		games.loadGames();
	}, [gs, phase, games, showTurnActivity]);

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

		await sendChat({ message: content }, { playerMessage: content });
	}, [gs.gameId, isExtracting, sendChat, gs]);

	const handleCancel = useCallback(() => {
		const live = turnsRef.current.get(gs.gameId);
		if (cancel(gs.gameId)) {
			if (live) live.turn = { ...live.turn, status: nextTurnStatus(live.turn.status, 'cancel') };
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
		}, { playerMessage: lastUserMessage });
	}, [invocationData, gs, lastUserMessage, sendChat]);

	const handleInvoke = useCallback((selectedAspects) => resumeRoll(selectedAspects), [resumeRoll]);
	const handleSkipInvocation = useCallback(() => resumeRoll([]), [resumeRoll]);

	// =========================================================================
	// RETURN
	// =========================================================================

	return {
		// State
		isExtracting,
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
