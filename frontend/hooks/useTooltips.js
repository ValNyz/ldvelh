'use client';

import { useState, useEffect, useCallback } from 'react';
import { tooltipsApi } from '../lib/api';

/**
 * Hook to load tooltip data for a game.
 * Returns a map of entity name/alias -> formatted tooltip data.
 *
 * NOTE: Fetch is disabled for now. Re-enable by uncommenting fetchTooltips body.
 */
export function useTooltips(gameId) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState(null);

	const fetchTooltips = useCallback(async () => {
		// TODO: re-enable tooltip fetching
		setTooltipMap({});
	}, [gameId]);

	useEffect(() => {
		fetchTooltips();
	}, [fetchTooltips]);

	const refresh = useCallback(() => {
		fetchTooltips();
	}, [fetchTooltips]);

	return { tooltipMap, isLoading, error, refresh };
}
