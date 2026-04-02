'use client';

import { useState, useEffect, useCallback } from 'react';
import { stateApi } from '../lib/api';

/**
 * Hook pour charger et rafraîchir les données du monde (sidebar)
 * 
 * @param {string|null} gameId - ID de la partie
 * @param {boolean} enabled - Si false, ne charge pas les données
 * @returns {{ 
 *   worldData: {npcs: Array, locations: Array, quests: Array, organizations: Array} | null,
 *   loading: boolean,
 *   error: string | null,
 *   refresh: () => Promise<void>
 * }}
 */
export function useWorldData(gameId, enabled = true) {
	const [worldData, setWorldData] = useState(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState(null);

	const fetchWorldData = useCallback(async (force = false) => {
		if (!gameId || (!enabled && !force)) return;

		setLoading(true);
		setError(null);

		try {
			const data = await stateApi.getWorld(gameId);
			setWorldData(data);
		} catch (err) {
			console.error('[useWorldData] Erreur:', err);
			setError(err.message);
		} finally {
			setLoading(false);
		}
	}, [gameId, enabled]);

	// Load on mount and when gameId/enabled changes
	useEffect(() => {
		fetchWorldData();
	}, [fetchWorldData]);

	// Explicit refresh always fetches (bypasses enabled check)
	const refresh = useCallback(async () => {
		await fetchWorldData(true);
	}, [fetchWorldData]);

	return {
		worldData,
		loading,
		error,
		refresh
	};
}

export default useWorldData;
