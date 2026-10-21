'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { tooltipsApi } from '../lib/api';
import {
	chunks, idsToFetch, latestLabels, mergeSpans, pruneCache, purgeSpans,
	referencedEntities, spansSignature, tooltipMapOf,
} from '../lib/game/annotations.mjs';

const POLL_INTERVAL = 5000;
const MAX_POLLS = 12;
// Annotated messages per request (the backend's cap) and pages read back at most.
const PAGE_SIZE = 50;
const MAX_PAGES = 20;
// Entity ids per batch tooltip request (the backend's cap).
const IDS_PER_REQUEST = 100;

/**
 * Hook to load the stored entity mentions of the narration and their tooltips.
 *
 * `messageIds`: the ids of the messages the chat shows. After each turn, call refresh()
 * to poll for new annotations. It keeps:
 * - spansByMessage: { message_id: [{ start, end, entity_id, ... }] }. Each response is
 *   merged in (lib/game/annotations.mjs): the latest page, and the older pages read back
 *   with `before` while they bring messages not seen yet, so every shown message keeps
 *   its mentions. A message leaves the map when the chat no longer shows it;
 * - tooltipMap: { entity_id: tooltip }, from a cache keyed by id and label: only new ids
 *   and renamed entities are fetched, in one batch request; a failed id is asked again
 *   on the next fetch.
 *
 * Work started for another game is ignored (a generation counter).
 */
export function useTooltips(gameId, messageIds = []) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [spansByMessage, setSpansByMessage] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const pollRef = useRef(null);
	const pollCountRef = useRef(0);
	const generationRef = useRef(0);
	const spansRef = useRef({});
	const cacheRef = useRef({});
	const liveIdsRef = useRef(messageIds);
	liveIdsRef.current = messageIds;

	const stopPolling = useCallback(() => {
		if (pollRef.current) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
		pollCountRef.current = 0;
	}, []);

	// Another game: nothing of the previous one is kept, and its work in flight is void.
	useEffect(() => {
		generationRef.current += 1;
		stopPolling();
		spansRef.current = {};
		cacheRef.current = {};
		setTooltipMap({});
		setSpansByMessage({});
	}, [gameId, stopPolling]);

	// Messages gone from the chat (rollback, regeneration) lose their mentions.
	const liveKey = messageIds.join(',');
	useEffect(() => {
		const kept = purgeSpans(spansRef.current, liveIdsRef.current);
		if (kept === spansRef.current) return;
		spansRef.current = kept;
		cacheRef.current = pruneCache(cacheRef.current, kept);
		setSpansByMessage(kept);
		setTooltipMap(tooltipMapOf(cacheRef.current));
	}, [liveKey]);

	/** The annotations of the latest page, then of older pages while they are new. */
	const fetchAnnotations = useCallback(async () => {
		let spans = spansRef.current;
		let labels = {};
		let before;
		for (let page = 0; page < MAX_PAGES; page++) {
			const data = await tooltipsApi.getAnnotations(gameId, { limit: PAGE_SIZE, before });
			const messages = data?.messages || [];
			const unseen = messages.some(m => !(m.message_id in spans));
			labels = { ...latestLabels(messages), ...labels };
			spans = mergeSpans(spans, messages, liveIdsRef.current);
			if (messages.length < PAGE_SIZE || !unseen) break;
			before = messages[messages.length - 1].sequence;
		}
		return { spans, labels };
	}, [gameId]);

	/**
	 * The cache with the tooltips of `ids` put in, each under its latest label; ids whose
	 * request failed stay out.
	 */
	const fetchTooltips = useCallback(async (ids, spans, labels, cache) => {
		const next = { ...cache };
		const annotation = referencedEntities(spans);
		await Promise.all(chunks(ids, IDS_PER_REQUEST).map(async (part) => {
			try {
				const data = await tooltipsApi.getEntities(gameId, part);
				for (const id of part) {
					const label = labels[id] ?? annotation[id].label;
					const type = annotation[id].entity_type;
					// No entity behind the id: its player-safe label alone.
					const tooltip = data?.tooltips?.[id] || { name: label, type, infos: [] };
					next[id] = { label, tooltip };
				}
			} catch (err) {
				console.error('[Tooltips] Entity fetch error:', err);
			}
		}));
		return next;
	}, [gameId]);

	const fetchAndBuild = useCallback(async () => {
		if (!gameId) return false;
		const generation = generationRef.current;
		try {
			const { spans, labels } = await fetchAnnotations();
			if (generation !== generationRef.current) return false;
			const changed = spansSignature(spans) !== spansSignature(spansRef.current);
			const ids = idsToFetch(spans, cacheRef.current, labels);
			const cache = ids.length
				? await fetchTooltips(ids, spans, labels, cacheRef.current)
				: cacheRef.current;
			if (generation !== generationRef.current) return false;
			spansRef.current = spans;
			cacheRef.current = pruneCache(cache, spans);
			if (changed) setSpansByMessage(spans);
			if (changed || ids.length) setTooltipMap(tooltipMapOf(cacheRef.current));
			return changed;
		} catch (err) {
			console.error('[Tooltips] Fetch error:', err);
			return false;
		}
	}, [gameId, fetchAnnotations, fetchTooltips]);

	const refresh = useCallback(() => {
		if (!gameId) return;
		stopPolling();
		const generation = generationRef.current;
		setIsLoading(true);

		fetchAndBuild().then(hasNew => {
			if (generation !== generationRef.current) return;
			if (hasNew) {
				setIsLoading(false);
				return;
			}
			// Poll until the resolver's mentions of the turn arrive
			pollRef.current = setInterval(async () => {
				pollCountRef.current++;
				const found = await fetchAndBuild();
				if (generation !== generationRef.current) return;
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
