// Creation wizard: AI fill of each step, undo / redo over the whole form, D6 skills, payload sent.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const SHOTS = 'test-results/screens';

const WORLD_FILL = {
	world_config: {
		genre: 'cyberpunk', difficulty: 'hard', duration: 'short', hardcore: false,
		lore: 'Néo-Lyon, 2093 : une pluie acide qui ne cesse jamais, des tours corporatistes qui percent les nuages.',
	},
	manual_entities: {
		npcs: [{ name: 'Rook', description: 'Fixer qui doit trop de faveurs.' }],
		locations: [{ name: 'Le Puits', description: 'Marché noir sous les fondations.' }],
		organizations: [{ name: 'Helix Corp', description: 'Biotech qui traque les hackers.' }],
	},
	cost: null,
};

const CHARACTER_FILL = {
	character_data: {
		name: 'Nyx', gender: 'non-binary', occupation: 'hackeuse',
		description: 'Ancienne ingénieure d’Helix, yeux chromés, elle a volé ce qu’il ne fallait pas.',
		attributes: { 'Dextérité': '3D+1', 'Connaissance': '3D', 'Mécanique': '2D+2', 'Perception': '3D', 'Force': '2D', 'Technique': '4D' },
		skills: { 'Piratage': '2D', 'Cybernétique': '2D', 'Esquive': '1D+1', 'Armes à feu': '1D+2' },
	},
	cost: null,
};

const loreField = (page) => page.getByPlaceholder(/cyberpunk sous une pluie éternelle/);
const descriptionField = (page) => page.getByPlaceholder(/ancienne pilote de course/);
const enhanceButton = (page) => page.getByRole('button', { name: /Enrichir avec l'IA/ });
const undoButton = (page) => page.getByRole('button', { name: /Défaire/ });
const redoButton = (page) => page.getByRole('button', { name: /Refaire/ });

async function openWizard(page) {
	await page.goto('/game/');
	await page.getByRole('button', { name: /Nouvelle aventure/ }).click();
	await expect(page.getByText('Moteur', { exact: true })).toBeVisible();
}

test('AI fill, undo / redo across steps, D6 skills and the creation payload', async ({ page }) => {
	const api = await mockApi(page, {
		'POST /world/enhance': (body) => (body.scope === 'world' ? WORLD_FILL : CHARACTER_FILL),
	});
	await openWizard(page);

	// Step 1: engine
	await page.getByRole('button', { name: /Système D6/ }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();

	// Step 2: world — the button needs text in "Contexte libre"
	await expect(page.getByRole('heading', { name: 'Configuration du monde' })).toBeVisible();
	await expect(enhanceButton(page)).toBeDisabled();
	await loreField(page).fill('cyberpunk sous la pluie, une corpo traque les hackers');
	await page.screenshot({ path: `${SHOTS}/1-world-typed.png`, fullPage: true, animations: "disabled" });
	await enhanceButton(page).click();

	await expect(loreField(page)).toHaveValue(WORLD_FILL.world_config.lore);
	await expect(page.getByRole('button', { name: /Cyberpunk/ })).toHaveClass(/bg-primary/);
	await expect(page.locator('input[value="Rook"]')).toBeVisible(); // entities section opened
	await expect(page.locator('input[value="Helix Corp"]')).toBeVisible();
	await page.screenshot({ path: `${SHOTS}/2-world-filled.png`, fullPage: true, animations: "disabled" });

	const worldCall = api.calls.find(c => c.path === '/world/enhance');
	expect(worldCall.body).toMatchObject({
		scope: 'world', engine: 'd6', provider: 'anthropic', model: 'claude-sonnet-5-5',
		current: { world_config: { lore: 'cyberpunk sous la pluie, une corpo traque les hackers' } },
	});

	// Undo the AI fill (button), redo it (keyboard)
	await undoButton(page).click();
	await expect(loreField(page)).toHaveValue('cyberpunk sous la pluie, une corpo traque les hackers');
	await expect(page.locator('input[value="Rook"]')).toHaveCount(0);
	await page.keyboard.press('Control+Shift+Z');
	await expect(loreField(page)).toHaveValue(WORLD_FILL.world_config.lore);
	await expect(redoButton(page)).toBeDisabled();

	// Step 3: character
	await page.getByRole('button', { name: 'Suivant' }).click();
	await expect(page.getByRole('heading', { name: 'Création du personnage' })).toBeVisible();
	await descriptionField(page).fill('hackeuse en fuite');
	await enhanceButton(page).click();
	await expect(page.getByPlaceholder('Valentin')).toHaveValue('Nyx');
	await expect(descriptionField(page)).toHaveValue(CHARACTER_FILL.character_data.description);
	await expect(page.getByText('Cybernétique', { exact: true })).toBeVisible(); // cyberpunk D6 skill
	await page.screenshot({ path: `${SHOTS}/3-character-filled.png`, fullPage: true, animations: "disabled" });

	const charCall = api.calls.filter(c => c.path === '/world/enhance')[1];
	expect(charCall.body.scope).toBe('character');
	expect(charCall.body.current.world_config.genre).toBe('cyberpunk');

	// D6 skills: manual allocation respects the 2D cap
	const addTo = (skill) => page.getByRole('button', { name: `Ajouter un cran : ${skill}` });
	await expect(addTo('Esquive')).toBeDisabled();               // 7D all spent
	await page.getByRole('button', { name: 'Retirer un cran : Esquive' }).click();
	await expect(addTo('Esquive')).toBeEnabled();                // one pip free again
	await expect(addTo('Piratage')).toBeDisabled();              // still at the 2D cap
	await addTo('Esquive').click();                              // back to the AI's allocation

	// Undo: the character fill (the -/+ round trip left no entry), the typed description,
	// then back to step 2 for the world fill
	await page.keyboard.press('Control+Z');
	await expect(descriptionField(page)).toHaveValue('hackeuse en fuite');
	await page.keyboard.press('Control+Z');
	await expect(descriptionField(page)).toHaveValue('');
	await page.keyboard.press('Control+Z');
	await expect(page.getByRole('heading', { name: 'Configuration du monde' })).toBeVisible();
	await expect(loreField(page)).toHaveValue('cyberpunk sous la pluie, une corpo traque les hackers');
	await page.screenshot({ path: `${SHOTS}/4-undo-back-to-world.png`, fullPage: true, animations: "disabled" });

	// Redo everything, which lands back on the character step
	for (let i = 0; i < 3; i++) await page.keyboard.press('Control+Y');
	await expect(page.getByRole('heading', { name: 'Création du personnage' })).toBeVisible();
	await expect(page.getByPlaceholder('Valentin')).toHaveValue('Nyx');

	// Create: the /chat init payload carries duration, character and D6 skills in backend format
	await page.getByRole('button', { name: 'Créer le monde' }).click();
	await expect.poll(() => api.calls.find(c => c.path === '/chat')).toBeTruthy();
	const init = api.calls.find(c => c.path === '/chat').body;
	expect(init.engine).toBe('d6');
	expect(init.world_config).toMatchObject({ genre: 'cyberpunk', difficulty: 'hard', duration: 'short' });
	expect(init.manual_entities.npcs).toEqual(WORLD_FILL.manual_entities.npcs);
	expect(init.character_data.name).toBe('Nyx');
	expect(init.character_data.skills).toEqual(expect.arrayContaining([
		{ attribute: 'Technique', name: 'Piratage', dice_value: '6D' },       // 4D + 2D
		{ attribute: 'Dextérité', name: 'Esquive', dice_value: '4D+2' },      // 3D+1 + 1D+1
	]));
});

test('AI fill error is shown and leaves the form untouched', async ({ page }) => {
	await mockApi(page, {
		'POST /world/enhance': () => ({ __status: 502, body: { detail: "L'IA n'a pas pu remplir le formulaire. Réessaie ou reformule ton texte." } }),
	});
	await openWizard(page);
	await page.getByRole('button', { name: 'Suivant' }).click();
	await loreField(page).fill('un monde de cendres');
	await enhanceButton(page).click();
	await expect(page.getByRole('alert').filter({ hasText: "L'IA n'a pas pu" })).toBeVisible();
	await expect(loreField(page)).toHaveValue('un monde de cendres');
	await page.screenshot({ path: `${SHOTS}/5-enhance-error.png`, fullPage: true, animations: "disabled" });
});

test('edits of one field are one undo step until another field changes', async ({ page }) => {
	await mockApi(page);
	await openWizard(page);
	await page.getByRole('button', { name: 'Suivant' }).click();
	await loreField(page).pressSequentially('abc', { delay: 50 });
	await page.waitForTimeout(1500); // a pause does not split the entry
	await loreField(page).pressSequentially(' def', { delay: 50 });
	await page.getByRole('button', { name: /Brutal/ }).click();
	await loreField(page).pressSequentially(' ghi', { delay: 50 });
	await page.keyboard.press('Control+Z'); // the text typed after the click
	await expect(loreField(page)).toHaveValue('abc def');
	await page.keyboard.press('Control+Z'); // difficulty back
	await expect(page.getByRole('button', { name: /Brutal/ })).not.toHaveClass(/border-primary/);
	await expect(loreField(page)).toHaveValue('abc def');
	await page.keyboard.press('Control+Z'); // everything typed before, pause included
	await expect(loreField(page)).toHaveValue('');
});
