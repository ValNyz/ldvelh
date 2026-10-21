/**
 * Turn the stored mentions of a narrator message into markdown links, so ReactMarkdown's
 * link override can render each one with its entity's tooltip.
 *
 * A span is {start, end, entity_id}: offsets in the raw text, counted in code points (as
 * the backend counts them). Each kept span becomes `[surface](entity:<id>)`. A span is
 * dropped when it does not fit the text, when its surface holds a markdown mark or a line
 * break, or when it touches a code block, inline code, a link or a URL; of two spans that
 * overlap, the longest is kept. Nothing is ever matched by name: two identical surfaces
 * keep their own ids, and bold text written by the narrator stays plain bold.
 */

export const ENTITY_SCHEME = 'entity:';

// Characters that would open, close or escape a markdown construct inside link text.
const MARKDOWN_MARKS = /[*_`[\]\\<>~\n\r]/;
// Text a link must not be injected into: fenced code, inline code, markdown links,
// autolinks and bare URLs.
const PROTECTED = [
	/```[\s\S]*?(?:```|$)/g,
	/`[^`\n]*`/g,
	/!?\[[^\]\n]*\]\([^)\n]*\)/g,
	/<[^>\s]+>/g,
	/\b(?:https?:\/\/|www\.)\S+/g,
];

/** The entity id of an `entity:<id>` href; null for any other href. */
export function entityIdOf(href) {
	return typeof href === 'string' && href.startsWith(ENTITY_SCHEME)
		? href.slice(ENTITY_SCHEME.length)
		: null;
}

/** The UTF-16 index of each code point index of `text` (one more for its end). */
function utf16Indexes(text) {
	const indexes = [];
	let index = 0;
	for (const char of text) {
		indexes.push(index);
		index += char.length;
	}
	indexes.push(index);
	return indexes;
}

/** The [start, end) ranges of `text` no link may touch. */
function protectedRanges(text) {
	return PROTECTED.flatMap(pattern =>
		Array.from(text.matchAll(pattern), m => [m.index, m.index + m[0].length]),
	);
}

function overlaps(a, b) {
	return a.start < b.end && b.start < a.end;
}

/** The spans of `spans` that can be links, in UTF-16 offsets, without overlap. */
function linkableSpans(text, spans) {
	const indexes = utf16Indexes(text);
	const last = indexes.length - 1;
	const ranges = protectedRanges(text).map(([start, end]) => ({ start, end }));
	const candidates = spans
		.filter(s => s && s.entity_id && Number.isInteger(s.start) && Number.isInteger(s.end))
		.filter(s => s.start >= 0 && s.start < s.end && s.end <= last)
		.map(s => ({ start: indexes[s.start], end: indexes[s.end], entityId: s.entity_id }))
		.filter(s => !MARKDOWN_MARKS.test(text.slice(s.start, s.end)))
		.filter(s => !ranges.some(r => overlaps(r, s)))
		// Longest first (then leftmost): it wins over the spans it overlaps.
		.sort((a, b) => (b.end - b.start) - (a.end - a.start) || a.start - b.start);
	const kept = [];
	for (const span of candidates) {
		if (!kept.some(k => overlaps(k, span))) kept.push(span);
	}
	return kept;
}

/** `text` with each linkable span of `spans` written as an entity link. */
export function injectEntityMarkers(text, spans) {
	if (!text || !spans || spans.length === 0) return text;
	let out = text;
	// From the end, so that earlier offsets stay valid.
	for (const { start, end, entityId } of linkableSpans(text, spans).sort((a, b) => b.start - a.start)) {
		out = `${out.slice(0, start)}[${out.slice(start, end)}](${ENTITY_SCHEME}${entityId})${out.slice(end)}`;
	}
	return out;
}
