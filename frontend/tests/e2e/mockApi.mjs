/**
 * Mocked backend for e2e tests: every /api call is answered here and recorded,
 * so the frontend runs for real without the Python backend or an LLM.
 */

export const GENRES = [
	{ id: 'g1', slug: 'sci_fi', label: 'Science-Fiction', is_preset: true, world_type: null },
	{ id: 'g2', slug: 'dark_fantasy', label: 'Dark Fantasy', is_preset: true, world_type: null },
	{ id: 'g3', slug: 'cosmic_horror', label: 'Horreur Cosmique', is_preset: true, world_type: null },
	{ id: 'g4', slug: 'cyberpunk', label: 'Cyberpunk', is_preset: true, world_type: null },
];

export const USER = {
	id: 'u1', email: 'joueur@example.com', name: 'Joueur', email_verified: true,
	preferences: { active_provider: 'anthropic', active_model: 'claude-sonnet-5-5' },
};

/**
 * @param {import('@playwright/test').Page} page
 * @param {Object} handlers - { 'POST /world/enhance': (body) => response, ... } override defaults.
 *   A response may be { __status, body } (HTTP error) or { __sse: [events] } (SSE stream).
 * @returns {{ calls: Array<{method: string, path: string, body: any}> }}
 */
export async function mockApi(page, handlers = {}) {
	const calls = [];
	const defaults = {
		'GET /auth/me': () => ({ user: USER }),
		'POST /auth/refresh': () => ({ token: 'test-token' }),
		'GET /games': () => ({ games: [] }),
		'GET /genres': () => ({ genres: GENRES }),
		'POST /games': () => ({ gameId: '00000000-0000-0000-0000-000000000001' }),
	};
	const all = { ...defaults, ...handlers };

	// Signed in once per test (the tab's sessionStorage remembers it): a reload keeps
	// what the app stored, and a logout stays logged out on the next page.
	await page.addInitScript((user) => {
		if (sessionStorage.getItem('e2e-signed-in')) return;
		sessionStorage.setItem('e2e-signed-in', '1');
		localStorage.setItem('ldvelh-auth-token', 'test-token');
		localStorage.setItem('ldvelh-auth-user', JSON.stringify(user));
	}, USER);

	await page.route('**/api/**', async (route) => {
		const req = route.request();
		const path = new URL(req.url()).pathname.replace(/^\/api/, '').replace(/\/$/, '');
		const key = `${req.method()} ${path}`;
		let body = null;
		try { body = req.postDataJSON(); } catch { body = req.postData(); }
		calls.push({ method: req.method(), path, body });
		const handler = all[key];
		if (!handler) {
			return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
		}
		const result = await handler(body);
		if (result && result.__sse) {
			const events = result.__sse.map(e => `data: ${JSON.stringify(e)}\n\n`).join('');
			return route.fulfill({ status: 200, contentType: 'text/event-stream', body: events });
		}
		if (result && result.__status) {
			return route.fulfill({ status: result.__status, contentType: 'application/json', body: JSON.stringify(result.body) });
		}
		return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
	});
	return { calls };
}

/**
 * /chat answered by streams the test feeds event by event (a mocked route can only send a
 * whole body at once): `fetch` is wrapped in the page for /api/chat only, and each request
 * gets the next stream. Aborting the request (Annuler) errors its stream as fetch would.
 * @param {import('@playwright/test').Page} page
 */
export async function streamedChat(page) {
	await page.addInitScript(() => {
		const original = window.fetch.bind(window);
		const chat = { bodies: [], controllers: [], aborted: [] };
		window.__chat = chat;
		window.fetch = (input, init = {}) => {
			const url = typeof input === 'string' ? input : input.url;
			if (new URL(url, location.href).pathname.replace(/\/$/, '') !== '/api/chat') return original(input, init);
			const index = chat.bodies.length;
			chat.bodies.push(JSON.parse(init.body));
			chat.aborted.push(false);
			const body = new ReadableStream({ start(controller) { chat.controllers[index] = controller; } });
			init.signal?.addEventListener('abort', () => {
				chat.aborted[index] = true;
				chat.controllers[index].error(new DOMException('The user aborted a request.', 'AbortError'));
			});
			return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
		};
	});
	const state = () => page.evaluate(() => ({ bodies: window.__chat.bodies, aborted: window.__chat.aborted }));
	return {
		/** Bodies of the /chat requests sent so far. */
		bodies: async () => (await state()).bodies,
		/** Whether request `index` was aborted. */
		aborted: async (index) => (await state()).aborted[index],
		/** Sends `events` on stream `index` (dropped once it was aborted). */
		push: (index, ...events) => page.evaluate(([i, text]) => {
			if (!window.__chat.aborted[i]) window.__chat.controllers[i].enqueue(new TextEncoder().encode(text));
		}, [index, events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')]),
		/** Ends stream `index`. */
		end: (index) => page.evaluate((i) => {
			if (!window.__chat.aborted[i]) window.__chat.controllers[i].close();
		}, index),
	};
}
