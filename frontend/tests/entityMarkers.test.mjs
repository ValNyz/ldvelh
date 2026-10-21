import { test } from 'node:test';
import assert from 'node:assert/strict';

import { entityIdOf, injectEntityMarkers } from '../lib/game/entityMarkers.mjs';

const A = '00000000-0000-0000-0000-00000000000a';
const B = '00000000-0000-0000-0000-00000000000b';

/** The span of the first occurrence of `surface` in `text`, from index `from`. */
function span(text, surface, entity_id, from = 0) {
	const start = text.indexOf(surface, from);
	assert.notEqual(start, -1, `${surface} not in ${text}`);
	return { start, end: start + surface.length, entity_id };
}

test('a span is rendered as an entity link at its offsets', () => {
	const text = 'Le cargo rentre à Vergence ce soir.';
	assert.equal(
		injectEntityMarkers(text, [span(text, 'Vergence', A)]),
		`Le cargo rentre à [Vergence](entity:${A}) ce soir.`,
	);
	assert.equal(entityIdOf(`entity:${A}`), A);
	assert.equal(entityIdOf('https://example.org'), null);
});

test('overlapping spans keep the longest', () => {
	const text = 'Pater Ondrev parle.';
	assert.equal(
		injectEntityMarkers(text, [span(text, 'Pater', B), span(text, 'Pater Ondrev', A)]),
		`[Pater Ondrev](entity:${A}) parle.`,
	);
});

test('accented surfaces keep their offsets', () => {
	const text = "L'Élan repart vers l'Hôtel-Dieu, après l'été.";
	assert.equal(
		injectEntityMarkers(text, [span(text, 'Élan', A), span(text, 'Hôtel-Dieu', B)]),
		`L'[Élan](entity:${A}) repart vers l'[Hôtel-Dieu](entity:${B}), après l'été.`,
	);
});

test('code point offsets survive a character outside the BMP', () => {
	// The backend counts code points: the emoji is one, but two UTF-16 units.
	const text = '🌙 Vergence dort.';
	assert.equal(
		injectEntityMarkers(text, [{ start: 2, end: 10, entity_id: A }]),
		`🌙 [Vergence](entity:${A}) dort.`,
	);
});

test('two identical surfaces map to two different ids', () => {
	const text = 'Le garde salue le garde.';
	const first = span(text, 'garde', A);
	const second = span(text, 'garde', B, first.end);
	assert.equal(
		injectEntityMarkers(text, [first, second]),
		`Le [garde](entity:${A}) salue le [garde](entity:${B}).`,
	);
});

test('a message without spans is unchanged', () => {
	const text = 'Rien ici. **Le** reste en gras.';
	assert.equal(injectEntityMarkers(text, []), text);
	assert.equal(injectEntityMarkers(text, undefined), text);
	assert.equal(injectEntityMarkers('', [{ start: 0, end: 1, entity_id: A }]), '');
});

test('a span crossing a bold mark or a URL is dropped', () => {
	const bold = 'Il voit **Vergence** au loin.';
	assert.equal(injectEntityMarkers(bold, [span(bold, 'voit **Ver', A)]), bold);
	// Inside the bold text, the span crosses no mark.
	assert.equal(
		injectEntityMarkers(bold, [span(bold, 'Vergence', A)]),
		`Il voit **[Vergence](entity:${A})** au loin.`,
	);
	const url = 'Voir https://vergence.example/carte et [la carte](https://x.example).';
	assert.equal(injectEntityMarkers(url, [span(url, 'vergence', A)]), url);
	assert.equal(injectEntityMarkers(url, [span(url, 'la carte', A)]), url);
});

test('a span inside a code block is dropped', () => {
	const fenced = 'Avant.\n```\nVergence\n```\nAprès.';
	assert.equal(injectEntityMarkers(fenced, [span(fenced, 'Vergence', A)]), fenced);
	const inline = 'Tape `Vergence` puis entre.';
	assert.equal(injectEntityMarkers(inline, [span(inline, 'Vergence', A)]), inline);
});

test('a span out of the text or empty is dropped', () => {
	const text = 'Vergence.';
	assert.equal(injectEntityMarkers(text, [{ start: 4, end: 40, entity_id: A }]), text);
	assert.equal(injectEntityMarkers(text, [{ start: 3, end: 3, entity_id: A }]), text);
});
