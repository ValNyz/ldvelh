'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { tooltipsApi } from '../lib/api';

const POLL_INTERVAL = 5000;
const MAX_POLLS = 12;

/**
 * Hook to load the stored entity mentions of the narration and their tooltips.
 *
 * After each turn, call refresh() to start polling for new annotations. It builds:
 * - spansByMessage: { message_id: [{ start, end, entity_id }] }, the mentions of each
 *   annotated message (offsets in its raw text);
 * - tooltipMap: { entity_id: { icon, name, type, infos, relation } }, fetched by id
 *   (its `name` is what the player may read).
 *
 * The annotations are rebuilt when the set of (message_id, number of annotations)
 * changes, not when a total grows: a rollback or a regeneration that removes messages is
 * seen, and the keys of messages and entities no longer annotated are dropped.
 */
export function useTooltips(gameId) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [spansByMessage, setSpansByMessage] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const pollRef = useRef(null);
	const pollCountRef = useRef(0);
	const signatureRef = useRef('');

	const stopPolling = useCallback(() => {
		if (pollRef.current) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
		pollCountRef.current = 0;
	}, []);

	// Another game: nothing of the previous one is kept.
	useEffect(() => {
		stopPolling();
		signatureRef.current = '';
		setTooltipMap({});
		setSpansByMessage({});
	}, [gameId, stopPolling]);

	const fetchAndBuild = useCallback(async () => {
		if (!gameId) return false;

		try {
			const data = await tooltipsApi.getAnnotations(gameId);
			const messages = data?.messages || [];
			const signature = annotationSignature(messages);
			if (signature === signatureRef.current) return false;
			signatureRef.current = signature;

			const spans = {};
			const entities = new Map();
			for (const msg of messages) {
				spans[msg.message_id] = msg.annotations.map(({ start, end, entity_id }) => ({ start, end, entity_id }));
				for (const ann of msg.annotations) {
					if (!entities.has(ann.entity_id)) entities.set(ann.entity_id, ann);
				}
			}

			// One tooltip per entity, fetched again on each change: a reveal renames it.
			const tooltips = {};
			await Promise.all(Array.from(entities.values(), async (ann) => {
				tooltips[ann.entity_id] = await fetchTooltip(gameId, ann);
			}));

			setSpansByMessage(spans);
			setTooltipMap(tooltips);
			console.debug(`[Tooltips] ${messages.length} annotated messages, ${entities.size} entities`);
			return messages.length > 0;
		} catch (err) {
			console.error('[Tooltips] Fetch error:', err);
			return false;
		}
	}, [gameId]);

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
			// Poll until the resolver's mentions of the turn arrive
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

	useEffect(() => stopPolling, [stopPolling]);

	return { tooltipMap, spansByMessage, isLoading, refresh };
}

/** What identifies a set of annotated messages: each message id with its count. */
function annotationSignature(messages) {
	return messages
		.map(m => `${m.message_id}:${m.annotations.length}`)
		.sort()
		.join('|');
}

/** The tooltip of an annotated entity; its player-safe label alone when the lookup fails. */
async function fetchTooltip(gameId, ann) {
	try {
		const result = await tooltipsApi.getEntity(gameId, ann.entity_id);
		if (result?.found && result.tooltip) return result.tooltip;
	} catch {
		// The label of the annotation is shown instead.
	}
	return { icon: '', name: ann.label, type: ann.entity_type, infos: [] };
}
