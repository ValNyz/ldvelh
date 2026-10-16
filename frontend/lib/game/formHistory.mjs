/**
 * LDVELH - Form history (undo / redo)
 * Pure functions over { past, present, future }: every change, by the player or
 * by the AI, is one entry. Consecutive edits of the same field (typing, repeated
 * clicks on one skill) are merged into one entry until another field changes or
 * seal() is called (the field loses focus). Long texts are also cut at pauses
 * (pauseMs), like a text editor, so a description written in several goes is
 * undone one go at a time.
 */

export const HISTORY_LIMIT = 100;
export const TEXT_PAUSE_MS = 2000;

export function createHistory(present) {
	return { past: [], present, future: [], lastKey: null, lastAt: 0 };
}

/**
 * Record a new present.
 * @param {object} h - history
 * @param {*} next - new present (ignored if identical to the current one)
 * @param {object} [opts]
 * @param {string|null} [opts.key] - field being edited; the same key as the previous change merges
 * @param {number|null} [opts.pauseMs] - when set, a pause this long starts a new entry
 * @param {number} [opts.at] - timestamp (ms)
 * @param {*} [opts.meta] - stored with the entry it creates (e.g. the wizard step)
 */
export function push(h, next, { key = null, meta = null, pauseMs = null, at = Date.now() } = {}) {
	if (Object.is(next, h.present)) return h;
	const merge = key !== null && key === h.lastKey && h.past.length > 0
		&& (pauseMs === null || at - h.lastAt < pauseMs);
	if (merge && sameState(next, h.past[h.past.length - 1].state)) {
		// The merged edit came back to where it started (e.g. "+" then "-"): no entry left.
		return { past: h.past.slice(0, -1), present: next, future: [], lastKey: null, lastAt: 0 };
	}
	const past = merge
		? h.past
		: [...h.past, { state: h.present, meta }].slice(-HISTORY_LIMIT);
	return { past, present: next, future: [], lastKey: key, lastAt: at };
}

/** End the current entry: the next change starts a new one, even on the same field. */
export function seal(h) {
	return h.lastKey === null ? h : { ...h, lastKey: null };
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
	};
}

/** Meta of the entry undo() / redo() would apply (e.g. to show the step it changes). */
export const undoMeta = h => h.past[h.past.length - 1]?.meta ?? null;
export const redoMeta = h => h.future[0]?.meta ?? null;

/**
 * Coalescing key for a change of a nested form: the path of the one leaf that
 * changed ("worldConfig.lore", "characterData.skills.Piratage",
 * "manualEntities.npcs.0.name"), else null: several fields changed at once,
 * never merged. Lets typing in one
 * field merge while an edit of another field starts a new entry.
 */
export function changeKey(prev, next) {
	const path = [];
	let a = prev;
	let b = next;
	while (isContainer(a) && isContainer(b) && Array.isArray(a) === Array.isArray(b)
		&& (!Array.isArray(a) || a.length === b.length)) {
		const changed = Object.keys({ ...a, ...b }).filter(k => !Object.is(a[k], b[k]));
		if (changed.length !== 1) return null;
		path.push(changed[0]);
		a = a[changed[0]];
		b = b[changed[0]];
	}
	return path.join('.') || null;
}

// Form states are small JSON-like objects.
function sameState(a, b) {
	return JSON.stringify(a) === JSON.stringify(b);
}

function isContainer(v) {
	return v !== null && typeof v === 'object';
}
