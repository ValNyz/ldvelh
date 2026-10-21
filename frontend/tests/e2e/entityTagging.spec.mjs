// Entity mentions are tagged (tooltip) from the stored spans, by offsets and entity id
// (#142, #155): never by matching a name in the text.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000dd';
const MESSAGE_ID = 'dddddddd-0000-0000-0000-000000000002';
const ENTITY_ID = 'eeeeeeee-0000-0000-0000-000000000001';

/** The mocks of a loaded game whose narrator message is `narration`. */
function gameMocks(narration, annotations, tooltip = { found: false }) {
	return {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Brume', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => ({
			state: { game: { name: 'Partie Brume' }, world_created: true },
			messages: [
				{ id: 'dddddddd-0000-0000-0000-000000000001', role: 'user', content: "J'écoute." },
				{ id: MESSAGE_ID, role: 'assistant', content: narration },
			],
		}),
		'GET /tooltips/annotations': () => ({
			messages: annotations.length
				? [{ message_id: MESSAGE_ID, sequence: 2, annotations }]
				: [],
		}),
		'GET /tooltips/entity': () => tooltip,
	};
}

/** The annotation of the first occurrence of `surface` in `text`, from index `from`. */
function annotation(text, surface, label, from = 0) {
	const start = text.indexOf(surface, from);
	return { start, end: start + surface.length, entity_id: ENTITY_ID, entity_type: 'character', label };
}

async function openGame(page) {
	await page.goto('/game/');
	await page.getByText('Partie Brume').click();
}

test('a descriptor mention gets its tooltip', async ({ page }) => {
	const descriptor = 'La Kethari âgée';
	const narration = `${descriptor} te fixe longuement, puis détourne les yeux vers le quai.`;
	await mockApi(page, gameMocks(
		narration,
		[annotation(narration, descriptor, descriptor)],
		{ found: true, tooltip: { icon: '👤', name: descriptor, type: 'character', infos: [] } },
	));
	const entityRequest = page.waitForRequest(r => r.url().includes('/tooltips/entity'));
	await openGame(page);

	const url = new URL((await entityRequest).url());
	expect(url.searchParams.get('id')).toBe(ENTITY_ID);
	expect(url.searchParams.get('gameId')).toBe(GAME_ID);
	const tagged = page.locator('span.text-blue-400.cursor-help');
	await expect(tagged).toHaveCount(1);
	await expect(tagged).toHaveText(descriptor);
	await expect(page.getByText(/te fixe longuement, puis détourne les yeux vers le quai\./)).toBeVisible();
	await tagged.hover();
	await expect(page.locator('div.fixed.z-50').getByText(descriptor)).toBeVisible();
	await page.screenshot({ path: 'test-results/entity-descriptor.png' });
});

test('bold text written by the narrator gets no tooltip', async ({ page }) => {
	await mockApi(page, gameMocks('**Le** cargo rentre ce soir.', []));
	await openGame(page);

	await expect(page.locator('strong', { hasText: 'Le' })).toBeVisible();
	await expect(page.locator('.cursor-help')).toHaveCount(0);
});

test('a surface inside a longer word is never tagged', async ({ page }) => {
	const narration = "Paraît qu'ils coupent un poste avant la convergence. Le cargo rentre à Vergence ce soir.";
	await mockApi(page, gameMocks(
		narration,
		[{ ...annotation(narration, 'Vergence', 'Vergence'), entity_type: 'location' }],
		{ found: true, tooltip: { icon: '📍', name: 'Vergence', type: 'location', infos: [] } },
	));
	await openGame(page);

	const tagged = page.locator('span.text-blue-400.cursor-help');
	await expect(tagged).toHaveCount(1);
	await expect(tagged).toHaveText('Vergence');
	await expect(page.getByText(/avant la convergence\./)).toBeVisible();
	await page.screenshot({ path: 'test-results/entity-tagging.png' });
});
