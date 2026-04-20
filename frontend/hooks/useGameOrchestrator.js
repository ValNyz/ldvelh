'use client';

import { useState, useCallback, useRef } from 'react';
import { useStreaming } from './useStreaming';
import { stateApi } from '../lib/api';

// Game content constants (French — the game is in French)
const MESSAGES = {
	NEW_GAME_NAME: 'Nouvelle partie',
	CANCELLED_SUFFIX: '\n\n*(Annulé)*',
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
	const sendingRef = useRef(false);
	const pendingRollRef = useRef(null);

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
			sendingRef.current = false;
			gs.setLoading(false);
			gs.setSaving(true);
			setIsExtracting(false);

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

			// LIGHT mode: display final narrative
			const gameData = data?.game_state?.game;
			gs.setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return [...prev.slice(0, -1), {
						...last,
						content: displayText || last.content,
						streaming: false,
						extracting: false,
						cost: data?.meta?.narration_cost || null,
						cycle: gameData?.current_cycle || null,
						time: gameData?.time || null,
						game_date: gameData?.game_date || null,
						location: gameData?.current_location || null,
					}];
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
		onRollPending: (data) => {
			// Fate Core: roll failed, player can invoke aspects
			sendingRef.current = false;
			gs.setLoading(false);
			gs.setSaving(false);
			setInvocationData({
				rollId: data.roll_id,
				roll: data.roll,
				aspects: data.aspects,
				fatePoints: data.fate_points,
			});
		},
		onError: (err, details) => {
			sendingRef.current = false;
			gs.setError({ message: err, details, recoverable: true });
			gs.setLoading(false);
			gs.setSaving(false);
			setIsExtracting(false);
		}
	});

	// =========================================================================
	// WORLD GENERATION
	// =========================================================================

	const generateWorld = useCallback(async (id) => {
		gs.setLoading(true);
		gs.setError(null);
		phase.setWorldGenProgress('');

		await startStream('/chat', {
			message: PROTOCOL.INIT_TOKEN,
			gameId: id,
			gameState: null,
			provider: preferences?.activeProvider || 'anthropic',
			model: preferences?.activeModel || null,
		});
	}, [startStream, gs, phase, preferences]);

	const handleStartAdventure = useCallback(async () => {
		phase.setGamePhase(phase.GAME_PHASE.STARTING_ADVENTURE);
		gs.setLoading(true);
		gs.setError(null);
		gs.setMessages([]);

		await startStream('/chat', {
			message: PROTOCOL.ARRIVAL_TOKEN,
			gameId: gs.gameId,
			gameState: gs.gameState,
			provider: preferences?.activeProvider || 'anthropic',
			model: preferences?.activeModel || null,
		});
	}, [gs.gameId, gs.gameState, startStream, gs, phase, preferences]);

	// =========================================================================
	// GAME CRUD HANDLERS
	// =========================================================================

	const handleNewGame = useCallback(async () => {
		gs.setError(null);
		gs.setMessages([]);
		gs.replaceGameState(null);
		phase.setWorldGenProgress('');
		phase.setWorldData(null);
		phase.setGamePhase(phase.GAME_PHASE.WIZARD);
	}, [gs, phase]);

	const handleWizardComplete = useCallback(async ({ engine, worldConfig, characterData, manualEntities }) => {
		gs.setLoading(true);
		gs.setError(null);
		try {
			const id = await games.createGame(engine);
			gs.setGameId(id);
			gs.setGameName(MESSAGES.NEW_GAME_NAME);

			await games.loadGames();
			phase.setGamePhase(phase.GAME_PHASE.GENERATING_WORLD);
			gs.setLoading(false);

			// Start world generation with engine params
			await startStream('/chat', {
				message: PROTOCOL.INIT_TOKEN,
				gameId: id,
				gameState: null,
				provider: preferences?.activeProvider || 'anthropic',
				model: preferences?.activeModel || null,
				engine,
				world_config: worldConfig,
				character_data: characterData,
				manual_entities: manualEntities,
			});
		} catch (e) {
			gs.setError({ message: e.message });
			gs.setLoading(false);
		}
	}, [games, gs, phase, startStream, preferences]);

	const handleWizardCancel = useCallback(() => {
		phase.setGamePhase(phase.GAME_PHASE.LIST);
	}, [phase]);

	const handleLoadGame = useCallback(async (id) => {
		gs.setLoading(true);
		gs.setError(null);
		try {
			const data = await games.loadGame(id);
			gs.setGameId(id);
			gs.setGameName(data.state?.game?.name || MESSAGES.NEW_GAME_NAME);

			if (data.state) {
				gs.replaceGameState(data.state);
			}

			const loadedMessages = data.messages || [];
			gs.setMessages(loadedMessages);

			if (loadedMessages.length > 0) {
				phase.setGamePhase(phase.GAME_PHASE.PLAYING);
			} else if (data.state?.world_created) {
				if (data.world_info) {
					phase.setWorldData(data.world_info);
				}
				phase.setGamePhase(phase.GAME_PHASE.WORLD_READY);
			} else {
				phase.setGamePhase(phase.GAME_PHASE.GENERATING_WORLD);
				gs.setLoading(false);
				generateWorld(id);
				return;
			}
		} catch (e) {
			gs.setError({ message: e.message });
		} finally {
			gs.setLoading(false);
		}
	}, [games, gs, phase, generateWorld]);

	const handleDeleteGame = useCallback(async (id) => {
		try {
			await games.deleteGame(id);
			if (gs.gameId === id) {
				gs.resetGame();
				phase.resetPhase();
			}
			await games.loadGames();
		} catch (e) {
			gs.setError({ message: e.message });
		}
	}, [games, gs, phase]);

	const handleRenameGame = useCallback(async (newName) => {
		if (!gs.gameId) return;
		await games.renameGame(gs.gameId, newName);
		gs.setGameName(newName);
		await games.loadGames();
	}, [gs.gameId, games, gs]);

	const handleQuit = useCallback(() => {
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
		gs.setLoading(true);
		gs.setSaving(true);

		await startStream('/chat', {
			gameId: gs.gameId,
			message: content,
			gameState: gs.gameState,
			provider: preferences?.activeProvider || 'anthropic',
			model: preferences?.activeModel || null,
		});
	}, [gs.gameId, gs.gameState, isExtracting, startStream, gs, preferences]);

	const handleCancel = useCallback(() => {
		if (cancel()) {
			sendingRef.current = false;
			gs.setLoading(false);
			gs.setSaving(false);
			setIsExtracting(false);
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
	}, [cancel, gs]);

	const handleEdit = useCallback((index) => {
		setEditingIndex(index);
	}, []);

	const handleCancelEdit = useCallback(() => {
		setEditingIndex(null);
	}, []);

	const handleSubmitEdit = useCallback(async (content) => {
		if (editingIndex === null) return;

		const targetMsg = gs.messages[editingIndex];
		if (!targetMsg?.id) return;

		let result;
		try {
			result = await stateApi.rollback(gs.gameId, targetMsg.id);
		} catch (e) {
			console.error('Rollback failed:', e);
			gs.setError({ message: 'Rollback failed: ' + e.message });
			return;
		}

		gs.setMessages(result.messages || []);
		if (result.state) gs.replaceGameState(result.state);
		setEditingIndex(null);

		await handleSendMessage(content);
	}, [editingIndex, gs.gameId, gs, handleSendMessage]);

	const handleResend = useCallback(async (index) => {
		const msg = gs.messages[index];
		if (!msg || msg.role !== 'user' || !msg.id) return;

		let result;
		try {
			result = await stateApi.rollback(gs.gameId, msg.id);
		} catch (e) {
			console.error('Rollback failed:', e);
			gs.setError({ message: 'Rollback failed: ' + e.message });
			return;
		}

		gs.setMessages(result.messages || []);
		if (result.state) gs.replaceGameState(result.state);
		await handleSendMessage(msg.content);
	}, [gs.messages, gs.gameId, gs, handleSendMessage]);

	const handleRegenerate = useCallback(async () => {
		if (!lastUserMessage) return;

		const lastUserIndex = gs.messages.length - 2;
		const lastUserMsg = gs.messages[lastUserIndex];
		if (!lastUserMsg || lastUserMsg.role !== 'user' || !lastUserMsg.id) return;

		let result;
		try {
			result = await stateApi.rollback(gs.gameId, lastUserMsg.id);
		} catch (e) {
			console.error('Rollback failed:', e);
			gs.setError({ message: 'Rollback failed: ' + e.message });
			return;
		}

		gs.setMessages(result.messages || []);
		if (result.state) gs.replaceGameState(result.state);

		await handleSendMessage(lastUserMessage);
	}, [lastUserMessage, gs.messages, gs.gameId, gs, handleSendMessage]);

	const handleRetry = useCallback(() => {
		if (lastUserMessage) handleSendMessage(lastUserMessage);
	}, [lastUserMessage, handleSendMessage]);

	// =========================================================================
	// ASPECT INVOCATION (Fate Core)
	// =========================================================================

	const handleInvoke = useCallback(async (selectedAspects) => {
		if (!invocationData || !gs.gameId) return;

		setInvocationData(null);
		gs.setLoading(true);
		gs.setSaving(true);
		sendingRef.current = true;

		await startStream('/chat', {
			gameId: gs.gameId,
			message: lastUserMessage,
			gameState: gs.gameState,
			provider: preferences?.activeProvider || 'anthropic',
			model: preferences?.activeModel || null,
			roll_id: invocationData.rollId,
			invoked_aspects: selectedAspects,
		});
	}, [invocationData, gs.gameId, gs.gameState, lastUserMessage, startStream, gs, preferences]);

	const handleSkipInvocation = useCallback(async () => {
		if (!invocationData || !gs.gameId) return;

		setInvocationData(null);
		gs.setLoading(true);
		gs.setSaving(true);
		sendingRef.current = true;

		await startStream('/chat', {
			gameId: gs.gameId,
			message: lastUserMessage,
			gameState: gs.gameState,
			provider: preferences?.activeProvider || 'anthropic',
			model: preferences?.activeModel || null,
			roll_id: invocationData.rollId,
			invoked_aspects: [],
		});
	}, [invocationData, gs.gameId, gs.gameState, lastUserMessage, startStream, gs, preferences]);

	const handleDismissInvocation = useCallback(() => {
		setInvocationData(null);
	}, []);

	// =========================================================================
	// RETURN
	// =========================================================================

	return {
		// State
		isExtracting,
		isStreaming,
		editingIndex,
		invocationData,

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
		handleDismissInvocation,

		// World generation
		handleStartAdventure,
		handleWizardComplete,
		handleWizardCancel,
	};
}
