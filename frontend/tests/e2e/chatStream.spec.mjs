// /chat stream failures (#35): the error is shown and the player can always send again.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000aa';
const LOADED_GAME = {
	state: { game: { name: 'Ma partie', engine: 'none' } },
	messages: [{ role: 'user', content: 'Je regarde autour de moi.' }, { role: 'assistant', content: 'Une salle vide.' }],
};
const ANSWER = [
	{ type: 'chunk', content: 'La porte grince.' },
	{ type: 'done', displayText: 'La porte grince.', state: {} },
	{ type: 'saved' },
];

const input = (page) => page.getByPlaceholder(/Ton action/);

// A render crash (React error boundary, uncaught exception) fails the test. The
// browser's own "Failed to load resource" lines are expected: the API answers 401/500 on purpose.
let crashes;
test.beforeEach(({ page }) => {
	crashes = [];
	page.on('pageerror', e => crashes.push(e.message));
	page.on('console', m => {
		if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) crashes.push(m.text());
	});
});
test.afterEach(() => expect(crashes).toEqual([]));

/** Mocked API whose /chat answers come from `chatAnswers`, one per call. */
async function openGame(page, chatAnswers) {
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Ma partie', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => LOADED_GAME,
		'POST /chat': () => chatAnswers.shift(),
	});
	await page.goto('/game/');
	await page.getByText('Ma partie').click();
	await expect(page.getByText('Une salle vide.')).toBeVisible();
	return api;
}

async function send(page, text) {
	await input(page).fill(text);
	await input(page).press('Control+Enter');
}

test('an HTTP error is shown and the player can send again', async ({ page }) => {
	await openGame(page, [{ __status: 500, body: { detail: 'Erreur interne du serveur' } }, { __sse: ANSWER }]);
	await send(page, 'J’ouvre la porte.');
	await expect(page.getByText('Erreur interne du serveur')).toBeVisible();
	await expect(input(page)).toBeEnabled();

	await page.getByRole('button', { name: 'Fermer' }).click();
	await send(page, 'J’ouvre la porte.');
	await expect(page.getByText('La porte grince.')).toBeVisible();
});

test('a stream cut short ends with a recoverable error, and Réessayer works', async ({ page }) => {
	await openGame(page, [{ __sse: [{ type: 'chunk', content: 'La por' }] }, { __sse: ANSWER }]);
	await send(page, 'J’ouvre la porte.');
	await expect(page.getByText(/connexion a été interrompue/)).toBeVisible();
	await expect(input(page)).toBeEnabled();
	await page.getByRole('button', { name: 'Réessayer' }).click();
	await expect(page.getByText('La porte grince.').last()).toBeVisible();
});

test('a 401 refreshes the session once and the turn goes through', async ({ page }) => {
	const api = await openGame(page, [{ __status: 401, body: { detail: 'Token expiré' } }, { __sse: ANSWER }]);
	const refreshes = () => api.calls.filter(c => c.path === '/auth/refresh').length;
	const before = refreshes(); // the app also refreshes once at start-up
	await send(page, 'J’ouvre la porte.');
	await expect(page.getByText('La porte grince.')).toBeVisible();
	expect(refreshes() - before).toBe(1);
	const chats = api.calls.filter(c => c.path === '/chat');
	expect(chats).toHaveLength(2);
});
