/**
 * LDVELH - AI fill re-roll base
 * Each click on "Enrichir avec l'IA" starts from the player's own state, never
 * from the previous AI version (no drift). The wizard remembers each fill as
 * { base: what was sent, result: what came back }; a field still holding an AI
 * result is sent as the base it came from. A field the player edited is theirs.
 */

const MAX_FILLS = 20;

export function rememberFill(fills, base, result) {
	return [...fills, { base, result }].slice(-MAX_FILLS);
}

/** The step's fields as the player left them: AI results replaced by their base. */
export function baseOf(fills, current) {
	const out = { ...current };
	for (const key of Object.keys(out)) {
		const fill = findLast(fills, f => key in f.result && same(f.result[key], out[key]));
		if (!fill) continue;
		if (key in fill.base) out[key] = fill.base[key];
		else delete out[key];
	}
	return out;
}

/** True when the field still holds what an AI fill wrote (and changed). */
export function isAiValue(fills, key, value) {
	return fills.some(f => same(f.result[key], value) && !same(f.base[key], value));
}

/**
 * An AI suggestion the player has not edited. A suggested entity keeps the AI's
 * version in `suggested`, so editing it changes one field only (one undo entry).
 */
export function isSuggestion(e) {
	return !!e.suggested && e.suggested.name === e.name && e.suggested.description === e.description;
}

/** Entity lists without the AI suggestions the player has not edited. */
export function withoutSuggestions(entities) {
	return Object.fromEntries(Object.entries(entities || {}).map(
		([kind, items]) => [kind, Array.isArray(items) ? items.filter(e => !isSuggestion(e)) : items],
	));
}

/** Mark the entities the AI added (names absent from what was sent). */
export function markSuggestions(result, sent) {
	return Object.fromEntries(Object.entries(result || {}).map(([kind, items]) => {
		const known = new Set((sent?.[kind] || []).map(e => e.name.trim().toLowerCase()));
		return [kind, items.map(e => (known.has(e.name.trim().toLowerCase())
			? e
			: { ...e, suggested: { name: e.name, description: e.description } }))];
	}));
}

function findLast(list, predicate) {
	for (let i = list.length - 1; i >= 0; i--) if (predicate(list[i])) return list[i];
	return null;
}

// Form values are small JSON-like values.
function same(a, b) {
	return JSON.stringify(a) === JSON.stringify(b);
}
