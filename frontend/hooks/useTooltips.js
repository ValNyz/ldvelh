'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { tooltipsApi } from '../lib/api';
import {
	changesSpans, chunks, idsToFetch, latestLabels, mergeSpans, pruneCache, purgeSpans,
	referencedEntities, spansSignature, tooltipMapOf,
} from '../lib/game/annotations.mjs';
import { createRunGuard } from '../lib/game/runGuard.mjs';

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
 *   with `before` while they bring a message not seen yet or change a known one (a
 *   reveal or a merge), so every shown message keeps its mentions up to date. A message
 *   leaves the map when the chat no longer shows it;
 * - tooltipMap: { entity_id: tooltip }, from a cache keyed by id and label: only new ids
 *   and renamed entities are fetched, in one batch request; a failed id is asked again
 *   on the next fetch.
 *
 * Only the latest run commits (a run guard): work started for another game, or by a
 * poll still awaiting when refresh() starts again, is ignored.
 */
export function useTooltips(gameId, messageIds = []) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [spansByMessage, setSpansByMessage] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const pollRef = useRef(null);
	const pollCountRef = useRef(0);
	const guardRef = useRef(null);
	if (!guardRef.current) guardRef.current = createRunGuard();
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
		guardRef.current.start();
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

	/** The annotations of the latest page, then of older pages while they change something. */
	const fetchAnnotations = useCallback(async () => {
		let spans = spansRef.current;
		let labels = {};
		let before;
		for (let page = 0; page < MAX_PAGES; page++) {
			const data = await tooltipsApi.getAnnotations(gameId, { limit: PAGE_SIZE, before });
			const messages = data?.messages || [];
			const changes = changesSpans(spans, messages);
			labels = { ...latestLabels(messages), ...labels };
			spans = mergeSpans(spans, messages, liveIdsRef.current);
			if (messages.length < PAGE_SIZE || !changes) break;
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

	/** One fetch for the run `isCurrent` (createRunGuard): it commits only if still current. */
	const fetchAndBuild = useCallback(async (isCurrent) => {
		if (!gameId) return false;
		try {
			const { spans: fetched, labels } = await fetchAnnotations();
			if (!isCurrent()) return false;
			const ids = idsToFetch(fetched, cacheRef.current, labels);
			const cache = ids.length
				? await fetchTooltips(ids, fetched, labels, cacheRef.current)
				: cacheRef.current;
			if (!isCurrent()) return false;
			// The chat may have changed during the awaits (rollback): purge again.
			const spans = purgeSpans(fetched, liveIdsRef.current);
			const changed = spansSignature(spans) !== spansSignature(spansRef.current);
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
		// A poll of an earlier refresh still awaiting must not commit after this one.
		const isCurrent = guardRef.current.start();
		setIsLoading(true);

		fetchAndBuild(isCurrent).then(hasNew => {
			if (!isCurrent()) return;
			if (hasNew) {
				setIsLoading(false);
				return;
			}
			// Poll until the resolver's mentions of the turn arrive
			pollRef.current = setInterval(async () => {
				pollCountRef.current++;
				const found = await fetchAndBuild(isCurrent);
				if (!isCurrent()) return;
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
