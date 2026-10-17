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
	player_message: 'Je tente un saut impossible.',
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
	// The waiting action, not saved before the resume, is shown just before its narration.
	const action = page.getByText('Je tente un saut impossible.');
	await expect(action).toBeVisible();
	const [actionBox, answerBox] = [await action.boundingBox(), await page.getByText('Tu rates le saut de peu.').last().boundingBox()];
	expect(actionBox.y).toBeLessThan(answerBox.y);
	await page.screenshot({ path: testInfo.outputPath('invocation-resolved-after-reload.png') });
	const chats = api.calls.filter(c => c.path === '/chat');
	expect(chats).toHaveLength(1);
	expect(chats[0].body.roll_id).toBe(ROLL_ID);
	expect(chats[0].body.invoked_aspects).toEqual(['Pilote déchu en quête de rédemption']);
	expect(chats[0].body.message).toBe('Je tente un saut impossible.');
});

test('a new message answered with the waiting roll shows the waiting action', async ({ page }, testInfo) => {
	let chatCount = 0;
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Fate', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => ({ ...LOADED_GAME, state: { ...LOADED_GAME.state, pending_roll: null } }),
		'POST /chat': () => {
			chatCount += 1;
			return { __sse: chatCount === 1 ? [{ type: 'roll_pending', ...PENDING_ROLL }] : ANSWER };
		},
	});
	await page.goto('/game/');
	await page.getByText('Partie Fate').click();
	const input = page.getByPlaceholder(/Ton action/);
	await input.fill('Je fais autre chose.');
	await input.press('Control+Enter');

	await expect(page.getByRole('heading', { name: 'Invoquer un aspect ?' })).toBeVisible();
	// The optimistic message is replaced by the action the roll belongs to.
	await expect(page.getByText('Je tente un saut impossible.')).toBeVisible();
	await expect(page.getByText('Je fais autre chose.')).toHaveCount(0);
	await page.screenshot({ path: testInfo.outputPath('invocation-waiting-action-replaces-message.png') });

	await page.getByRole('button', { name: /Pilote déchu en quête de rédemption/ }).click();
	await page.getByRole('button', { name: 'Invoquer (1 PD)' }).click();
	await expect(page.getByText('Tu rates le saut de peu.').last()).toBeVisible();
	const chats = api.calls.filter(c => c.path === '/chat');
	expect(chats).toHaveLength(2);
	expect(chats[1].body.roll_id).toBe(ROLL_ID);
	expect(chats[1].body.message).toBe('Je tente un saut impossible.');
});

test('the input is disabled while the roll waits, enabled again after skipping', async ({ page }, testInfo) => {
	let chatCount = 0;
	const api = await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Fate', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => ({ ...LOADED_GAME, state: { ...LOADED_GAME.state, pending_roll: null } }),
		'POST /chat': () => {
			chatCount += 1;
			return { __sse: chatCount === 1 ? [{ type: 'roll_pending', ...PENDING_ROLL }] : ANSWER };
		},
	});
	await page.goto('/game/');
	await page.getByText('Partie Fate').click();
	const input = page.getByPlaceholder(/Ton action/);
	await input.fill('Je fais autre chose.');
	await input.press('Control+Enter');

	// #80: nothing can be sent behind the modal (it would show the waiting action twice).
	const dialog = page.getByRole('dialog', { name: 'Invoquer un aspect ?' });
	await expect(dialog).toBeVisible();
	await expect(dialog).toBeFocused();
	await expect(input).toBeDisabled();
	// Tab stays inside the dialog (3 buttons: two aspects and "Accepter l'échec"; the
	// invoke button is disabled until an aspect is chosen), Escape closes nothing.
	for (let i = 0; i < 4; i += 1) await page.keyboard.press('Tab');
	expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
	await page.keyboard.press('Escape');
	await expect(dialog).toBeVisible();
	await expect(page.getByText('Je tente un saut impossible.')).toHaveCount(1);
	await page.screenshot({ path: testInfo.outputPath('invocation-input-disabled-while-roll-waits.png') });

	await page.getByRole('button', { name: "Accepter l'échec" }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByText('Tu rates le saut de peu.').last()).toBeVisible();
	await expect(input).toBeEnabled();
	await expect(input).toBeFocused();
	await page.screenshot({ path: testInfo.outputPath('invocation-input-enabled-after-skip.png') });
	const chats = api.calls.filter(c => c.path === '/chat');
	expect(chats).toHaveLength(2);
	expect(chats[1].body.roll_id).toBe(ROLL_ID);
	expect(chats[1].body.invoked_aspects).toEqual([]);
});
