// Leaving a game while its narration streams cuts nothing (#143): the /chat request stays
// open in the background, and its events only ever reach the game they belong to.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000dd';
const OTHER_ID = '00000000-0000-0000-0000-0000000000ee';
const HISTORY = [
	{ id: 'cccccccc-0000-0000-0000-000000000001', role: 'user', content: 'Je regarde autour de moi.' },
	{ id: 'cccccccc-0000-0000-0000-000000000002', role: 'assistant', content: 'Le hangar est désert.' },
];
const GAME = { state: { game: { name: 'Partie Pluie' }, world_created: true }, messages: HISTORY };
const OTHER_GAME = {
	state: { game: { name: 'Partie Neige' }, world_created: true },
	messages: [
		{ id: 'dddddddd-0000-0000-0000-000000000001', role: 'user', content: 'Je marche dans la neige.' },
		{ id: 'dddddddd-0000-0000-0000-000000000002', role: 'assistant', content: 'Le froid te mord les doigts.' },
	],
};
const LIVE_IDS = { user_message_id: 'eeeeeeee-0000-0000-0000-000000000003', assistant_message_id: 'eeeeeeee-0000-0000-0000-000000000004' };

// State the held turn of the first game ends with: its header shows it, never another game's.
const GAME_STATE = { game: { current_location: 'Quai des brumes', game_date: '12 brumaire' }, player: { credits: 4242 } };
const answer = (text, meta = undefined, gameState = undefined) => [
	{ type: 'chunk', content: text },
	{ type: 'done', displayText: text, state: { ...(meta ? { meta } : {}), ...(gameState ? { game_state: gameState } : {}) } },
	{ type: 'saved' },
];
const PENDING_ROLL = {
	type: 'roll_pending',
	roll_id: '11111111-2222-3333-4444-555555555555',
	roll: {
		dice: [-1, -1, -1, -1], total: -4, skill_total: 0, outcome: 'failure', shifts: -4,
		details: { skill_name: 'Athlétisme', skill_label: 'Médiocre', difficulty: 4, difficulty_label: 'Bon' },
	},
	aspects: ['Pilote déchu en quête de rédemption'],
	fate_points: 3,
	player_message: 'Je sors.',
};
const FATAL_ERROR = { type: 'error', error: 'Le narrateur a échoué.', recoverable: false };

let crashes;
test.beforeEach(({ page }) => {
	crashes = [];
	page.on('pageerror', e => crashes.push(e.message));
	page.on('console', m => {
		if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) crashes.push(m.text());
	});
});
test.afterEach(() => expect(crashes).toEqual([]));

// Two games; the first /chat answer waits for `release()`, the next ones answer at once.
// GET /games/{id} always returns the history without the turn played in the test.
async function setup(page, chatAnswers) {
	let release;
	const gate = new Promise(resolve => { release = resolve; });
	let chatCount = 0;
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [
			{ id: GAME_ID, name: 'Partie Pluie', current_cycle: 1 },
			{ id: OTHER_ID, name: 'Partie Neige', current_cycle: 1 },
		] }),
		[`GET /games/${GAME_ID}`]: () => GAME,
		[`GET /games/${OTHER_ID}`]: () => OTHER_GAME,
		[`POST /games/${GAME_ID}/rollback`]: () => ({ messages: HISTORY, state: GAME.state }),
		'POST /chat': async () => {
			const index = chatCount++;
			if (index === 0) await gate;
			return { __sse: chatAnswers[index] };
		},
	});
	await page.goto('/game/');
	const requests = () => api.calls.filter(c => c.path === '/chat' || c.path.endsWith('/rollback'));
	// Resolves once the held /chat answer has been delivered to the page.
	const releaseChat = async () => {
		const delivered = page.waitForEvent('requestfinished', r => r.url().includes('/api/chat'));
		release();
		await delivered;
	};
	return { requests, releaseChat };
}

async function open(page, name, lastMessage) {
	await page.getByText(name).click();
	await expect(page.getByText(lastMessage)).toBeVisible();
}

async function send(page, text) {
	const input = page.getByPlaceholder(/Ton action/);
	await input.fill(text);
	await input.press('Control+Enter');
}

async function sendThenLeave(page, requests) {
	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await send(page, 'Je sors.');
	await expect.poll(() => requests().length).toBe(1);
	await page.getByTitle('Retour à la liste').click();
	await expect(page.getByText('Partie Neige')).toBeVisible();
}

test('reopening the game while its turn streams shows the action, then the reply with its ids', async ({ page }, testInfo) => {
	const { requests, releaseChat } = await setup(page, [answer('La porte grince.', LIVE_IDS, GAME_STATE), answer('La pluie redouble.')]);
	await sendThenLeave(page, requests);

	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await expect(page.getByRole('button', { name: /Annuler/ })).toBeVisible();
	await expect(page.getByText('Je sors.')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('quit-1-reopened-in-flight.png') });

	await releaseChat();
	await expect(page.getByText('La porte grince.')).toBeVisible();
	await expect(page.getByText('Je sors.')).toHaveCount(1);
	await expect(page.getByText('📍 Quai des brumes')).toBeVisible();
	await expect(page.getByText(/4[\s\u202f]?242 cr/)).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('quit-2-reply-landed.png') });

	await page.getByText('La porte grince.').hover();
	await page.getByTitle('Regénérer').click();
	await expect(page.getByText('La pluie redouble.')).toBeVisible();
	const calls = requests();
	expect(calls.map(c => c.path)).toEqual(['/chat', `/games/${GAME_ID}/rollback`, '/chat']);
	expect(calls[1].body).toEqual({ messageId: LIVE_IDS.user_message_id });
	expect(calls[2].body.message).toBe('Je sors.');
});

test('opening another game while the old turn streams: nothing from it shows there, sending works', async ({ page }, testInfo) => {
	const { requests, releaseChat } = await setup(page, [answer('La porte grince.', LIVE_IDS, GAME_STATE), answer('Tu te réchauffes.')]);
	await sendThenLeave(page, requests);

	await open(page, 'Partie Neige', 'Le froid te mord les doigts.');
	await releaseChat();
	await expect(page.getByText('Quai des brumes')).toHaveCount(0);
	await expect(page.getByText('12 brumaire')).toHaveCount(0);
	await expect(page.getByText(/4[\s\u202f]?242 cr/)).toHaveCount(0);
	await expect(page.getByText('Sauvegarde...')).toHaveCount(0);
	await send(page, 'Je fais un feu.');
	await expect(page.getByText('Tu te réchauffes.')).toBeVisible();
	await expect(page.getByText('La porte grince.')).toHaveCount(0);
	await expect(page.getByText('Je sors.')).toHaveCount(0);
	await expect(page.getByText('Je marche dans la neige.')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('quit-3-other-game.png') });
	const calls = requests();
	expect(calls.map(c => c.body.gameId)).toEqual([GAME_ID, OTHER_ID]);
});

test('a game opened while the old turn is held can send before that turn ends', async ({ page }, testInfo) => {
	const { requests, releaseChat } = await setup(page, [answer('La porte grince.', LIVE_IDS), answer('Tu te réchauffes.')]);
	await sendThenLeave(page, requests);

	await open(page, 'Partie Neige', 'Le froid te mord les doigts.');
	await send(page, 'Je fais un feu.');
	await expect(page.getByText('Tu te réchauffes.')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('quit-4-send-while-held.png') });
	await releaseChat();
	await expect(page.getByText('La porte grince.')).toHaveCount(0);
	expect(requests().map(c => c.body.gameId)).toEqual([GAME_ID, OTHER_ID]);
});

for (const [name, event] of [['a pending roll', PENDING_ROLL], ['a fatal error', FATAL_ERROR]]) {
	test(`${name} arriving after the player left reaches neither the list nor another game`, async ({ page }, testInfo) => {
		const slug = name.replaceAll(' ', '-');
		const { requests, releaseChat } = await setup(page, [[event], answer('Tu te réchauffes.')]);
		await sendThenLeave(page, requests);

		await releaseChat();
		await expect(page.getByText('Le narrateur a échoué.')).toHaveCount(0);
		await expect(page.getByText('Partie Pluie')).toBeVisible();
		await page.screenshot({ path: testInfo.outputPath(`quit-5-${slug}-list.png`) });

		await open(page, 'Partie Neige', 'Le froid te mord les doigts.');
		await expect(page.getByRole('heading', { name: 'Invoquer un aspect ?' })).toHaveCount(0);
		await expect(page.getByText('Le narrateur a échoué.')).toHaveCount(0);
		await expect(page.getByText('Je sors.')).toHaveCount(0);
		await send(page, 'Je fais un feu.');
		await expect(page.getByText('Tu te réchauffes.')).toBeVisible();
		await page.screenshot({ path: testInfo.outputPath(`quit-6-${slug}-other-game.png`) });
	});
}

test('a pending roll arriving after the same game was reopened opens its modal there', async ({ page }, testInfo) => {
	const { requests, releaseChat } = await setup(page, [[PENDING_ROLL]]);
	await sendThenLeave(page, requests);

	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await releaseChat();
	await expect(page.getByRole('heading', { name: 'Invoquer un aspect ?' })).toBeVisible();
	await expect(page.getByText('Je sors.')).toHaveCount(1);
	await page.screenshot({ path: testInfo.outputPath('quit-7-roll-pending-reopened.png') });
});
