import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	chunks, idsToFetch, latestLabels, mergeSpans, pruneCache, purgeSpans, spansSignature,
	tooltipMapOf,
} from '../lib/game/annotations.mjs';

const ann = (entity_id, label, start = 0) => ({ start, end: start + 4, entity_id, entity_type: 'character', label });

test('a response is merged into the known spans, older messages kept', () => {
	const prev = { m1: [ann('a', 'Ana')], m2: [ann('b', 'Bo')] };
	const response = [
		{ message_id: 'm3', sequence: 3, annotations: [ann('c', 'Cy')] },
		{ message_id: 'm2', sequence: 2, annotations: [ann('b', 'Bob')] },
	];
	assert.deepEqual(mergeSpans(prev, response, ['m1', 'm2', 'm3']), {
		m1: [ann('a', 'Ana')],
		m2: [ann('b', 'Bob')],
		m3: [ann('c', 'Cy')],
	});
});

test('messages no longer in the chat are purged, by the chat ids', () => {
	const prev = { m1: [ann('a', 'Ana')], m2: [ann('b', 'Bo')] };
	assert.deepEqual(mergeSpans(prev, [], ['m1']), { m1: [ann('a', 'Ana')] });
	// The chat not loaded yet (no ids): nothing is dropped.
	assert.equal(purgeSpans(prev, []), prev);
	// Nothing to drop: the same object, so no re-render.
	assert.equal(purgeSpans(prev, ['m1', 'm2', 'm9']), prev);
});

test('a merge made before a rollback is purged again by the chat ids of commit time', () => {
	const response = [{ message_id: 'm2', sequence: 2, annotations: [ann('b', 'Bo')] }];
	const merged = mergeSpans({ m1: [ann('a', 'Ana')] }, response, ['m1', 'm2']);
	// m2 rolled back while the tooltips were fetched.
	assert.deepEqual(purgeSpans(merged, ['m1']), { m1: [ann('a', 'Ana')] });
});

test('the signature changes with a label, not with the order', () => {
	const one = { m1: [ann('a', 'Ana')], m2: [ann('b', 'Bo')] };
	const reordered = { m2: [ann('b', 'Bo')], m1: [ann('a', 'Ana')] };
	assert.equal(spansSignature(one), spansSignature(reordered));
	assert.notEqual(spansSignature(one), spansSignature({ ...one, m2: [ann('b', 'Bob')] }));
});

test('only new ids and renamed entities are fetched; the cache follows the spans', () => {
	const spans = { m1: [ann('a', 'Ana'), ann('b', 'Bob', 10)], m2: [ann('c', 'Cy')] };
	const cache = {
		a: { label: 'Ana', tooltip: { name: 'Ana' } },
		b: { label: 'Bo', tooltip: { name: 'Bo' } },
		z: { label: 'Zed', tooltip: { name: 'Zed' } },
	};
	const labels = latestLabels([{ message_id: 'm1', annotations: spans.m1 }]);
	assert.deepEqual(idsToFetch(spans, cache, labels).sort(), ['b', 'c']);
	// An entity seen only in an older page keeps its cached tooltip.
	assert.deepEqual(idsToFetch(spans, { ...cache, c: { label: 'Cy', tooltip: {} } }, {}), []);
	assert.deepEqual(Object.keys(pruneCache(cache, spans)).sort(), ['a', 'b']);
	assert.deepEqual(tooltipMapOf({ a: cache.a }), { a: { name: 'Ana' } });
});

test('ids are sent in chunks of the backend cap', () => {
	assert.deepEqual(chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
	assert.deepEqual(chunks([], 2), []);
});
