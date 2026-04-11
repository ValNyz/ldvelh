'use client';

import { useState, useCallback, useRef } from 'react';
import { tooltipsApi } from '../lib/api';

const POLL_INTERVAL = 5000;
const MAX_POLLS = 12;

/**
 * Hook to load entity tooltip data from resolver annotations.
 *
 * After each turn, call refresh() to start polling for new annotations.
 * Builds a tooltipMap: { lowercase_canonical_name: { icon, name, type, infos, relation } }
 *
 * Bold text in messages is matched against these names for tooltip display.
 */
export function useTooltips(gameId) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const pollRef = useRef(null);
	const pollCountRef = useRef(0);
	const prevAnnotationCountRef = useRef(0);

	const stopPolling = useCallback(() => {
		if (pollRef.current) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
		pollCountRef.current = 0;
	}, []);

	const fetchAndBuild = useCallback(async () => {
		if (!gameId) return false;

		try {
			const data = await tooltipsApi.getAnnotations(gameId);
			const messages = data?.messages || [];
			if (messages.length === 0) {
				console.debug('[Tooltips] No annotations yet');
				return false;
			}
			console.debug(`[Tooltips] Got ${messages.length} annotated messages`);

			// Count total annotations
			const totalAnns = messages.reduce((sum, m) => sum + m.annotations.length, 0);
			if (totalAnns <= prevAnnotationCountRef.current) return false;
			prevAnnotationCountRef.current = totalAnns;

			// Collect unique entity names from annotations
			const entities = new Map();
			for (const msg of messages) {
				for (const ann of msg.annotations) {
					if (!entities.has(ann.canonical_name)) {
						entities.set(ann.canonical_name, ann.entity_type);
					}
				}
			}

			// Fetch tooltip details for each entity — use functional setState to avoid stale closure
			const newEntries = {};
			const icons = { character: '👤', location: '📍', organization: '🏢', object: '📦', arc: '📖' };

			for (const [name, entityType] of entities) {
				const key = name.toLowerCase();
				try {
					const result = await tooltipsApi.getEntity(gameId, name, entityType);
					if (result?.found && result.tooltip) {
						newEntries[key] = result.tooltip;
					} else {
						// Entity not in DB yet — basic tooltip
						newEntries[key] = { icon: icons[entityType] || '❓', name, type: entityType, infos: [] };
					}
				} catch {
					newEntries[key] = { icon: icons[entityType] || '❓', name, type: entityType, infos: [] };
				}
			}

			if (Object.keys(newEntries).length > 0) {
				setTooltipMap(prev => ({ ...prev, ...newEntries }));
				console.debug(`[Tooltips] Map updated with ${Object.keys(newEntries).length} entities`);
			}

			return true;
		} catch (err) {
			console.error('[Tooltips] Fetch error:', err);
			return false;
		}
	}, [gameId]); // No tooltipMap dependency — uses functional setState

	const refresh = useCallback(() => {
		if (!gameId) return;
		stopPolling();
		pollCountRef.current = 0;
		setIsLoading(true);

		// Immediate first fetch
		fetchAndBuild().then(hasNew => {
			if (hasNew) {
				setIsLoading(false);
				return;
			}
			// Start polling if no annotations yet
			pollRef.current = setInterval(async () => {
				pollCountRef.current++;
				const found = await fetchAndBuild();
				if (found || pollCountRef.current >= MAX_POLLS) {
					stopPolling();
					setIsLoading(false);
				}
			}, POLL_INTERVAL);
		});
	}, [gameId, fetchAndBuild, stopPolling]);

	return { tooltipMap, isLoading, refresh };
}
