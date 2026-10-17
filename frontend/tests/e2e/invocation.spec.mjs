// Pending Fate roll (#32): the aspect invocation modal comes back after a reload.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000bb';
const ROLL_ID = '11111111-2222-3333-4444-555555555555';
const PENDING_ROLL = {
	roll_id: ROLL_ID,
	roll: {
		dice: [-1, -1, -1, -1], total: -4, skill_total: 0, outcome: 'failure', shifts: -4,
		details: { skill_name: 'Athlétisme', skill_label: 'Médiocre', difficulty: 4, difficulty_label: 'Bon' },
	},
	aspects: ['Pilote déchu en quête de rédemption', "Je dois de l'argent à tout le monde"],
	fate_points: 3,
};
const LOADED_GAME = {
	state: { game: { name: 'Partie Fate', engine: 'fate_core' }, pending_roll: PENDING_ROLL },
	messages: [
		{ role: 'user', content: 'Je regarde autour de moi.' },
		{ role: 'assistant', content: 'Le hangar est désert.' },
	],
};
const ANSWER = [
	{ type: 'roll_result', roll: { ...PENDING_ROLL.roll, skill_total: 2, shifts: -2 } },
	{ type: 'chunk', content: 'Tu rates le saut de peu.' },
	{ type: 'done', displayText: 'Tu rates le saut de peu.', state: {} },
	{ type: 'saved' },
];

let crashes;
test.beforeEach(({ page }) => {
	crashes = [];
	page.on('pageerror', e => crashes.push(e.message));
	page.on('console', m => {
		if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) crashes.push(m.text());
	});
});
test.afterEach(() => expect(crashes).toEqual([]));

test('invocation modal comes back after a reload', async ({ page }, testInfo) => {
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Fate', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => LOADED_GAME,
		'POST /chat': () => ({ __sse: ANSWER }),
	});
	await page.goto('/game/');
	await page.getByText('Partie Fate').click();

	const modal = page.getByRole('heading', { name: 'Invoquer un aspect ?' });
	await expect(modal).toBeVisible();
	await expect(page.getByRole('button', { name: /Pilote déchu en quête de rédemption/ })).toBeVisible();
	await expect(page.getByText('3 PD restants')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('invocation-modal-after-reload.png') });

	// The resume carries the stored roll id; the backend narrates the stored message.
	await page.getByRole('button', { name: /Pilote déchu en quête de rédemption/ }).click();
	await page.getByRole('button', { name: 'Invoquer (1 PD)' }).click();
	await expect(modal).toBeHidden();
	await expect(page.getByText('Tu rates le saut de peu.').last()).toBeVisible();
	const chats = api.calls.filter(c => c.path === '/chat');
	expect(chats).toHaveLength(1);
	expect(chats[0].body.roll_id).toBe(ROLL_ID);
	expect(chats[0].body.invoked_aspects).toEqual(['Pilote déchu en quête de rédemption']);
});
