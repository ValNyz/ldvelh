'use client';

import { useState, useCallback, useRef } from 'react';
import { tooltipsApi } from '../lib/api';

const POLL_INTERVAL = 5000;
const MAX_POLLS = 12;

/**
 * Hook to load entity tooltip data from resolver annotations.
 *
 * After each turn, call refresh() to start polling for new annotations.
 * Builds a tooltipMap: { lowercase_surface: { icon, name, type, infos, relation } }: each
 * text the narration shows for an annotated entity maps to that entity's tooltip, fetched
 * by entity id (its `name` is what the player may read).
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

			// One entry per entity (its id; the label for an unresolved span), with the
			// texts the narration shows for it: the tooltip is fetched once per entity and
			// keyed by each surface, so two entities never collapse onto one display name.
			const entities = new Map();
			for (const msg of messages) {
				for (const ann of msg.annotations) {
					const key = ann.entity_id || `${ann.entity_type}:${ann.label}`;
					if (!entities.has(key)) {
						entities.set(key, { ref: ann.entity_id || ann.label, label: ann.label, entityType: ann.entity_type, surfaces: new Set() });
					}
					entities.get(key).surfaces.add(ann.surface || ann.label);
				}
			}

			// Fetch tooltip details for each entity — use functional setState to avoid stale closure
			const newEntries = {};
			const icons = { character: '👤', location: '📍', organization: '🏢', object: '📦', arc: '📖' };

			for (const { ref, label, entityType, surfaces } of entities.values()) {
				let tooltip;
				try {
					const result = await tooltipsApi.getEntity(gameId, ref, entityType);
					tooltip = result?.found && result.tooltip ? result.tooltip : null;
				} catch {
					tooltip = null;
				}
				// Entity not in DB yet — basic tooltip
				tooltip = tooltip || { icon: icons[entityType] || '❓', name: label, type: entityType, infos: [] };
				for (const surface of surfaces) {
					newEntries[surface.toLowerCase()] = tooltip;
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
