// The image's static server (runtime/, #41) and the one used by e2e and `npm start`
// (main lockfile) must be the same serve version.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));

test('runtime/ pins exactly the serve version of the main lockfile', () => {
	const runtime = read('../runtime/package.json').dependencies.serve;
	const runtimeLock = read('../runtime/package-lock.json').packages['node_modules/serve'].version;
	const mainLock = read('../package-lock.json').packages['node_modules/serve'].version;
	assert.match(runtime, /^\d+\.\d+\.\d+$/, 'exact version, no range');
	assert.equal(runtimeLock, runtime);
	assert.equal(mainLock, runtime);
});
