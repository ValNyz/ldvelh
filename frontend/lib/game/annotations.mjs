/**
 * Pure helpers of the entity mentions shown in the chat (useTooltips).
 *
 * spansByMessage: { message_id: [{ start, end, entity_id, entity_type, label }] }, the
 * stored mentions of each annotated narrator message. A response of
 * `/tooltips/annotations` covers a window of messages only: it is merged into what is
 * known, never put in its place, and a message leaves the map only when the chat no
 * longer shows it.
 *
 * The tooltip cache: { entity_id: { label, tooltip } }. A tooltip is fetched for an id
 * not in the cache, or whose label (what the player may read, given with each
 * annotation) changed since: a reveal renames the entity.
 */

/**
 * `prev` with the messages of `messages` (a response) put in, minus the messages that
 * are not in `liveIds` (the chat's message ids; none known yet: nothing is dropped).
 */
export function mergeSpans(prev, messages, liveIds) {
	const merged = { ...prev };
	for (const msg of messages || []) merged[msg.message_id] = msg.annotations;
	return purgeSpans(merged, liveIds);
}

/** `spans` minus the messages not in `liveIds` (empty: kept as is). */
export function purgeSpans(spans, liveIds) {
	const live = new Set(liveIds || []);
	if (live.size === 0) return spans;
	const kept = Object.fromEntries(Object.entries(spans).filter(([id]) => live.has(id)));
	return Object.keys(kept).length === Object.keys(spans).length ? spans : kept;
}

/** What identifies the mentions of one message: its spans with their ids and labels. */
function messageSignature(anns) {
	return anns.map(a => `${a.start}-${a.end}-${a.entity_id}-${a.label}`).join(',');
}

/** What identifies the mentions of `spans`: each message with its spans and labels. */
export function spansSignature(spans) {
	return Object.entries(spans)
		.map(([id, anns]) => `${id}:${messageSignature(anns)}`)
		.sort()
		.join('|');
}

/**
 * Whether `messages` (a response) would change `spans`: a message not known yet, or one
 * whose spans differ from the known ones (a reveal or a merge renames an entity or moves
 * a mention to the surviving id).
 */
export function changesSpans(spans, messages) {
	return (messages || []).some(m =>
		!(m.message_id in spans) || messageSignature(spans[m.message_id]) !== messageSignature(m.annotations));
}

/** The current label of each entity of `messages` (a response: labels are fresh). */
export function latestLabels(messages) {
	const labels = {};
	for (const msg of messages || []) {
		for (const ann of msg.annotations) labels[ann.entity_id] = ann.label;
	}
	return labels;
}

/** The entity ids `spans` refer to, with the annotation of each (the last seen). */
export function referencedEntities(spans) {
	const entities = {};
	for (const anns of Object.values(spans)) {
		for (const ann of anns) entities[ann.entity_id] = ann;
	}
	return entities;
}

/**
 * The entity ids of `spans` whose tooltip must be fetched: not in `cache`, or whose
 * label in `labels` (the latest response) differs from the cached one.
 */
export function idsToFetch(spans, cache, labels) {
	return Object.keys(referencedEntities(spans)).filter(id => {
		const cached = cache[id];
		return !cached || (id in labels && labels[id] !== cached.label);
	});
}

/** `cache` restricted to the entities `spans` still refer to. */
export function pruneCache(cache, spans) {
	const referenced = referencedEntities(spans);
	return Object.fromEntries(Object.entries(cache).filter(([id]) => id in referenced));
}

/** The tooltip map `{entity_id: tooltip}` of `cache`. */
export function tooltipMapOf(cache) {
	return Object.fromEntries(Object.entries(cache).map(([id, { tooltip }]) => [id, tooltip]));
}

/** `items` in chunks of at most `size`. */
export function chunks(items, size) {
	const out = [];
	for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
	return out;
}
