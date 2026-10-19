// Entity names are tagged (tooltip) as whole words only (#142).
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000dd';
const NARRATION = "Paraît qu'ils coupent un poste avant la convergence. Le cargo rentre à Vergence ce soir.";
const LOADED_GAME = {
	state: { game: { name: 'Partie Brume' }, world_created: true },
	messages: [
		{ id: 'dddddddd-0000-0000-0000-000000000001', role: 'user', content: "J'écoute." },
		{ id: 'dddddddd-0000-0000-0000-000000000002', role: 'assistant', content: NARRATION },
	],
};

test('a name is tagged as a whole word, not inside a longer word', async ({ page }) => {
	await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Brume', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => LOADED_GAME,
		'GET /tooltips/annotations': () => ({
			messages: [{ annotations: [{ canonical_name: 'Vergence', entity_type: 'location' }] }],
		}),
		'GET /tooltips/entity': () => ({ found: false }),
	});
	await page.goto('/game/');
	await page.getByText('Partie Brume').click();

	const tagged = page.locator('span.text-blue-400.cursor-help');
	await expect(tagged).toHaveCount(1);
	await expect(tagged).toHaveText('Vergence');
	await expect(page.getByText(/avant la convergence\./)).toBeVisible();
	await page.screenshot({ path: 'test-results/entity-tagging.png' });
});
