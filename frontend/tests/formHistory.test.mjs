import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	COALESCE_MS, HISTORY_LIMIT, changeKey, createHistory, push, redo, redoMeta, undo, undoMeta,
} from '../lib/game/formHistory.mjs';

test('undo and redo walk the entries', () => {
	let h = createHistory('a');
	h = push(h, 'b', { at: 0 });
	h = push(h, 'c', { at: 5000 });
	h = undo(h);
	assert.equal(h.present, 'b');
	h = undo(h);
	assert.equal(h.present, 'a');
	assert.equal(undo(h), h, 'nothing left to undo');
	h = redo(redo(h));
	assert.equal(h.present, 'c');
	assert.equal(redo(h), h, 'nothing left to redo');
});

test('a new change after undo drops the redo branch', () => {
	let h = push(push(createHistory(1), 2, { at: 0 }), 3, { at: 5000 });
	h = push(undo(h), 4, { at: 9000 });
	assert.deepEqual(h.future, []);
	assert.equal(undo(h).present, 2);
});

test('same key within the window merges (typing), other keys do not', () => {
	let h = createHistory('');
	h = push(h, 'h', { key: 'lore', at: 0 });
	h = push(h, 'he', { key: 'lore', at: 300 });
	h = push(h, 'hey', { key: 'lore', at: 600 });
	assert.equal(h.past.length, 1);
	h = push(h, 'hey!', { key: 'lore', at: 600 + COALESCE_MS });
	assert.equal(h.past.length, 2, 'pause starts a new entry');
	h = push(h, 'x', { key: 'genre', at: 1700 });
	assert.equal(h.past.length, 3);
	h = push(h, 'y', { key: null, at: 1701 });
	h = push(h, 'z', { key: null, at: 1702 });
	assert.equal(h.past.length, 5, 'null key (AI fill) never merges');
});

test('typing right after an undo starts a new entry', () => {
	let h = push(createHistory(''), 'a', { key: 'lore', at: 0 });
	h = undo(h);
	h = push(h, 'b', { key: 'lore', at: 10 });
	assert.equal(undo(h).present, '');
});

test('identical state is not recorded', () => {
	const h = createHistory({ a: 1 });
	assert.equal(push(h, h.present), h);
});

test('history is capped', () => {
	let h = createHistory(0);
	for (let i = 1; i <= HISTORY_LIMIT + 20; i++) h = push(h, i, { at: i * 10_000 });
	assert.equal(h.past.length, HISTORY_LIMIT);
});

test('meta tells which step an undo or redo changes', () => {
	let h = push(createHistory('a'), 'b', { at: 0, meta: 1 });
	h = push(h, 'c', { at: 5000, meta: 2 });
	assert.equal(undoMeta(h), 2);
	h = undo(h);
	assert.equal(redoMeta(h), 2);
	assert.equal(undoMeta(h), 1);
	assert.equal(undoMeta(createHistory('a')), null);
});

test('changeKey names the one field that changed', () => {
	const prev = { worldConfig: { lore: 'a', genre: 'sci_fi' }, engine: 'none' };
	assert.equal(changeKey(prev, { ...prev, worldConfig: { ...prev.worldConfig, lore: 'ab' } }),
		'worldConfig.lore');
	assert.equal(changeKey(prev, { ...prev, engine: 'd6' }), 'engine');
	assert.equal(changeKey(prev, { ...prev, worldConfig: { lore: 'b', genre: 'cyberpunk' } }), null);
	assert.equal(changeKey(prev, { worldConfig: { lore: 'b', genre: 'sci_fi' }, engine: 'd6' }), null);
});
