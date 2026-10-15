import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createSSEParser } from '../lib/sse.mjs';

function collect() {
	const events = [];
	return { events, parser: createSSEParser((e) => events.push(e)) };
}

function feedBytes(parser, bytes, sliceSize) {
	const decoder = new TextDecoder();
	for (let i = 0; i < bytes.length; i += sliceSize) {
		parser.push(decoder.decode(bytes.subarray(i, i + sliceSize), { stream: true }));
	}
	parser.push(decoder.decode());
	parser.flush();
}

const encoder = new TextEncoder();
const bigDone = { type: 'done', displayText: 'Été à la station — '.repeat(6000), state: { ok: true } };
const stream = encoder.encode(
	`: keepalive\n\ndata: ${JSON.stringify({ type: 'chunk', content: 'Début' })}\n\n` +
	`data: ${JSON.stringify(bigDone)}\n\n` +
	`data: ${JSON.stringify({ type: 'saved' })}\n\n`
);

for (const size of [1, 7, 16 * 1024]) {
	test(`events split every ${size} bytes are parsed exactly once`, () => {
		const { events, parser } = collect();
		feedBytes(parser, stream, size);
		assert.deepEqual(events.map((e) => e.type), ['chunk', 'done', 'saved']);
		assert.equal(events[1].displayText, bigDone.displayText);
	});
}

test('the 100 KB done event really is larger than a 16 KB read', () => {
	assert.ok(JSON.stringify(bigDone).length > 100_000);
});

test('two events in one read are both dispatched', () => {
	const { events, parser } = collect();
	parser.push('data: {"type":"chunk","content":"a"}\n\ndata: {"type":"chunk","content":"b"}\n\n');
	assert.deepEqual(events.map((e) => e.content), ['a', 'b']);
});

test('multi-line data fields are joined and CRLF is accepted', () => {
	const { events, parser } = collect();
	parser.push('data: {"type":\r\ndata: "status"}\r\n\r\n');
	assert.deepEqual(events, [{ type: 'status' }]);
});

test('a malformed event is dropped without stopping the stream', () => {
	const { events, parser } = collect();
	const warn = console.warn;
	console.warn = () => {};
	try {
		parser.push('data: {oops\n\ndata: {"type":"saved"}\n\n');
	} finally {
		console.warn = warn;
	}
	assert.deepEqual(events, [{ type: 'saved' }]);
});

test('CRLF split across two reads does not end the event early', () => {
	const { events, parser } = collect();
	parser.push('data: {"type":\r');
	parser.push('\ndata: "status"}\r\n\r\n');
	assert.deepEqual(events, [{ type: 'status' }]);
});
