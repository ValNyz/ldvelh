import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildChatPayload } from '../lib/game/chatRequest.mjs';

const GAME = '00000000-0000-0000-0000-000000000001';

test('the body carries the game and the chosen provider and model', () => {
	const body = buildChatPayload({ gameId: GAME, preferences: { activeProvider: 'openai', activeModel: 'gpt-x' } },
		{ message: 'Je regarde.' });
	assert.deepEqual(body, { gameId: GAME, provider: 'openai', model: 'gpt-x', message: 'Je regarde.' });
});

test('without preferences: anthropic and the server default model', () => {
	const body = buildChatPayload({ gameId: GAME, preferences: null }, { message: 'x' });
	assert.equal(body.provider, 'anthropic');
	assert.equal(body.model, null);
});

test('extra fields are kept (roll resume, wizard parameters)', () => {
	const body = buildChatPayload({ gameId: GAME }, { message: 'x', roll_id: 'r1', invoked_aspects: [] });
	assert.equal(body.roll_id, 'r1');
	assert.deepEqual(body.invoked_aspects, []);
});

test('the client game state is never sent (the server reloads it, #55)', () => {
	const body = buildChatPayload({ gameId: GAME }, { message: 'x' });
	assert.equal('gameState' in body, false);
});
