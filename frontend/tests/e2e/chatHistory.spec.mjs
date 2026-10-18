// Edit / resend / regenerate on a loaded game (#55): rollback to the action, then /chat again.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000cc';
const HISTORY = [
	{ id: 'aaaaaaaa-0000-0000-0000-000000000001', role: 'user', content: 'Je regarde autour de moi.' },
	{ id: 'aaaaaaaa-0000-0000-0000-000000000002', role: 'assistant', content: 'Le hangar est désert.' },
	{ id: 'aaaaaaaa-0000-0000-0000-000000000003', role: 'user', content: 'Je sors sous la pluie.' },
	{ id: 'aaaaaaaa-0000-0000-0000-000000000004', role: 'assistant', content: 'Il pleut à verse sur le quai.' },
];
const LOADED_GAME = { state: { game: { name: 'Partie Pluie' }, world_created: true }, messages: HISTORY };
const LIVE_IDS = { user_message_id: 'bbbbbbbb-0000-0000-0000-000000000005', assistant_message_id: 'bbbbbbbb-0000-0000-0000-000000000006' };

const answer = (text, meta = undefined) => [
	{ type: 'chunk', content: text },
	{ type: 'done', displayText: text, state: meta ? { meta } : {} },
	{ type: 'saved' },
];

// Messages kept by a rollback to `messageId`: everything before it (all of the loaded
// history for a turn played in the test, which this mock does not record).
function rollbackTo(messages, messageId) {
	const index = messages.findIndex(m => m.id === messageId);
	return { messages: index === -1 ? messages : messages.slice(0, index), state: LOADED_GAME.state };
}

let crashes;
test.beforeEach(({ page }) => {
	crashes = [];
	page.on('pageerror', e => crashes.push(e.message));
	page.on('console', m => {
		if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) crashes.push(m.text());
	});
});
test.afterEach(() => expect(crashes).toEqual([]));

async function openGame(page, chatAnswers) {
	let chatCount = 0;
	let history = HISTORY;
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Pluie', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => LOADED_GAME,
		[`POST /games/${GAME_ID}/rollback`]: (body) => {
			const result = rollbackTo(history, body.messageId);
			history = result.messages;
			return result;
		},
		'POST /chat': () => ({ __sse: chatAnswers[chatCount++] }),
	});
	await page.goto('/game/');
	await page.getByText('Partie Pluie').click();
	await expect(page.getByText('Il pleut à verse sur le quai.')).toBeVisible();
	const requests = () => api.calls.filter(c => c.path === '/chat' || c.path.endsWith('/rollback'));
	return { api, requests };
}

async function clickAction(page, messageText, title) {
	const text = page.getByText(messageText);
	await text.hover();
	// The action buttons of this message only (they sit next to its bubble).
	await text.locator('xpath=ancestor::div[contains(@class, "relative")][1]').getByTitle(title).click();
}

test('regenerate right after loading a saved game', async ({ page }, testInfo) => {
	const { requests } = await openGame(page, [answer('La pluie redouble.')]);
	await page.getByText('Il pleut à verse sur le quai.').hover();
	await expect(page.getByTitle('Regénérer').locator('..')).toHaveCSS('opacity', '1');
	await page.screenshot({ path: testInfo.outputPath('regenerate-1-loaded.png') });
	await page.getByTitle('Regénérer').click();

	await expect(page.getByText('La pluie redouble.')).toBeVisible();
	await expect(page.getByText('Il pleut à verse sur le quai.')).toHaveCount(0);
	await expect(page.getByText('Je sors sous la pluie.')).toHaveCount(1);
	await page.screenshot({ path: testInfo.outputPath('regenerate-2-regenerated.png') });
	const calls = requests();
	expect(calls.map(c => c.path)).toEqual([`/games/${GAME_ID}/rollback`, '/chat']);
	expect(calls[0].body).toEqual({ messageId: HISTORY[2].id });
	expect(calls[1].body.message).toBe('Je sors sous la pluie.');
	expect(calls[1].body.gameId).toBe(GAME_ID);
	expect(calls[1].body).not.toHaveProperty('gameState');
});

test('regenerate a turn played in this session uses the ids of its done event', async ({ page }, testInfo) => {
	const { requests } = await openGame(page, [answer('Le quai est vide.', LIVE_IDS), answer('Un chat miaule.')]);
	const input = page.getByPlaceholder(/Ton action/);
	await input.fill('Je longe le quai.');
	await input.press('Control+Enter');
	await expect(page.getByText('Le quai est vide.')).toBeVisible();

	await clickAction(page, 'Le quai est vide.', 'Regénérer');
	await expect(page.getByText('Un chat miaule.')).toBeVisible();
	await expect(page.getByText('Le quai est vide.')).toHaveCount(0);
	await expect(page.getByText('Il pleut à verse sur le quai.')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('regenerate-3-live-turn.png') });
	const calls = requests();
	expect(calls.map(c => c.path)).toEqual(['/chat', `/games/${GAME_ID}/rollback`, '/chat']);
	expect(calls[1].body).toEqual({ messageId: LIVE_IDS.user_message_id });
	expect(calls[2].body.message).toBe('Je longe le quai.');
});

test('edit a loaded action', async ({ page }, testInfo) => {
	const { requests } = await openGame(page, [answer('Tu fouilles le hangar.')]);
	await clickAction(page, 'Je regarde autour de moi.', 'Éditer');
	const box = page.locator('textarea').first();
	await box.fill('Je fouille le hangar.');
	await page.getByRole('button', { name: 'Envoyer', exact: true }).first().click();

	await expect(page.getByText('Tu fouilles le hangar.')).toBeVisible();
	await expect(page.getByText('Le hangar est désert.')).toHaveCount(0);
	await page.screenshot({ path: testInfo.outputPath('edit-loaded-action.png') });
	const calls = requests();
	expect(calls.map(c => c.path)).toEqual([`/games/${GAME_ID}/rollback`, '/chat']);
	expect(calls[0].body).toEqual({ messageId: HISTORY[0].id });
	expect(calls[1].body.message).toBe('Je fouille le hangar.');
	expect(calls[1].body).not.toHaveProperty('gameState');
});

test('resend a loaded action', async ({ page }, testInfo) => {
	const { requests } = await openGame(page, [answer('La pluie cesse.')]);
	await clickAction(page, 'Je sors sous la pluie.', 'Renvoyer');

	await expect(page.getByText('La pluie cesse.')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('resend-loaded-action.png') });
	const calls = requests();
	expect(calls.map(c => c.path)).toEqual([`/games/${GAME_ID}/rollback`, '/chat']);
	expect(calls[0].body).toEqual({ messageId: HISTORY[2].id });
	expect(calls[1].body.message).toBe('Je sors sous la pluie.');
});
