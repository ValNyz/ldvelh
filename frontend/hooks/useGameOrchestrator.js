'use client';

import { useState, useCallback, useRef } from 'react';
import { useStreaming } from './useStreaming';
import { stateApi } from '../lib/api';
import { invocationFromState, toInvocationData, withPendingPlayerMessage } from '../lib/game/pendingRoll.mjs';
import { paramsFromServer } from '../lib/game/wizardParams.mjs';
import { buildChatPayload } from '../lib/game/chatRequest.mjs';
import { findLastUserMessage } from '../lib/game/chatHistory.mjs';
import {
	TURN_KIND, startLiveTurn, withTurnEvent, turnActivity, reopenTurn, withChunk, withAnswer,
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
	}, [gs]);

	// =========================================================================
	// LIVE TURNS (#143)
	// =========================================================================

	// Leaving a game cuts nothing: its /chat stream runs on, its events update its live turn
	// (lib/game/liveTurn.mjs) and reach the screen only while that game is open.
	// The open game, set synchronously (stream events may come before the next render).
	const openGameRef = useRef(null);
	// gameId -> { turn }: the stream running for that game (or its failure not seen yet)
	const turnsRef = useRef(new Map());

	const showGame = useCallback((id) => {
		openGameRef.current = id;
		gs.setGameId(id);
	}, [gs]);

	// Turn flags of the open game (lib/game/liveTurn.mjs turnActivity).
	const showTurnActivity = useCallback((activity) => {
		sendingRef.current = activity.sending;
		gs.setLoading(activity.loading);
		gs.setSaving(activity.saving);
	}, [gs]);

	// The world generation is done: its world and state on screen.
	const showWorldReady = useCallback((worldInfo, gameState) => {
		phase.setDirectorStatus('done');
		phase.setWorldData(worldInfo);
		phase.setGamePhase(phase.GAME_PHASE.WORLD_READY);
		if (worldInfo.world?.name) gs.setGameName(worldInfo.world.name);
		gs.setGameState(gameState);
	}, [gs, phase]);

	// Callbacks of the stream of `live`: each event updates the live turn first (what it
	// carried included, to show it again on reopen), then the screen only when the turn's
	// game is the open one.
	const turnCallbacks = useCallback((live) => {
		const { gameId, kind } = live.turn;
		const shown = () => openGameRef.current === gameId && turnsRef.current.get(gameId) === live;
		// Event `type` updates the turn (and, with `edit`, the chat when shown); true when shown.
		const apply = (type, changes = {}) => {
			live.turn = withTurnEvent(live.turn, type, changes);
			const visible = shown();
			if (visible && changes.edit) gs.setMessages(changes.edit);
			return visible;
		};
		// What depends on the saved turn; bound to this game (run again on a late reopen).
		live.refreshAfterSave = () => {
			tooltips.refresh();
			world.refresh();
		};

		return {
			onRollResult: (roll) => {
				// Attached to the answer on its first chunk
				live.turn = { ...live.turn, roll };
			},
			onChunk: (content) => {
				const { roll } = live.turn;
				apply('chunk', { roll: null, edit: messages => withChunk(messages, content, roll) });
			},
			onProgress: (rawJson) => {
				if (apply('progress', { progress: rawJson })) phase.setWorldGenProgress(rawJson);
			},
			onStatus: (data) => {
				if (data?.step !== 'director') return;
				const director = { status: 'running', label: data.label || 'Scénario' };
				if (!apply('status', { director })) return;
				phase.setDirectorStatus(director.status);
				phase.setDirectorLabel(director.label);
			},
			onDone: (displayText, data) => {
				// INIT mode: world_info present means world was just created
				if (data?.world_info) {
					const worldInfo = {
						...data.world_info,
						generation_cost: data?.meta?.narration_cost || null,
					};
					if (!apply('done', { world: worldInfo, gameState: data.game_state })) return;
					endTurn({ saving: true }); // until 'saved'
					showWorldReady(worldInfo, data.game_state);
					return;
				}

				// LIGHT mode: display final narrative, with the ids the turn was saved with (#55)
				const edit = messages => withAnswer(messages, displayText, data);
				if (!apply('done', { edit, gameState: data?.game_state ?? null })) return;
				endTurn({ saving: true }); // until 'saved'
				if (data?.game_state) gs.setGameState(data.game_state);
				// The arrival scene is over: playing, unless the player went elsewhere (Paramètres).
				if (kind === TURN_KIND.ARRIVAL) {
					const { STARTING_ADVENTURE, PLAYING } = phase.GAME_PHASE;
					phase.setGamePhase(current => (current === STARTING_ADVENTURE ? PLAYING : current));
				}
			},
			onSaved: () => {
				if (!apply('saved')) return;
				gs.setSaving(false);
				live.refreshAfterSave();
			},
			onSaveUnconfirmed: () => {
				if (!apply('save_unconfirmed', { warning: MESSAGES.SAVE_UNCONFIRMED })) return;
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
				if (apply('warning', { warning: message })) gs.setWarning(message);
			},
			onError: (err, details, meta = {}) => {
				// Missing flag (client-side errors) means recoverable; the server says false when replaying would not help.
				const error = { message: err, details, recoverable: meta.recoverable !== false, code: meta.code };
				if (!apply('error', { error })) {
					// Not seen: kept after the stream ends, for the reopened game to report it.
					live.unseenError = true;
					return;
				}
				endTurn();
				gs.setError(error);
			},
		};
	}, [gs, phase, tooltips, world, endTurn, showWorldReady]);

	const { startStream, cancel } = useStreaming();

	// The live turn of `gameId` is not over (a second one would cut it).
	const isTurnRunning = useCallback((gameId) => turnActivity(turnsRef.current.get(gameId)?.turn).loading, []);

	// The only /chat call: every body is built by buildChatPayload (#55). The live turn of
	// `gameId` is a `kind` turn showing `playerMessage` (none for the protocol turns).
	const sendChat = useCallback(async (extra, { gameId = gs.gameId, kind = TURN_KIND.ACTION, playerMessage = null } = {}) => {
		const live = { turn: startLiveTurn(gameId, { kind, playerMessage }) };
		turnsRef.current.set(gameId, live);
		try {
			return await startStream('/chat', buildChatPayload({ gameId, preferences }, extra), {
				key: gameId,
				callbacks: turnCallbacks(live),
			});
		} finally {
			if (turnsRef.current.get(gameId) === live && !live.unseenError) turnsRef.current.delete(gameId);
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
		}, { gameId: id, kind: TURN_KIND.INIT });
	}, [sendChat, gs, phase]);

	/** Retry the world generation of the open game (after a failure, or on reopening it). */
	const handleRetryWorld = useCallback((params = null) => {
		if (gs.gameId && !isTurnRunning(gs.gameId)) generateWorld(gs.gameId, params);
	}, [gs.gameId, generateWorld, isTurnRunning]);

	const handleStartAdventure = useCallback(async () => {
		if (isTurnRunning(gs.gameId)) return;
		phase.setGamePhase(phase.GAME_PHASE.STARTING_ADVENTURE);
		gs.setLoading(true);
		gs.setError(null);
		gs.setWarning(null);
		gs.setMessages([]);

		await sendChat({ message: PROTOCOL.ARRIVAL_TOKEN }, { kind: TURN_KIND.ARRIVAL });
	}, [sendChat, gs, phase, isTurnRunning]);

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
			// The turn still running in this game (left during it) is shown again as if the
			// player had never left, and what it reported meanwhile comes back (#143).
			const reopened = reopenTurn(savedMessages, live?.turn, { worldCreated: Boolean(data.state?.world_created) });
			gs.setMessages(reopened.messages);
			setLastUserMessage(reopened.action || pending?.player_message || '');
			showTurnActivity(reopened.activity);
			if (reopened.gameState) gs.setGameState(reopened.gameState);
			if (reopened.warning) gs.setWarning(reopened.warning);
			if (reopened.error) gs.setError(reopened.error);
			if (reopened.refresh) live.refreshAfterSave();
			if (live?.unseenError && turnsRef.current.get(id) === live) turnsRef.current.delete(id); // reported now

			if (reopened.generating) {
				const { progress, director } = reopened.generating;
				phase.setWorldGenProgress(progress);
				phase.setDirectorStatus(director?.status ?? null);
				phase.setDirectorLabel(director?.label ?? null);
				phase.setGamePhase(phase.GAME_PHASE.GENERATING_WORLD);
			} else if (reopened.world) {
				showWorldReady(reopened.world.info, reopened.world.gameState);
			} else if (reopened.starting) {
				phase.setGamePhase(phase.GAME_PHASE.STARTING_ADVENTURE);
			} else if (reopened.messages.length > 0) {
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
	}, [games, gs, phase, showGame, showTurnActivity, showWorldReady]);

	// True once the game is deleted.
	const handleDeleteGame = useCallback(async (id) => {
		try {
			await games.deleteGame(id);
			// Nothing left to commit the turn into: its stream is the one worth cutting.
			cancel(id);
			turnsRef.current.delete(id);
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
	}, [games, gs, phase, cancel]);

	const handleRenameGame = useCallback(async (newName) => {
		if (!gs.gameId) return;
		await games.renameGame(gs.gameId, newName);
		gs.setGameName(newName);
		await games.loadGames();
	}, [games, gs]);

	// Leaving cuts nothing: the game's stream runs on in the background, its events no
	// longer reach the screen (#143).
	const handleQuit = useCallback(() => {
		openGameRef.current = null;
		setStoredInitParams(null);
		setInvocationData(null);
		gs.resetGame();
		showTurnActivity(turnActivity(null));
		phase.resetPhase();
		games.loadGames();
	}, [gs, phase, games, showTurnActivity]);

	// =========================================================================
	// MESSAGE HANDLERS
	// =========================================================================

	const handleSendMessage = useCallback(async (content) => {
		if (!gs.gameId || sendingRef.current) return;
		sendingRef.current = true;

		setLastUserMessage(content);
		gs.setMessages(prev => [...prev, { role: 'user', content }]);
		gs.setWarning(null);
		gs.setLoading(true);
		gs.setSaving(true);

		await sendChat({ message: content }, { playerMessage: content });
	}, [sendChat, gs]);

	const handleCancel = useCallback(() => {
		const live = turnsRef.current.get(gs.gameId);
		if (cancel(gs.gameId)) {
			if (live) live.turn = withTurnEvent(live.turn, 'cancel');
			endTurn();
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.streaming) {
					return [...prev.slice(0, -1), {
						...last,
						streaming: false,
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
