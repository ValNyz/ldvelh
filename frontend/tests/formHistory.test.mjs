import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	HISTORY_LIMIT, changeKey, createHistory, push, redo, redoMeta, undo, undoMeta,
} from '../lib/game/formHistory.mjs';

test('undo and redo walk the entries', () => {
	let h = createHistory('a');
	h = push(h, 'b');
	h = push(h, 'c');
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
	let h = push(push(createHistory(1), 2), 3);
	h = push(undo(h), 4);
	assert.deepEqual(h.future, []);
	assert.equal(undo(h).present, 2);
});

test('consecutive edits of the same field merge, whatever the pause', () => {
	let h = createHistory('');
	h = push(h, 'h', { key: 'lore' });
	h = push(h, 'he', { key: 'lore' });
	h = push(h, 'hey', { key: 'lore' });
	assert.equal(h.past.length, 1);
	h = push(h, 'x', { key: 'genre' });
	assert.equal(h.past.length, 2, 'another field starts a new entry');
	h = push(h, 'xy', { key: 'lore' });
	assert.equal(h.past.length, 3, 'back to the first field: a new entry too');
	h = push(h, 'y', { key: null });
	h = push(h, 'z', { key: null });
	assert.equal(h.past.length, 5, 'null key (AI fill) never merges');
});

test('a merged edit that comes back to its start leaves no entry', () => {
	let h = push(createHistory({ n: 1 }), { n: 0 }, { key: 'x' });   // older entry
	h = push(h, { n: 2 }, { key: 'n' });
	h = push(h, { n: 0 }, { key: 'n' });                        // "+" then "-"
	assert.equal(h.past.length, 1);
	assert.deepEqual(undo(h).present, { n: 1 });
});

test('typing right after an undo starts a new entry', () => {
	let h = push(createHistory(''), 'a', { key: 'lore' });
	h = undo(h);
	h = push(h, 'b', { key: 'lore' });
	assert.equal(undo(h).present, '');
});

test('identical state is not recorded', () => {
	const h = createHistory({ a: 1 });
	assert.equal(push(h, h.present), h);
});

test('history is capped', () => {
	let h = createHistory(0);
	for (let i = 1; i <= HISTORY_LIMIT + 20; i++) h = push(h, i);
	assert.equal(h.past.length, HISTORY_LIMIT);
});

test('meta tells which step an undo or redo changes', () => {
	let h = push(createHistory('a'), 'b', { meta: 1 });
	h = push(h, 'c', { meta: 2 });
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

test('changeKey follows nested skills and entity fields down to the leaf', () => {
	const prev = {
		characterData: { skills: { Piratage: '1D', Esquive: '1D' } },
		manualEntities: { npcs: [{ name: 'Ro', description: '' }] },
	};
	const skill = v => ({ ...prev, characterData: { skills: { ...prev.characterData.skills, ...v } } });
	assert.equal(changeKey(prev, skill({ Piratage: '1D+1' })), 'characterData.skills.Piratage');
	assert.equal(changeKey(prev, skill({ Cybernétique: '1D' })), 'characterData.skills.Cybernétique');
	assert.equal(changeKey(prev, skill({ Piratage: '2D', Esquive: '2D' })), null);
	const npcs = list => ({ ...prev, manualEntities: { npcs: list } });
	assert.equal(changeKey(prev, npcs([{ name: 'Rook', description: '' }])), 'manualEntities.npcs.0.name');
	assert.equal(changeKey(prev, npcs([...prev.manualEntities.npcs, { name: '', description: '' }])),
		'manualEntities.npcs', 'adding an entity is a change of the list');
});
