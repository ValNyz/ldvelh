import { test } from 'node:test';
import assert from 'node:assert/strict';

import { withPendingPlayerMessage } from '../lib/game/pendingRoll.mjs';

const history = [
	{ role: 'user', content: 'Je regarde autour de moi.' },
	{ role: 'assistant', content: 'Le hangar est désert.' },
	{ role: 'user', content: 'Je fais autre chose.' },
];

test('the optimistic message is replaced by the action the roll belongs to', () => {
	const out = withPendingPlayerMessage(history, 'Je tente un saut impossible.');
	assert.deepEqual(out.at(-1), { role: 'user', content: 'Je tente un saut impossible.' });
	assert.deepEqual(out.slice(0, -1), history.slice(0, -1));
	assert.equal(history.at(-1).content, 'Je fais autre chose.'); // not mutated
});

test('same message or no stored message: unchanged', () => {
	assert.equal(withPendingPlayerMessage(history, 'Je fais autre chose.'), history);
	assert.equal(withPendingPlayerMessage(history, undefined), history);
	assert.equal(withPendingPlayerMessage(history, ''), history);
});

test('only the last user message is touched', () => {
	const endsWithAssistant = history.slice(0, 2);
	const out = withPendingPlayerMessage(endsWithAssistant, 'Je saute.');
	assert.deepEqual(out, [{ role: 'user', content: 'Je saute.' }, endsWithAssistant[1]]);
	assert.equal(withPendingPlayerMessage([], 'Je saute.').length, 0);
});
