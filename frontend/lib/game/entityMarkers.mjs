import { fromMarkdown } from 'mdast-util-from-markdown';

/**
 * Turn the stored mentions of a narrator message into markdown links, so ReactMarkdown's
 * link override can render each one with its entity's tooltip.
 *
 * A span is {start, end, entity_id}: offsets in the raw text, counted in code points (as
 * the backend counts them). Each kept span becomes `[surface](entity:<id>)`. The text is
 * parsed as markdown (the parser react-markdown uses), and a span is kept only when it
 * lies inside one plain text node: not in code (fenced, tilde, indented or inline), a
 * link, an image, a reference or a definition, and not across a bold or italic mark. A
 * span is also dropped when it does not fit the text, when its surface holds a markdown
 * mark or a line break, when it follows `!` (an image) or `\` (an escape), or when it
 * touches a bare URL (plain text for the parser, but shown as is). Of two spans that
 * overlap, the longest is kept. Nothing is ever matched by name: two identical surfaces
 * keep their own ids, and bold text written by the narrator stays plain bold.
 */

export const ENTITY_SCHEME = 'entity:';

// Characters that would open, close or escape a markdown construct inside link text.
const MARKDOWN_MARKS = /[*_`[\]\\<>~\n\r]/;
// Characters that would turn the injected link into something else right before it.
const BAD_PREFIX = new Set(['!', '\\']);
// Bare URLs: plain text for the parser, but a link must not cut them.
const BARE_URL = /\b(?:https?:\/\/|www\.)\S+/g;
// Nodes whose text is no narration a link may wrap.
const OPAQUE = new Set(['link', 'linkReference', 'image', 'imageReference', 'definition', 'code', 'inlineCode', 'html']);

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

/** The [start, end) UTF-16 ranges of the plain text nodes of the markdown `text`. */
function plainTextRanges(text) {
	const ranges = [];
	const walk = (node) => {
		if (OPAQUE.has(node.type)) return;
		if (node.type === 'text' && node.position) {
			ranges.push({ start: node.position.start.offset, end: node.position.end.offset });
		}
		for (const child of node.children || []) walk(child);
	};
	walk(fromMarkdown(text));
	return ranges;
}

/** The [start, end) ranges of the bare URLs of `text`. */
function bareUrls(text) {
	return Array.from(text.matchAll(BARE_URL), m => ({ start: m.index, end: m.index + m[0].length }));
}

function inside(outer, span) {
	return outer.start <= span.start && span.end <= outer.end;
}

function overlaps(a, b) {
	return a.start < b.end && b.start < a.end;
}

/** The spans of `spans` that can be links, in UTF-16 offsets, without overlap. */
function linkableSpans(text, spans) {
	const indexes = utf16Indexes(text);
	const last = indexes.length - 1;
	const plain = plainTextRanges(text);
	const urls = bareUrls(text);
	const candidates = spans
		.filter(s => s && s.entity_id && Number.isInteger(s.start) && Number.isInteger(s.end))
		.filter(s => s.start >= 0 && s.start < s.end && s.end <= last)
		.map(s => ({ start: indexes[s.start], end: indexes[s.end], entityId: s.entity_id }))
		.filter(s => !MARKDOWN_MARKS.test(text.slice(s.start, s.end)))
		.filter(s => !BAD_PREFIX.has(text[s.start - 1]))
		.filter(s => plain.some(r => inside(r, s)) && !urls.some(r => overlaps(r, s)))
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
