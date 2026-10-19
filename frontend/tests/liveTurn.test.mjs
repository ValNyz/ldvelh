import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
	TURN_STATUS, TURN_KIND, startLiveTurn, nextTurnStatus, withTurnEvent, turnActivity,
	withChunk, withExtracting, withAnswer, withLiveTurn, reopenTurn,
} from '../lib/game/liveTurn.mjs';

const history = [
	{ id: 'u1', role: 'user', content: 'Je regarde autour de moi.' },
	{ id: 'a1', role: 'assistant', content: 'Le hangar est désert.' },
];
const committed = [...history, { id: 'u2', role: 'user', content: 'Je sors.' }, { id: 'a2', role: 'assistant', content: 'Il pleut.' }];
const IDS = { user_message_id: 'u2', assistant_message_id: 'a2' };
const GAME_STATE = { game: { current_location: 'Quai' } };
const action = (text = 'Je sors.') => startLiveTurn('g1', { playerMessage: text });

// A turn fed the stream events of an answer, as the orchestrator does.
function streamed(turn, text) {
	let out = withTurnEvent(turn, 'chunk', { edit: m => withChunk(m, text.slice(0, 4)) });
	return withTurnEvent(out, 'chunk', { edit: m => withChunk(m, text.slice(4)) });
}
const extracted = (turn, text) => withTurnEvent(streamed(turn, text), 'extracting', { edit: m => withExtracting(m, text) });
const answered = (turn, text, data = { meta: IDS, game_state: GAME_STATE }) =>
	withTurnEvent(streamed(turn, text), 'done', { edit: m => withAnswer(m, text, data), gameState: data.game_state });

// ---------------------------------------------------------------------------
// Turn data
// ---------------------------------------------------------------------------

test('a turn starts with the action shown, none for a protocol turn', () => {
	const turn = action();
	assert.equal(turn.gameId, 'g1');
	assert.equal(turn.kind, TURN_KIND.ACTION);
	assert.deepEqual(turn.messages, [{ role: 'user', content: 'Je sors.' }]);
	assert.equal(turn.status, TURN_STATUS.STREAMING);
	assert.deepEqual(startLiveTurn('g1', { kind: TURN_KIND.INIT }).messages, []);
});

test('status follows the stream events', () => {
	const s = TURN_STATUS;
	assert.equal(nextTurnStatus(s.STREAMING, 'chunk'), s.STREAMING);
	assert.equal(nextTurnStatus(s.STREAMING, 'progress'), s.STREAMING);
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

test('an event moves the status, edits the messages and keeps what it carried', () => {
	const turn = action();
	const out = withTurnEvent(turn, 'done', { edit: m => [...m, { role: 'assistant', content: 'Il pleut.' }], gameState: GAME_STATE });
	assert.equal(out.status, TURN_STATUS.SAVING);
	assert.equal(out.gameState, GAME_STATE);
	assert.equal(out.messages.length, 2);
	assert.equal(turn.status, TURN_STATUS.STREAMING); // not mutated
	assert.equal(withTurnEvent(turn, 'progress', { progress: '{"world"' }).progress, '{"world"');
	assert.equal(withTurnEvent(turn, 'cancel').status, TURN_STATUS.DROPPED);
});

test('activity of an action follows its status; no turn: free to send', () => {
	const activity = (status) => turnActivity({ ...action(), status });
	assert.deepEqual(activity(TURN_STATUS.STREAMING), { loading: true, sending: true, extracting: false, saving: true });
	assert.deepEqual(activity(TURN_STATUS.EXTRACTING), { loading: true, sending: true, extracting: true, saving: true });
	assert.deepEqual(activity(TURN_STATUS.SAVING), { loading: false, sending: false, extracting: false, saving: true });
	const idle = { loading: false, sending: false, extracting: false, saving: false };
	assert.deepEqual(activity(TURN_STATUS.ENDED), idle);
	assert.deepEqual(activity(TURN_STATUS.DROPPED), idle);
	assert.deepEqual(turnActivity(null), idle);
});

test('activity of a protocol turn: loading only, as when it started', () => {
	const init = startLiveTurn('g1', { kind: TURN_KIND.INIT });
	assert.deepEqual(turnActivity(init), { loading: true, sending: false, extracting: false, saving: false });
	assert.deepEqual(turnActivity({ ...init, status: TURN_STATUS.SAVING }), { loading: false, sending: false, extracting: false, saving: true });
});

// ---------------------------------------------------------------------------
// Message reducers
// ---------------------------------------------------------------------------

test('chunks build one streaming answer; the roll goes on its first chunk', () => {
	const roll = { total: 3 };
	let messages = withChunk([{ role: 'user', content: 'Je saute.' }], 'Tu ', roll);
	messages = withChunk(messages, 'sautes.', { total: 9 });
	assert.deepEqual(messages[1], { role: 'assistant', content: 'Tu sautes.', streaming: true, roll });
	assert.equal(messages.length, 2);
});

test('extracting shows the final text; without an answer: unchanged', () => {
	assert.deepEqual(withExtracting(withChunk([], 'Tu sau'), 'Tu sautes.').at(-1),
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
	const live = withChunk([...committed, { role: 'user', content: 'Je sors.' }], 'Il pleut.');
	assert.deepEqual(withAnswer(live, 'Il pleut.', { meta: IDS }), committed);
});

test('done on a chat that shows only the committed turn: unchanged', () => {
	assert.equal(withAnswer(committed, 'Il pleut.', { meta: IDS }), committed);
});

// ---------------------------------------------------------------------------
// Reloaded history + live turn
// ---------------------------------------------------------------------------

test('reopened while the turn streams: history, then the action and the answer so far', () => {
	const turn = withTurnEvent(action(), 'chunk', { edit: m => withChunk(m, 'Il ple') });
	assert.deepEqual(withLiveTurn(history, turn),
		[...history, { role: 'user', content: 'Je sors.' }, { role: 'assistant', content: 'Il ple', streaming: true }]);
	assert.deepEqual(withLiveTurn(history, action()), [...history, { role: 'user', content: 'Je sors.' }]);
});

test('reopened after done: the answered pair keeps its ids, so Régénérer targets this action', () => {
	const out = withLiveTurn(history, answered(action(), 'Il pleut.'));
	assert.deepEqual(out.slice(2).map(m => [m.role, m.id, m.content]), [['user', 'u2', 'Je sors.'], ['assistant', 'a2', 'Il pleut.']]);
});

test('the history already holds the committed turn (by id): not shown twice', () => {
	assert.equal(withLiveTurn(committed, answered(action(), 'Il pleut.')), committed);
});

test('extracting, ids not known yet, history already ending with that action and answer: not shown twice', () => {
	assert.equal(withLiveTurn(committed, extracted(action(), 'Il pleut.')), committed);
	// A different answer, or an answer still streaming, is not the committed one.
	assert.notEqual(withLiveTurn(committed, extracted(action(), 'Il neige.')), committed);
	assert.notEqual(withLiveTurn(committed, streamed(action(), 'Il pleut.')), committed);
	// Same answer after another action: not this turn.
	assert.notEqual(withLiveTurn(committed, extracted(action('Je reste.'), 'Il pleut.')), committed);
});

test('dropped turn: nothing again, except the action of a failed turn', () => {
	const dropped = withTurnEvent(streamed(action(), 'Il pleut.'), 'roll_pending');
	assert.equal(withLiveTurn(history, dropped), history);
	const failed = withTurnEvent(streamed(action(), 'Il pleut.'), 'error', { error: { message: 'Échec.' } });
	assert.deepEqual(withLiveTurn(history, failed), [...history, { role: 'user', content: 'Je sors.' }]);
	assert.equal(withLiveTurn(history, withTurnEvent(startLiveTurn('g1', { kind: TURN_KIND.INIT }), 'error', { error: { message: 'x' } })), history);
});

test('nothing to show: no turn, protocol turn without answer yet', () => {
	assert.equal(withLiveTurn(history, null), history);
	assert.equal(withLiveTurn(history, startLiveTurn('g1', { kind: TURN_KIND.ARRIVAL })), history);
});

test('the unsaved action of a pending roll is not repeated by its resumed turn', () => {
	const withPending = [...history, { role: 'user', content: 'Je saute.' }];
	const turn = withTurnEvent(action('Je saute.'), 'chunk', { edit: m => withChunk(m, 'Tu ') });
	assert.deepEqual(withLiveTurn(withPending, turn).map(m => m.content),
		['Je regarde autour de moi.', 'Le hangar est désert.', 'Je saute.', 'Tu ']);
});

// ---------------------------------------------------------------------------
// Reopening a game
// ---------------------------------------------------------------------------

test('reopen without a live turn: the load as is', () => {
	const plan = reopenTurn(history, null);
	assert.equal(plan.messages, history);
	assert.equal(plan.attached, false);
	assert.equal(plan.action, null);
	assert.equal(plan.gameState, null);
	assert.equal(plan.error, null);
	assert.equal(plan.refresh, false);
});

test('reopen while an action streams: attached, busy, its action to retry', () => {
	const plan = reopenTurn(history, streamed(action(), 'Il pleut.'));
	assert.equal(plan.attached, true);
	assert.equal(plan.activity.loading, true);
	assert.equal(plan.activity.sending, true);
	assert.equal(plan.action, 'Je sors.');
	assert.equal(plan.gameState, null);
	assert.equal(plan.messages.length, 4);
});

test('done (and saved) during a load read before the commit: its state wins, refresh once saved', () => {
	const done = answered(action(), 'Il pleut.');
	const plan = reopenTurn(history, done);
	assert.equal(plan.attached, true);
	assert.equal(plan.gameState, GAME_STATE);
	assert.equal(plan.refresh, false);
	assert.equal(plan.activity.saving, true);
	const saved = reopenTurn(history, withTurnEvent(done, 'saved'));
	assert.equal(saved.gameState, GAME_STATE);
	assert.equal(saved.refresh, true);
	assert.equal(saved.activity.saving, false);
});

test('load read after the commit: the load wins, nothing replayed', () => {
	const plan = reopenTurn(committed, withTurnEvent(answered(action(), 'Il pleut.'), 'saved'));
	assert.equal(plan.messages, committed);
	assert.equal(plan.attached, false);
	assert.equal(plan.gameState, null);
	assert.equal(plan.refresh, false);
});

test('a turn that failed while the game was closed: its action and its error come back', () => {
	const error = { message: 'Le narrateur a échoué.', recoverable: false };
	const plan = reopenTurn(history, withTurnEvent(action(), 'error', { error }));
	assert.equal(plan.error, error);
	assert.equal(plan.action, 'Je sors.');
	assert.equal(plan.attached, false);
	assert.deepEqual(plan.activity, turnActivity(null));
	assert.equal(plan.messages.at(-1).content, 'Je sors.');
});

test('the warning of the turn comes back with it', () => {
	const plan = reopenTurn(history, withTurnEvent(answered(action(), 'Il pleut.'), 'save_unconfirmed', { warning: 'Non confirmé.' }));
	assert.equal(plan.warning, 'Non confirmé.');
	assert.equal(reopenTurn(committed, withTurnEvent(answered(action(), 'Il pleut.'), 'save_unconfirmed', { warning: 'x' })).warning, null);
});

test('reopen while the world generation runs: its progress and director step come back', () => {
	let init = startLiveTurn('g1', { kind: TURN_KIND.INIT });
	init = withTurnEvent(init, 'progress', { progress: '{"world":{"name":"Kira"' });
	init = withTurnEvent(init, 'status', { director: { status: 'running', label: 'Scénario' } });
	const plan = reopenTurn([], init);
	assert.equal(plan.attached, true);
	assert.deepEqual(plan.generating, { progress: '{"world":{"name":"Kira"', director: { status: 'running', label: 'Scénario' } });
	assert.equal(plan.activity.loading, true);
	assert.equal(plan.world, null);
});

test('world generation done after the load was read: the world comes back, unless the load has it', () => {
	const info = { world: { name: 'Kira' } };
	const done = withTurnEvent(startLiveTurn('g1', { kind: TURN_KIND.INIT }), 'done', { world: info, gameState: GAME_STATE });
	assert.deepEqual(reopenTurn([], done).world, { info, gameState: GAME_STATE });
	assert.equal(reopenTurn([], done).generating, null);
	assert.equal(reopenTurn([], done, { worldCreated: true }).world, null);
	assert.equal(reopenTurn([], done, { worldCreated: true }).attached, false);
});

test('reopen while the arrival runs: starting, with its narration so far', () => {
	const arrival = startLiveTurn('g1', { kind: TURN_KIND.ARRIVAL });
	const plan = reopenTurn([], arrival);
	assert.equal(plan.starting, true);
	assert.equal(plan.attached, true);
	assert.deepEqual(plan.messages, []);
	const chunked = reopenTurn([], withTurnEvent(arrival, 'chunk', { edit: m => withChunk(m, 'Bienvenue') }));
	assert.equal(chunked.starting, true);
	assert.equal(chunked.messages[0].content, 'Bienvenue');
	assert.equal(chunked.action, null);
});
