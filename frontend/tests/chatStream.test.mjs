import { test } from 'node:test';
import assert from 'node:assert/strict';

import { STREAM_INTERRUPTED, SESSION_EXPIRED, runChatStream } from '../lib/chatStream.mjs';

const sse = (...events) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('');

function sseResponse(text) {
	return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

function jsonResponse(status, data, statusText = '') {
	return new Response(JSON.stringify(data), { status, statusText, headers: { 'content-type': 'application/json' } });
}

/** fetch answering with the given responses in order, recording the headers it was called with. */
function fakeFetch(...responses) {
	const calls = [];
	const impl = async (url, init) => {
		calls.push(init.headers);
		const next = responses.shift();
		if (next instanceof Error) throw next;
		return typeof next === 'function' ? next(init) : next;
	};
	return { impl, calls };
}

async function run(fetchImpl, extra = {}) {
	const events = [];
	const result = await runChatStream({
		url: '/api/chat', body: { message: 'hi' }, onEvent: e => events.push(e),
		getHeaders: () => ({ Authorization: 'Bearer old' }), fetchImpl, ...extra,
	});
	return { result, events, types: events.map(e => e.type) };
}

test('a complete stream passes its events through, nothing synthesized', async () => {
	const { impl } = fakeFetch(sseResponse(sse({ type: 'chunk', content: 'a' }, { type: 'done', displayText: 'a' }, { type: 'saved' })));
	const { result, types } = await run(impl);
	assert.deepEqual(types, ['chunk', 'done', 'saved']);
	assert.equal(result.success, true);
});

test('a stream closed without a terminal event ends with a recoverable error', async () => {
	const { impl } = fakeFetch(sseResponse(sse({ type: 'chunk', content: 'a' })));
	const { result, events, types } = await run(impl);
	assert.deepEqual(types, ['chunk', 'error']);
	assert.equal(events[1].error, STREAM_INTERRUPTED);
	assert.equal(events[1].interrupted, true);
	assert.equal(events[1].details, undefined, 'details is for server text only');
	assert.equal(result.interrupted, true);
});

test("'done' without 'saved' reports an unconfirmed save", async () => {
	const { impl } = fakeFetch(sseResponse(sse({ type: 'done', displayText: 'a' })));
	assert.deepEqual((await run(impl)).types, ['done', 'save_unconfirmed']);
});

test("roll_pending and error are terminal (no 'saved' expected)", async () => {
	for (const terminal of [{ type: 'roll_pending', roll_id: 'r' }, { type: 'error', error: 'boom' }]) {
		const { impl } = fakeFetch(sseResponse(sse(terminal)));
		assert.deepEqual((await run(impl)).types, [terminal.type]);
	}
});

test('HTTP errors become one error event with the status and FastAPI detail', async () => {
	const cases = [
		[jsonResponse(404, { detail: 'Partie introuvable' }), 'Partie introuvable'],
		[jsonResponse(422, { detail: [{ msg: 'field required' }] }), 'Requête invalide : field required'],
		[new Response('<html>', { status: 502, statusText: 'Bad Gateway' }), 'Erreur serveur (502 Bad Gateway)'],
	];
	for (const [response, message] of cases) {
		const { impl } = fakeFetch(response);
		const { result, events } = await run(impl);
		assert.equal(events.length, 1);
		assert.equal(events[0].type, 'error');
		assert.equal(events[0].error, message);
		assert.equal(events[0].status, response.status);
		assert.equal(result.success, false);
	}
});

test('401: one refresh, then the retry carries the new token', async () => {
	let token = 'old';
	const { impl, calls } = fakeFetch(jsonResponse(401, { detail: 'expired' }), sseResponse(sse({ type: 'done' }, { type: 'saved' })));
	const { result, types } = await run(impl, {
		getHeaders: () => ({ Authorization: `Bearer ${token}` }),
		refreshSession: async () => { token = 'new'; },
	});
	assert.deepEqual(types, ['done', 'saved']);
	assert.equal(result.success, true);
	assert.deepEqual(calls.map(h => h.Authorization), ['Bearer old', 'Bearer new']);
});

test('401 with a failed refresh: session expired, no retry', async () => {
	const { impl, calls } = fakeFetch(jsonResponse(401, { detail: 'expired' }));
	const { events } = await run(impl, { refreshSession: async () => { throw new Error('Session expired'); } });
	assert.deepEqual(events, [{ type: 'error', error: SESSION_EXPIRED, status: 401 }]);
	assert.equal(calls.length, 1);
});

test('a second 401 after the refresh is an error, not a loop', async () => {
	const { impl, calls } = fakeFetch(jsonResponse(401, {}), jsonResponse(401, { detail: 'Token invalide' }));
	const { events } = await run(impl, { refreshSession: async () => {} });
	assert.equal(calls.length, 2);
	assert.equal(events[0].error, 'Token invalide');
});

test('network failure: recoverable error; abort: nothing', async () => {
	const network = await run(fakeFetch(new TypeError('Failed to fetch')).impl);
	assert.deepEqual(network.types, ['error']);
	assert.equal(network.result.interrupted, true);

	const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });
	const aborted = await run(fakeFetch(abort).impl);
	assert.deepEqual(aborted.events, []);
	assert.equal(aborted.result.aborted, true);
});

test('a JSON (non-SSE) answer is a done, or an error when it says so', async () => {
	const ok = await run(fakeFetch(jsonResponse(200, { displayText: 'ok', state: { a: 1 } })).impl);
	assert.deepEqual(ok.events, [{ type: 'done', displayText: 'ok', state: { a: 1 } }]);
	const ko = await run(fakeFetch(jsonResponse(200, { error: 'Partie occupée' })).impl);
	assert.deepEqual(ko.types, ['error']);
	assert.equal(ko.result.success, false);
});
