import { test } from 'node:test';
import assert from 'node:assert/strict';

import { findLastUserMessage, withTurnIds } from '../lib/game/chatHistory.mjs';

const history = [
	{ id: 'u1', role: 'user', content: 'Je regarde autour de moi.' },
	{ id: 'a1', role: 'assistant', content: 'Le hangar est désert.' },
	{ id: 'u2', role: 'user', content: 'Je sors.' },
	{ id: 'a2', role: 'assistant', content: 'Il pleut.' },
];

test('the last user message is found scanning backwards', () => {
	assert.equal(findLastUserMessage(history), history[2]);
	assert.equal(findLastUserMessage(history.slice(0, 3)), history[2]);
});

test('no user message: null', () => {
	assert.equal(findLastUserMessage([]), null);
	assert.equal(findLastUserMessage([{ role: 'assistant', content: 'Bienvenue.' }]), null);
});

test('the turn ids go on the answer and on the action just before it', () => {
	const live = [...history.slice(0, 2), { role: 'user', content: 'Je sors.' }, { role: 'assistant', content: 'Il pleut.' }];
	const out = withTurnIds(live, { user_message_id: 'u2', assistant_message_id: 'a2' });
	assert.equal(out[2].id, 'u2');
	assert.equal(out[3].id, 'a2');
	assert.equal(out[0], live[0]);
	assert.equal(live[3].id, undefined); // not mutated
});

test('arrival: no action before the answer, only the answer gets its id', () => {
	const out = withTurnIds([{ role: 'assistant', content: 'Bienvenue.' }],
		{ user_message_id: 'u0', assistant_message_id: 'a0' });
	assert.deepEqual(out, [{ role: 'assistant', content: 'Bienvenue.', id: 'a0' }]);
});

test('no ids in the done payload: unchanged', () => {
	assert.equal(withTurnIds(history, null), history);
	assert.equal(withTurnIds(history, {}), history);
});
