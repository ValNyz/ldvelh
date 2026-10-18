// D6 roll display (#92): a wild die showing 1 applies one penalty, and the UI says so.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000bb';
const ROLL = {
	dice: [6, 5, 1], total: 13, skill_total: 13, outcome: 'success', shifts: 3, complication: true,
	details: {
		skill_name: 'Tir', dice_code: '3D+2', regular_dice: [6, 5], wild_die_rolls: [1],
		wild_total: 0, pip_bonus: 2, difficulty: 10, reason: 'Tir sur le garde',
	},
};

test('a wild die showing 1 states the single-penalty rule', async ({ page }) => {
	const errors = [];
	page.on('pageerror', e => errors.push(e.message));
	await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Ma partie', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => ({
			state: { game: { name: 'Ma partie', engine: 'd6' } },
			messages: [{ role: 'assistant', content: 'Une salle vide.' }],
		}),
		'POST /chat': () => ({ __sse: [
			{ type: 'roll_result', roll: ROLL },
			{ type: 'chunk', content: 'Le tir part de travers.' },
			{ type: 'done', displayText: 'Le tir part de travers.', state: {} },
			{ type: 'saved' },
		] }),
	});
	await page.goto('/game/');
	await page.getByText('Ma partie').click();
	await expect(page.getByText('Une salle vide.')).toBeVisible();
	await page.getByPlaceholder(/Ton action/).fill('Je tire.');
	await page.getByPlaceholder(/Ton action/).press('Control+Enter');
	await expect(page.getByText('Complication ! Le dé sauvage tombe sur 1 : il compte pour 0, les autres dés sont conservés.')).toBeVisible();
	await expect(page.getByText('(dé sauvage : 0)')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('d6-wild-one.png') });
	expect(errors).toEqual([]);
});
