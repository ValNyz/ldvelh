import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	TURN_STATUS, startLiveTurn, nextTurnStatus, turnActivity,
	withChunk, withExtracting, withAnswer, withLiveTurn,
} from '../lib/game/liveTurn.mjs';

const history = [
	{ id: 'u1', role: 'user', content: 'Je regarde autour de moi.' },
	{ id: 'a1', role: 'assistant', content: 'Le hangar est désert.' },
];
const IDS = { user_message_id: 'u2', assistant_message_id: 'a2' };

// A turn fed the events of a whole answer, as the orchestrator does.
function answered(turn, text, data = { meta: IDS }) {
	let messages = withChunk(turn.messages, text.slice(0, 4));
	messages = withChunk(messages, text.slice(4));
	return { ...turn, messages: withAnswer(messages, text, data), status: TURN_STATUS.SAVING };
}

test('a turn starts with the action shown, none for a protocol token', () => {
	assert.deepEqual(startLiveTurn('g1', 'Je sors.'), {
		gameId: 'g1', messages: [{ role: 'user', content: 'Je sors.' }], status: TURN_STATUS.STREAMING, roll: null,
	});
	assert.deepEqual(startLiveTurn('g1').messages, []);
});

test('status follows the stream events', () => {
	const s = TURN_STATUS;
	assert.equal(nextTurnStatus(s.STREAMING, 'chunk'), s.STREAMING);
	assert.equal(nextTurnStatus(s.STREAMING, 'extracting'), s.EXTRACTING);
	assert.equal(nextTurnStatus(s.EXTRACTING, 'done'), s.SAVING);
	assert.equal(nextTurnStatus(s.SAVING, 'saved'), s.ENDED);
	assert.equal(nextTurnStatus(s.SAVING, 'save_unconfirmed'), s.ENDED);
	assert.equal(nextTurnStatus(s.STREAMING, 'error'), s.DROPPED);
	assert.equal(nextTurnStatus(s.STREAMING, 'roll_pending'), s.DROPPED);
	assert.equal(nextTurnStatus(s.STREAMING, 'cancel'), s.DROPPED);
});

test('an error or a cancel after done keeps the committed turn', () => {
	assert.equal(nextTurnStatus(TURN_STATUS.SAVING, 'error'), TURN_STATUS.SAVING);
	assert.equal(nextTurnStatus(TURN_STATUS.ENDED, 'error'), TURN_STATUS.ENDED);
	assert.equal(nextTurnStatus(TURN_STATUS.SAVING, 'cancel'), TURN_STATUS.SAVING);
});

test('activity of the reopened game follows its turn; no turn: free to send', () => {
	const activity = (status) => turnActivity({ status });
	assert.deepEqual(activity(TURN_STATUS.STREAMING), { loading: true, sending: true, extracting: false, saving: true });
	assert.deepEqual(activity(TURN_STATUS.EXTRACTING), { loading: true, sending: true, extracting: true, saving: true });
	assert.deepEqual(activity(TURN_STATUS.SAVING), { loading: false, sending: false, extracting: false, saving: true });
	const idle = { loading: false, sending: false, extracting: false, saving: false };
	assert.deepEqual(activity(TURN_STATUS.ENDED), idle);
	assert.deepEqual(activity(TURN_STATUS.DROPPED), idle);
	assert.deepEqual(turnActivity(null), idle);
});

test('chunks build one streaming answer; the roll goes on its first chunk', () => {
	const roll = { total: 3 };
	let messages = withChunk([{ role: 'user', content: 'Je saute.' }], 'Tu ', roll);
	messages = withChunk(messages, 'sautes.', { total: 9 });
	assert.deepEqual(messages[1], { role: 'assistant', content: 'Tu sautes.', streaming: true, roll });
	assert.equal(messages.length, 2);
});

test('extracting shows the final text; without an answer: unchanged', () => {
	const messages = withChunk([], 'Tu sau');
	assert.deepEqual(withExtracting(messages, 'Tu sautes.').at(-1),
		{ role: 'assistant', content: 'Tu sautes.', streaming: false, extracting: true });
	const users = [{ role: 'user', content: 'Je sors.' }];
	assert.equal(withExtracting(users, 'x'), users);
});

test('done: final answer with the turn details and both ids', () => {
	const live = withChunk([...history, { role: 'user', content: 'Je sors.' }], 'Il pleut');
	const data = { meta: { ...IDS, narration_cost: 0.01 }, game_state: { game: { current_cycle: 2, current_location: 'Quai' } } };
	const out = withAnswer(live, 'Il pleut.', data);
	assert.deepEqual(out.at(-2), { role: 'user', content: 'Je sors.', id: 'u2' });
	assert.equal(out.at(-1).content, 'Il pleut.');
	assert.equal(out.at(-1).id, 'a2');
	assert.equal(out.at(-1).streaming, false);
	assert.equal(out.at(-1).cycle, 2);
	assert.equal(out.at(-1).location, 'Quai');
	assert.equal(out.at(-1).cost, 0.01);
});

test('done on a chat reloaded after the commit: the live copy is dropped', () => {
	const committed = [...history, { id: 'u2', role: 'user', content: 'Je sors.' }, { id: 'a2', role: 'assistant', content: 'Il pleut.' }];
	const live = withChunk([...committed, { role: 'user', content: 'Je sors.' }], 'Il pleut.');
	assert.deepEqual(withAnswer(live, 'Il pleut.', { meta: IDS }), committed);
});

test('reopened while the turn streams: history, then the action and the answer so far', () => {
	const turn = { ...startLiveTurn('g1', 'Je sors.'), messages: withChunk([{ role: 'user', content: 'Je sors.' }], 'Il ple') };
	const out = withLiveTurn(history, turn);
	assert.deepEqual(out, [...history, { role: 'user', content: 'Je sors.' }, { role: 'assistant', content: 'Il ple', streaming: true }]);
	assert.deepEqual(withLiveTurn(history, startLiveTurn('g1', 'Je sors.')), [...history, { role: 'user', content: 'Je sors.' }]);
});

test('reopened after done: the answered pair keeps its ids, so Régénérer targets this action', () => {
	const turn = answered(startLiveTurn('g1', 'Je sors.'), 'Il pleut.');
	const out = withLiveTurn(history, turn);
	assert.deepEqual(out.slice(2).map(m => [m.role, m.id, m.content]), [['user', 'u2', 'Je sors.'], ['assistant', 'a2', 'Il pleut.']]);
});

test('the history already holds the committed turn: not shown twice', () => {
	const turn = answered(startLiveTurn('g1', 'Je sors.'), 'Il pleut.');
	const committed = [...history, { id: 'u2', role: 'user', content: 'Je sors.' }, { id: 'a2', role: 'assistant', content: 'Il pleut.' }];
	assert.equal(withLiveTurn(committed, turn), committed);
});

test('nothing to show again: dropped turn, no turn, protocol token without answer yet', () => {
	assert.equal(withLiveTurn(history, { ...startLiveTurn('g1', 'Je sors.'), status: TURN_STATUS.DROPPED }), history);
	assert.equal(withLiveTurn(history, null), history);
	assert.equal(withLiveTurn(history, startLiveTurn('g1')), history);
});

test('the unsaved action of a pending roll is not repeated by its resumed turn', () => {
	const withPending = [...history, { role: 'user', content: 'Je saute.' }];
	const turn = { ...startLiveTurn('g1', 'Je saute.'), messages: withChunk([{ role: 'user', content: 'Je saute.' }], 'Tu ') };
	const out = withLiveTurn(withPending, turn);
	assert.deepEqual(out.map(m => m.content), ['Je regarde autour de moi.', 'Le hangar est désert.', 'Je saute.', 'Tu ']);
});
