// Leaving a game while its narration streams cuts nothing (#143): the /chat request stays
// open in the background, and its events only ever reach the game they belong to.
import { test, expect } from '@playwright/test';
import { mockApi, streamedChat } from './mockApi.mjs';

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

const GAMES = [
	{ id: GAME_ID, name: 'Partie Pluie', current_cycle: 1 },
	{ id: OTHER_ID, name: 'Partie Neige', current_cycle: 1 },
];
const gate = () => {
	let release;
	const held = new Promise(resolve => { release = resolve; });
	return { held, release };
};

// Two games; the first /chat answer waits for `releaseChat()`, the next ones answer at once.
// GET /games/{id} always returns the history without the turn played in the test.
// `holdReopen`: the second load of the first game (its reopening) waits for `releaseLoad()`.
async function setup(page, chatAnswers, { holdReopen = false } = {}) {
	const chatGate = gate();
	const loadGate = gate();
	let chatCount = 0;
	let loads = 0;
	const api = await mockApi(page, {
		'GET /games': () => ({ games: GAMES }),
		[`GET /games/${GAME_ID}`]: async () => {
			if (++loads === 2 && holdReopen) await loadGate.held;
			return GAME;
		},
		[`GET /games/${OTHER_ID}`]: () => OTHER_GAME,
		[`POST /games/${GAME_ID}/rollback`]: () => ({ messages: HISTORY, state: GAME.state }),
		'POST /chat': async () => {
			const index = chatCount++;
			if (index === 0) await chatGate.held;
			return { __sse: chatAnswers[index] };
		},
	});
	await page.goto('/game/');
	const requests = () => api.calls.filter(c => c.path === '/chat' || c.path.endsWith('/rollback'));
	// Resolves once the held /chat answer has been delivered to the page.
	const releaseChat = async () => {
		const delivered = page.waitForEvent('requestfinished', r => r.url().includes('/api/chat'));
		chatGate.release();
		await delivered;
	};
	return { api, requests, releaseChat, releaseLoad: loadGate.release };
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
	await expect(page.getByText('Je sors.')).toHaveCount(1);
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

test('a turn that failed after the player left: reopened, its action and error come back, Réessayer resends it', async ({ page }, testInfo) => {
	const failure = { type: 'error', error: 'Le narrateur a échoué.', recoverable: true };
	const { requests, releaseChat } = await setup(page, [[failure], answer('La porte grince.')]);
	await sendThenLeave(page, requests);
	await releaseChat();

	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await expect(page.getByText('Le narrateur a échoué.')).toBeVisible();
	await expect(page.getByText('Je sors.')).toHaveCount(1);
	await page.screenshot({ path: testInfo.outputPath('quit-8-failed-turn-reopened.png') });
	await page.getByRole('button', { name: 'Réessayer' }).click();
	await expect(page.getByText('La porte grince.')).toBeVisible();
	expect(requests().map(c => c.body.message)).toEqual(['Je sors.', 'Je sors.']);
});

test('done and saved arriving while the game reopens: the turn and its state are not lost', async ({ page }, testInfo) => {
	const { requests, releaseChat, releaseLoad } = await setup(page, [answer('La porte grince.', LIVE_IDS, GAME_STATE)], { holdReopen: true });
	await sendThenLeave(page, requests);

	await page.getByText('Partie Pluie').click(); // its load waits
	await releaseChat(); // done + saved delivered while the game loads
	releaseLoad(); // the load read before the commit: no turn, old state
	await expect(page.getByText('La porte grince.')).toBeVisible();
	await expect(page.getByText('Je sors.')).toHaveCount(1);
	await expect(page.getByText('📍 Quai des brumes')).toBeVisible();
	await expect(page.getByText(/4[\s\u202f]?242 cr/)).toBeVisible();
	await expect(page.getByText('Sauvegarde...')).toHaveCount(0);
	await expect(page.getByPlaceholder(/Ton action/)).toBeEnabled();
	await page.screenshot({ path: testInfo.outputPath('quit-9-done-during-reopen.png') });
});

// ---------------------------------------------------------------------------
// Streams fed event by event
// ---------------------------------------------------------------------------

async function setupStreamed(page, { games = GAMES, loads = {} } = {}) {
	const chat = await streamedChat(page);
	await mockApi(page, {
		'GET /games': () => ({ games }),
		[`GET /games/${GAME_ID}`]: () => GAME,
		[`GET /games/${OTHER_ID}`]: () => OTHER_GAME,
		...loads,
	});
	await page.goto('/game/');
	return chat;
}

test('Annuler after reopening cuts that game\'s turn only; the game can send again', async ({ page }, testInfo) => {
	const chat = await setupStreamed(page);
	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await send(page, 'Je sors.');
	await expect.poll(async () => (await chat.bodies()).length).toBe(1);
	await chat.push(0, { type: 'chunk', content: 'La porte ' });
	await expect(page.getByText('La porte')).toBeVisible();
	await page.getByTitle('Retour à la liste').click();

	await open(page, 'Partie Neige', 'Le froid te mord les doigts.');
	await send(page, 'Je fais un feu.');
	await expect.poll(async () => (await chat.bodies()).length).toBe(2);
	await page.getByTitle('Retour à la liste').click();

	await open(page, 'Partie Pluie', 'Le hangar est désert.');
	await expect(page.getByText('Je sors.')).toHaveCount(1);
	await expect(page.getByText('La porte')).toBeVisible();
	await page.getByRole('button', { name: /Annuler/ }).click();
	await expect(page.getByText('(Annulé)')).toBeVisible();
	expect(await chat.aborted(0)).toBe(true);
	expect(await chat.aborted(1)).toBe(false);
	await page.screenshot({ path: testInfo.outputPath('quit-10-cancel-after-reopen.png') });

	// The other game's turn runs on and ends normally; nothing of it shows here.
	await chat.push(1, ...answer('Tu te réchauffes.'));
	await chat.end(1);
	await expect(page.getByText('Tu te réchauffes.')).toHaveCount(0);

	await send(page, 'Je reste.');
	await expect.poll(async () => (await chat.bodies()).length).toBe(3);
	await chat.push(2, ...answer('Tu restes au sec.'));
	await chat.end(2);
	await expect(page.getByText('Tu restes au sec.')).toBeVisible();
	await expect(page.getByText('(Annulé)')).toBeVisible();
	expect((await chat.bodies()).map(b => [b.gameId, b.message])).toEqual([
		[GAME_ID, 'Je sors.'], [OTHER_ID, 'Je fais un feu.'], [GAME_ID, 'Je reste.'],
	]);
});

test('leaving during the arrival scene and reopening: its narration goes on, no second arrival', async ({ page }, testInfo) => {
	const NEW_ID = '00000000-0000-0000-0000-0000000000ff';
	const newGame = {
		state: { game: { name: 'Partie Neuve' }, world_created: true },
		world_info: { world: { name: 'Station Kira' }, npc_count: 2, location_count: 3, org_count: 1 },
		messages: [],
	};
	const chat = await setupStreamed(page, {
		games: [{ id: NEW_ID, name: 'Partie Neuve', current_cycle: 0 }],
		loads: { [`GET /games/${NEW_ID}`]: () => newGame },
	});
	await page.getByText('Partie Neuve').click();
	await page.getByRole('button', { name: /Commencer l'aventure/ }).click();
	await expect.poll(async () => (await chat.bodies()).length).toBe(1);
	await chat.push(0, { type: 'chunk', content: 'Bienvenue sur ' });
	await expect(page.getByText('Bienvenue sur')).toBeVisible();
	await page.getByTitle('Retour à la liste').click();

	await page.getByText('Partie Neuve').click();
	await expect(page.getByText('Bienvenue sur')).toBeVisible();
	await expect(page.getByRole('button', { name: /Commencer l'aventure/ })).toHaveCount(0);
	await page.screenshot({ path: testInfo.outputPath('quit-11-arrival-reopened.png') });

	await chat.push(0, { type: 'chunk', content: 'la station.' }, ...answer('Bienvenue sur la station.', LIVE_IDS).slice(1));
	await chat.end(0);
	await expect(page.getByText('Bienvenue sur la station.')).toBeVisible();
	await expect(page.getByPlaceholder(/Ton action/)).toBeEnabled();
	await page.screenshot({ path: testInfo.outputPath('quit-12-arrival-done.png') });
	expect(await chat.bodies()).toHaveLength(1);
});
