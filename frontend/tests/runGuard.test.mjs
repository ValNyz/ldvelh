import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createRunGuard } from '../lib/game/runGuard.mjs';

test('a run started before a later one can no longer commit', () => {
	const guard = createRunGuard();
	const poll = guard.start();
	assert.equal(poll(), true);
	const refresh = guard.start();
	// The poll still awaiting when the refresh started: void, the refresh current.
	assert.equal(poll(), false);
	assert.equal(refresh(), true);
});

test('each guard counts its own runs', () => {
	const first = createRunGuard();
	const run = first.start();
	createRunGuard().start();
	assert.equal(run(), true);
});
