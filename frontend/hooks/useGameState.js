'use client';

import { useState, useCallback } from 'react';
import { normalizeGameState } from '../lib/game/gameState.js';
import { gamesApi, stateApi } from '../lib/api.js';

// ============================================================================
// MAIN HOOK
// ============================================================================

export function useGameState() {
	const [gameId, setGameId] = useState(null);
	const [gameName, setGameName] = useState('');
	const [gameState, setGameStateRaw] = useState(null);
	const [messages, setMessages] = useState([]);
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState(null);

	/**
	 * Update gameState with smart merge.
	 * Used after each server response.
	 */
	const updateGameState = useCallback((newState) => {
		const normalized = normalizeGameState(newState);
		if (!normalized) return;

		setGameStateRaw(prev => {
			if (!prev) return normalized;

			return {
				game: { ...prev.game, ...normalized.game },
				player: mergePlayer(prev.player, normalized.player),
				ai: normalized.ai?.name ? { ...prev.ai, ...normalized.ai } : prev.ai,
				world_created: normalized.world_created ?? prev.world_created ?? false
			};
		});
	}, []);

	/**
	 * Fully replace gameState (for initial load).
	 * Avoids merge with stale state.
	 */
	const replaceGameState = useCallback((newState) => {
		const normalized = normalizeGameState(newState);
		setGameStateRaw(normalized);
	}, []);

	const clearError = useCallback(() => setError(null), []);

	const resetGame = useCallback(() => {
		setGameId(null);
		setGameName('');
		setGameStateRaw(null);
		setMessages([]);
		setError(null);
	}, []);

	return {
		// State
		gameId,
		gameName,
		gameState,
		messages,
		loading,
		saving,
		error,

		// Setters
		setGameId,
		setGameName,
		setGameState: updateGameState,
		replaceGameState,
		setMessages,
		setLoading,
		setSaving,
		setError,

		// Actions
		clearError,
		resetGame,
		normalizeGameState
	};
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Smart merge for player data.
 * Inventory is always replaced (source of truth = DB).
 */
function mergePlayer(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		credits: next.credits ?? prev.credits,
		inventory: next.inventory !== undefined ? next.inventory : (prev.inventory || []),
		engine_stats: next.engine_stats !== undefined ? next.engine_stats : prev.engine_stats
	};
}

// ============================================================================
// GAMES HOOK
// ============================================================================

export function useGames() {
	const [games, setGames] = useState([]);
	const [loadingList, setLoadingList] = useState(false);

	const loadGames = useCallback(async () => {
		setLoadingList(true);
		try {
			const data = await gamesApi.list();
			setGames(data.games || []);
		} catch (e) {
			console.error('Error loading games:', e);
		} finally {
			setLoadingList(false);
		}
	}, []);

	const createGame = useCallback(async (engine = null) => {
		const data = await gamesApi.create(engine);
		if (data.error) throw new Error(data.error);
		return data.gameId;
	}, []);

	const deleteGame = useCallback(async (id) => {
		await gamesApi.delete(id);
		return true;
	}, []);

	const renameGame = useCallback(async (id, newName) => {
		await gamesApi.rename(id, newName);
	}, []);

	const loadGame = useCallback(async (id) => {
		const data = await stateApi.load(id);
		if (data.error) throw new Error(data.error);
		return data;
	}, []);

	return {
		games,
		loadingList,
		loadGames,
		createGame,
		deleteGame,
		renameGame,
		loadGame
	};
}
