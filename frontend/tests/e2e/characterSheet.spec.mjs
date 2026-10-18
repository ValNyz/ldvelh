// Character sheet (F-26, #93): Fate aspects + skill pyramid, D6 attributes + skills,
// refreshed by the `done` payload of a turn.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000cc';
const MESSAGES = [
	{ role: 'user', content: 'Je regarde autour de moi.' },
	{ role: 'assistant', content: 'Le hangar est désert.' },
];

const FATE_PLAYER = {
	credits: 1400,
	inventory: [],
	engine_stats: {
		stress_physical: [true, false], stress_mental: [false, false],
		consequences: { mild: null }, fate_points: 3, refresh: 3,
	},
	sheet: {
		aspects: [
			{ type: 'high_concept', name: 'Pilote déchu en quête de rédemption' },
			{ type: 'trouble', name: "Je dois de l'argent à tout le monde" },
			{ type: 'other', name: 'Mon vieux cargo est ma maison' },
		],
		skills: [
			{ name: 'Athlétisme', level: 4, label: 'Excellent' },
			{ name: 'Pilotage', level: 3, label: 'Bon' },
			{ name: 'Empathie', level: 3, label: 'Bon' },
			{ name: 'Combat', level: 2, label: 'Correct' },
			{ name: 'Discrétion', level: 2, label: 'Correct' },
			{ name: 'Volonté', level: 2, label: 'Correct' },
			{ name: 'Contacts', level: 1, label: 'Moyen' },
			{ name: 'Ressources', level: 1, label: 'Moyen' },
			{ name: 'Physique', level: 1, label: 'Moyen' },
			{ name: 'Tromperie', level: 1, label: 'Moyen' },
		],
		stunts: [
			"Tireur d'élite",
			{ name: 'Réflexes', description: '+2 en initiative' },
			{ name: '', description: 'Toujours prêt' },
			{},
		],
	},
};

const D6_PLAYER = {
	credits: 900,
	inventory: [],
	engine_stats: { wounds: { stunned: true }, force_points: 1 },
	sheet: {
		attributes: { 'Dextérité': '3D', 'Mécanique': '3D', 'Perception': '3D+1' },
		skills: [
			{ attribute: 'Dextérité', name: 'Blaster', dice_value: '4D' },
			{ attribute: 'Mécanique', name: 'Pilotage', dice_value: '3D+2' },
		],
	},
};

const loaded = (engine, player) => ({
	state: { game: { name: 'Partie fiche', engine }, player, world_created: true },
	messages: MESSAGES,
});

let crashes;
test.beforeEach(({ page }) => {
	crashes = [];
	page.on('pageerror', e => crashes.push(e.message));
	page.on('console', m => {
		if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) crashes.push(m.text());
	});
});
test.afterEach(() => expect(crashes).toEqual([]));

async function openSheet(page, handlers) {
	await mockApi(page, {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie fiche', current_cycle: 1 }] }),
		...handlers,
	});
	await page.goto('/game/');
	await page.getByText('Partie fiche').click();
	await page.getByTitle('Fiche personnage').click();
	await expect(page.getByRole('heading', { name: 'Fiche personnage' })).toBeVisible();
}

test('Fate sheet shows high concept, trouble, aspects and the skill pyramid', async ({ page }, testInfo) => {
	const raised = {
		...FATE_PLAYER.sheet,
		skills: FATE_PLAYER.sheet.skills.map(s => (s.name === 'Combat' ? { ...s, level: 3, label: 'Bon' } : s)),
	};
	await openSheet(page, {
		[`GET /games/${GAME_ID}`]: () => loaded('fate_core', FATE_PLAYER),
		'POST /chat': () => ({ __sse: [
			{ type: 'chunk', content: 'Tu progresses.' },
			{ type: 'done', displayText: 'Tu progresses.', state: { game_state: {
				game: { name: 'Partie fiche', engine: 'fate_core' },
				player: { ...FATE_PLAYER, sheet: raised },
			} } },
			{ type: 'saved' },
		] }),
	});

	const sheet = page.locator('h2', { hasText: 'Fiche personnage' }).locator('xpath=../..');
	// Each label sits on its own aspect's card.
	const cards = sheet.getByTestId('aspect-card');
	await expect(cards).toHaveText([
		'ConceptPilote déchu en quête de rédemption',
		"ProblèmeJe dois de l'argent à tout le monde",
		'AspectMon vieux cargo est ma maison',
	]);
	// Stunts: a string, a dict, a dict without a name; the empty one is skipped.
	await expect(sheet.getByText("Tireur d'élite")).toBeVisible();
	await expect(sheet.getByText('Réflexes')).toBeVisible();
	await expect(sheet.getByText('+2 en initiative')).toBeVisible();
	await expect(sheet.getByText('Toujours prêt')).toBeVisible();
	await expect(sheet.getByText('+4 Excellent')).toBeVisible();
	await expect(sheet.getByText('Athlétisme', { exact: true })).toBeVisible();
	await expect(sheet.getByText('Pilotage, Empathie')).toBeVisible();
	await expect(sheet.getByText('Combat, Discrétion, Volonté')).toBeVisible();
	await expect(sheet.getByText('Contacts, Ressources, Physique, Tromperie')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('character-sheet-fate.png') });
	await sheet.getByText('Toujours prêt').scrollIntoViewIfNeeded();
	await page.screenshot({ path: testInfo.outputPath('character-sheet-fate-stunts.png') });

	// The done payload of a turn refreshes the open sheet.
	const input = page.getByPlaceholder(/Ton action/);
	await input.fill("Je m'entraîne.");
	await input.press('Control+Enter');
	await expect(page.getByText('Tu progresses.').last()).toBeVisible();
	await expect(sheet.getByText('Pilotage, Empathie, Combat')).toBeVisible();
	await expect(sheet.getByText('Discrétion, Volonté')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('character-sheet-fate-after-turn.png') });
});

test('D6 sheet shows attributes and their skills', async ({ page }, testInfo) => {
	await openSheet(page, { [`GET /games/${GAME_ID}`]: () => loaded('d6', D6_PLAYER) });

	const sheet = page.locator('h2', { hasText: 'Fiche personnage' }).locator('xpath=../..');
	await expect(sheet.getByText('Attributs et compétences')).toBeVisible();
	// Each skill sits under its own attribute, with its dice code.
	await expect(sheet.getByTestId('d6-attribute')).toHaveText([
		'Dextérité3DBlaster4D',
		'Mécanique3DPilotage3D+2',
		'Perception3D+1',
	]);
	await expect(sheet.getByText('1 PF')).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('character-sheet-d6.png') });
});
