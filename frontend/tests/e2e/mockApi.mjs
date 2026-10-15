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
 * @param {Object} handlers - { 'POST /world/enhance': (body) => response, ... } override defaults
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

	await page.addInitScript((user) => {
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
		if (result && result.__status) {
			return route.fulfill({ status: result.__status, contentType: 'application/json', body: JSON.stringify(result.body) });
		}
		return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
	});
	return { calls };
}
