import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	baseOf, isAiValue, isSuggestion, markSuggestions, rememberFill, withoutSuggestions,
} from '../lib/game/enhanceBase.mjs';

test('a re-roll starts from the player text, not the AI version', () => {
	const typed = { genre: 'sci_fi', lore: 'pluie, corpo' };
	const ai1 = { genre: 'cyberpunk', lore: 'Néo-Lyon sous la pluie…' };
	let fills = rememberFill([], typed, ai1);
	assert.deepEqual(baseOf(fills, ai1), typed);
	// Second fill was sent the base, so a third click still starts from the typed text
	const ai2 = { genre: 'cyberpunk', lore: 'Une autre version…' };
	fills = rememberFill(fills, baseOf(fills, ai1), ai2);
	assert.deepEqual(baseOf(fills, ai2), typed);
	// Undo back to the first AI version: still the typed text
	assert.deepEqual(baseOf(fills, ai1), typed);
});

test('a field the player edited after the fill is theirs', () => {
	const fills = rememberFill([], { lore: 'pluie', genre: 'sci_fi' }, { lore: 'IA', genre: 'cyberpunk' });
	assert.deepEqual(baseOf(fills, { lore: 'IA, retouché', genre: 'cyberpunk' }),
		{ lore: 'IA, retouché', genre: 'sci_fi' });
});

test('a field the AI added is dropped from the base (an invented name is invented again)', () => {
	const fills = rememberFill([], { description: '' }, { description: 'Pilote', name: 'Nyx' });
	assert.deepEqual(baseOf(fills, { description: 'Pilote', name: 'Nyx' }), { description: '' });
	assert.deepEqual(baseOf([], { name: 'Nyx' }), { name: 'Nyx' });
});

test('isAiValue tells an AI text from the player text', () => {
	const fills = rememberFill([], { lore: 'pluie' }, { lore: 'IA' });
	assert.equal(isAiValue(fills, 'lore', 'IA'), true);
	assert.equal(isAiValue(fills, 'lore', 'pluie'), false);
	assert.equal(isAiValue(fills, 'lore', 'autre'), false);
});

test('suggestions are marked, and unedited ones are left out of the next request', () => {
	const sent = { npcs: [{ name: 'Rook', description: 'à moi' }] };
	const result = { npcs: [{ name: 'Rook', description: 'à moi' }, { name: 'Vex', description: 'IA' }], locations: [] };
	const marked = markSuggestions(result, sent);
	assert.equal(isSuggestion(marked.npcs[0]), false);
	assert.equal(isSuggestion(marked.npcs[1]), true);
	assert.deepEqual(withoutSuggestions(marked), { npcs: [{ name: 'Rook', description: 'à moi' }], locations: [] });
	// Edited: the player's, kept in the next request
	const edited = { ...marked.npcs[1], description: 'IA, retouché' };
	assert.equal(isSuggestion(edited), false);
	assert.equal(withoutSuggestions({ npcs: [edited] }).npcs.length, 1);
	assert.deepEqual(withoutSuggestions(undefined), {});
});
