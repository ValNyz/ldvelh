import { test } from 'node:test';
import assert from 'node:assert/strict';

import { invocationFromState, toInvocationData, withPendingPlayerMessage } from '../lib/game/pendingRoll.mjs';

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

test('waiting action already shown before the optimistic message: no duplicate (#80)', () => {
	const shown = [
		...history.slice(0, 2),
		{ role: 'user', content: 'Je tente un saut impossible.' },
		{ role: 'user', content: 'Je fais autre chose.' },
	];
	const out = withPendingPlayerMessage(shown, 'Je tente un saut impossible.');
	assert.deepEqual(out, shown.slice(0, 3));
	assert.equal(shown.length, 4); // not mutated
});

test('an earlier, non-adjacent identical message does not drop the optimistic one', () => {
	const earlier = [
		{ role: 'user', content: 'Je tente un saut impossible.' },
		{ role: 'assistant', content: 'Raté.' },
		{ role: 'user', content: 'Je fais autre chose.' },
	];
	const out = withPendingPlayerMessage(earlier, 'Je tente un saut impossible.');
	assert.equal(out.length, 3);
	assert.equal(out.at(-1).content, 'Je tente un saut impossible.');
});

test('invocation data follows the pending roll of a state (#80)', () => {
	const pending = { roll_id: 'r1', roll: { total: -2 }, aspects: ['A'], fate_points: 2 };
	assert.deepEqual(invocationFromState({ pending_roll: pending }),
		{ rollId: 'r1', roll: { total: -2 }, aspects: ['A'], fatePoints: 2 });
	assert.deepEqual(toInvocationData(pending), invocationFromState({ pending_roll: pending }));
	assert.equal(invocationFromState({ pending_roll: null }), null);
	assert.equal(invocationFromState(undefined), null);
});
