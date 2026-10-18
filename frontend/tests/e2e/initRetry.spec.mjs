// A failed world generation (#88): the wizard draft stays attached to the game until its
// world exists; reopening the game offers to retry with the same parameters, or to edit them.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';
import { SHOTS, loreField, nameField, openWizard } from './wizardPage.mjs';

const GAME_ID = '00000000-0000-0000-0000-000000000088';
const DRAFT_KEY = 'ldvelh.wizardDraft.u1';
const GAME_DRAFT_KEY = `${DRAFT_KEY}.${GAME_ID}`;
const FAILED = 'Échec de génération du monde. Réessaie.';
const storedDraft = (page, key = GAME_DRAFT_KEY) => page.evaluate(k => JSON.parse(localStorage.getItem(k)), key);
const initParams = ({ engine, world_config, character_data, manual_entities }) =>
	({ engine, world_config, character_data, manual_entities });

const WORLD_DONE = [
	{ type: 'done', displayText: null, state: {
		game_state: { game: { name: 'Station Kira', engine: 'd6' }, player: {}, world_created: true },
		world_info: { world: { name: 'Station Kira' }, npc_count: 2, location_count: 3, org_count: 1 },
	} },
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

/** Mocked API: the first __INIT__ fails, the next ones create the world; the server keeps
 * the parameters of the last __INIT__ that carried them (init_params). */
async function failingFirstInit(page) {
	let created = false;
	let inits = 0;
	let stored = null;
	const api = await mockApi(page, {
		'POST /games': () => { created = true; return { gameId: GAME_ID }; },
		'GET /games': () => ({ games: created ? [{ id: GAME_ID, name: 'Nouvelle partie', current_cycle: 0 }] : [] }),
		[`DELETE /games/${GAME_ID}`]: () => { created = false; return { success: true }; },
		[`GET /games/${GAME_ID}`]: () => ({
			state: { game: { name: 'Nouvelle partie', engine: 'd6' }, player: {}, world_created: false },
			messages: [],
			init_params: stored,
		}),
		'POST /chat': (body) => {
			if ('world_config' in body) stored = initParams(body);
			inits += 1;
			return { __sse: inits === 1
				? [{ type: 'error', error: FAILED, code: 'world_gen_failed', recoverable: true }]
				: WORLD_DONE };
		},
	});
	return { api, chats: () => api.calls.filter(c => c.path === '/chat').map(c => c.body) };
}

async function createWorldThatFails(page, chats) {
	await openWizard(page);
	await page.getByRole('button', { name: /Système D6/ }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();
	await page.getByRole('button', { name: /Cyberpunk/ }).click();
	await loreField(page).fill('Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: 'Suivant' }).click();
	await nameField(page).fill('Kira');
	await page.getByRole('button', { name: 'Créer le monde' }).click();
	await expect(page.getByText(FAILED)).toBeVisible();
	expect(chats()).toHaveLength(1);
}

async function reopenFromList(page) {
	await page.getByRole('button', { name: 'Retour aux parties' }).click();
	await expect(page.getByRole('heading', { name: 'Création en cours' })).toHaveCount(0); // attached to the game
	await page.getByText('Nouvelle partie', { exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Monde à créer' })).toBeVisible();
}

test('init fails, back to the list, reopen: the retry sends the original parameters', async ({ page }) => {
	const { api, chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.screenshot({ path: `${SHOTS}/88-1-init-failed.png`, fullPage: true, animations: 'disabled' });
	const first = chats()[0];
	expect(first.world_config).toMatchObject({ genre: 'cyberpunk', lore: 'Néo-Lyon sous la pluie' });
	expect((await storedDraft(page)).gameId).toBe(GAME_ID); // kept: the world does not exist yet
	expect(await storedDraft(page, DRAFT_KEY)).toBeNull(); // moved under the game's key

	await reopenFromList(page);
	await expect(page.getByTestId('pending-params')).toContainText('Néo-Lyon sous la pluie');
	await expect(page.getByTestId('pending-params')).toContainText('Kira');
	await expect(page.getByTestId('pending-params')).toContainText('Genre : Cyberpunk'); // the label
	await page.screenshot({ path: `${SHOTS}/88-2-reopened-pending.png`, fullPage: true, animations: 'disabled' });

	await page.getByRole('button', { name: 'Réessayer' }).click();
	await expect(page.getByRole('heading', { name: /Monde créé/ })).toBeVisible();
	const retry = chats()[1];
	expect(retry.gameId).toBe(GAME_ID);
	expect(initParams(retry)).toEqual(initParams(first));
	expect(api.calls.filter(c => c.method === 'POST' && c.path === '/games')).toHaveLength(1);
	await expect.poll(() => storedDraft(page)).toBeNull(); // world created: the draft is done
	await page.screenshot({ path: `${SHOTS}/88-3-world-created.png`, fullPage: true, animations: 'disabled' });
});

test('init fails: retry right away, or edit the parameters of the same game', async ({ page }) => {
	const { api, chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await reopenFromList(page);

	await page.getByRole('button', { name: 'Modifier les paramètres' }).click();
	await expect(nameField(page)).toHaveValue('Kira');
	await page.getByRole('button', { name: 'Retour' }).click();
	await loreField(page).fill('Lyon engloutie');
	await page.getByRole('button', { name: 'Suivant' }).click();
	await page.getByRole('button', { name: 'Créer le monde' }).click();
	await expect(page.getByRole('heading', { name: /Monde créé/ })).toBeVisible();

	const retry = chats()[1];
	expect(retry.gameId).toBe(GAME_ID); // same game, not a new one
	expect(retry.world_config.lore).toBe('Lyon engloutie');
	expect(retry.character_data.name).toBe('Kira');
	expect(api.calls.filter(c => c.method === 'POST' && c.path === '/games')).toHaveLength(1);
	await expect.poll(() => storedDraft(page)).toBeNull();
});

test('the retry button of the failed generation screen resends the same parameters', async ({ page }) => {
	const { chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.getByRole('button', { name: 'Réessayer' }).click();
	await expect(page.getByRole('heading', { name: /Monde créé/ })).toBeVisible();
	expect(initParams(chats()[1])).toEqual(initParams(chats()[0]));
});

test('another creation started meanwhile does not take the failed game\'s draft', async ({ page }) => {
	const { chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.getByRole('button', { name: 'Retour aux parties' }).click();

	// Game B: a new creation, changed, then left in the list
	await page.getByRole('button', { name: /Nouvelle aventure/ }).click();
	await page.getByRole('button', { name: /Narratif/ }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();
	await loreField(page).fill('Un autre monde');
	await page.getByRole('button', { name: 'Retour' }).click();
	await page.getByRole('button', { name: 'Annuler' }).click();
	await expect(page.getByRole('heading', { name: 'Création en cours' })).toBeVisible();

	// Back to A: its own parameters
	await page.getByText('Nouvelle partie', { exact: true }).click();
	await expect(page.getByTestId('pending-params')).toContainText('Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: 'Modifier les paramètres' }).click();
	await expect(nameField(page)).toHaveValue('Kira');
	await page.getByRole('button', { name: 'Retour' }).click();
	await expect(loreField(page)).toHaveValue('Néo-Lyon sous la pluie');
	expect((await storedDraft(page, DRAFT_KEY)).form.worldConfig.lore).toBe('Un autre monde'); // B kept too
});

test('without a local draft, the pending game shows and edits the server parameters', async ({ page }) => {
	const { chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.evaluate(k => localStorage.removeItem(k), GAME_DRAFT_KEY); // another browser
	await page.reload();
	await page.getByText('Nouvelle partie', { exact: true }).click();
	await expect(page.getByTestId('pending-params')).toContainText('Néo-Lyon sous la pluie');
	await expect(page.getByTestId('pending-params')).toContainText('Genre : Cyberpunk');

	// Réessayer without a draft: a bare __INIT__, the server reuses its set
	await page.getByRole('button', { name: 'Réessayer' }).click();
	await expect(page.getByRole('heading', { name: /Monde créé/ })).toBeVisible();
	expect('world_config' in chats()[1]).toBe(false);
});

test('without a local draft, « Modifier les paramètres » is prefilled from the server', async ({ page }) => {
	const { chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.evaluate(k => localStorage.removeItem(k), GAME_DRAFT_KEY);
	await page.reload();
	await page.getByText('Nouvelle partie', { exact: true }).click();
	await page.getByRole('button', { name: 'Modifier les paramètres' }).click();
	await expect(nameField(page)).toHaveValue('Kira');
	await page.getByRole('button', { name: 'Retour' }).click();
	await expect(loreField(page)).toHaveValue('Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: 'Suivant' }).click();
	await page.getByRole('button', { name: 'Créer le monde' }).click();
	await expect(page.getByRole('heading', { name: /Monde créé/ })).toBeVisible();
	expect(initParams(chats()[1])).toEqual(initParams(chats()[0])); // same set, round-tripped
});

test('deleting the failed game drops its draft', async ({ page }) => {
	const { chats } = await failingFirstInit(page);
	await createWorldThatFails(page, chats);
	await page.getByRole('button', { name: 'Retour aux parties' }).click();
	await page.getByText('Nouvelle partie', { exact: true }).hover();
	await page.getByTitle('Supprimer').click();
	await page.getByRole('button', { name: 'Confirmer' }).click();
	await expect(page.getByText('Nouvelle partie', { exact: true })).toHaveCount(0);
	await expect.poll(() => storedDraft(page)).toBeNull();
});
