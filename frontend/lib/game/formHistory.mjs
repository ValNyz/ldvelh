/**
 * LDVELH - Form history (undo / redo)
 * Pure functions over { past, present, future }: every change, by the player or
 * by the AI, is one entry; consecutive edits of the same field within a short
 * window (typing) are merged into one entry.
 */

export const COALESCE_MS = 1000;
export const HISTORY_LIMIT = 100;

export function createHistory(present) {
	return { past: [], present, future: [], lastKey: null, lastAt: 0 };
}

/**
 * Record a new present.
 * @param {object} h - history
 * @param {*} next - new present (ignored if identical to the current one)
 * @param {object} [opts]
 * @param {string|null} [opts.key] - field being edited; same key within COALESCE_MS merges
 * @param {number} [opts.at] - timestamp (ms)
 * @param {*} [opts.meta] - stored with the entry it creates (e.g. the wizard step)
 */
export function push(h, next, { key = null, at = Date.now(), meta = null } = {}) {
	if (Object.is(next, h.present)) return h;
	const merge = key !== null && key === h.lastKey && at - h.lastAt < COALESCE_MS && h.past.length > 0;
	if (merge && sameState(next, h.past[h.past.length - 1].state)) {
		// The merged edit came back to where it started (e.g. "+" then "-"): no entry left.
		return { past: h.past.slice(0, -1), present: next, future: [], lastKey: null, lastAt: 0 };
	}
	const past = merge
		? h.past
		: [...h.past, { state: h.present, meta }].slice(-HISTORY_LIMIT);
	return { past, present: next, future: [], lastKey: key, lastAt: at };
}

/** Step back; returns the same object when there is nothing to undo. */
export function undo(h) {
	if (h.past.length === 0) return h;
	const entry = h.past[h.past.length - 1];
	return {
		past: h.past.slice(0, -1),
		present: entry.state,
		future: [{ state: h.present, meta: entry.meta }, ...h.future],
		lastKey: null,
		lastAt: 0,
	};
}

/** Step forward; returns the same object when there is nothing to redo. */
export function redo(h) {
	if (h.future.length === 0) return h;
	const entry = h.future[0];
	return {
		past: [...h.past, { state: h.present, meta: entry.meta }],
		present: entry.state,
		future: h.future.slice(1),
		lastKey: null,
		lastAt: 0,
	};
}

/** Meta of the entry undo() / redo() would apply (e.g. to show the step it changes). */
export const undoMeta = h => h.past[h.past.length - 1]?.meta ?? null;
export const redoMeta = h => h.future[0]?.meta ?? null;

/**
 * Coalescing key for a change of a nested form: "slice.field" when one field of
 * one slice changed, else null (never merged). Lets typing in one field merge
 * while a click on another field starts a new entry.
 */
export function changeKey(prev, next) {
	const slices = Object.keys({ ...prev, ...next }).filter(k => !Object.is(prev?.[k], next?.[k]));
	if (slices.length !== 1) return null;
	const slice = slices[0];
	const a = prev?.[slice];
	const b = next?.[slice];
	if (!isPlainObject(a) || !isPlainObject(b)) return slice;
	const fields = Object.keys({ ...a, ...b }).filter(k => !Object.is(a[k], b[k]));
	if (fields.length !== 1) return null;
	return `${slice}.${fields[0]}`;
}

// Form states are small JSON-like objects.
function sameState(a, b) {
	return JSON.stringify(a) === JSON.stringify(b);
}

function isPlainObject(v) {
	return v !== null && typeof v === 'object' && !Array.isArray(v);
}
