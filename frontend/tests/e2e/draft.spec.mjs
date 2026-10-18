// Creation wizard draft: a world being created survives a reload, can be resumed or dropped.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';
import {
	SHOTS, characterHeading, descriptionField, loreField, openWizard, undoButton, worldHeading,
} from './wizardPage.mjs';

const DRAFT_KEY = 'ldvelh.wizardDraft.u1';
const draftCard = (page) => page.getByRole('heading', { name: 'Création en cours' });
const storedDraft = (page) => page.evaluate(k => JSON.parse(localStorage.getItem(k)), DRAFT_KEY);

async function startWorld(page, lore) {
	await openWizard(page);
	await page.getByRole('button', { name: /Système D6/ }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();
	await loreField(page).fill(lore);
}

test('a reload during the creation goes back to the wizard, same step, same form', async ({ page }) => {
	await mockApi(page);
	await startWorld(page, 'Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: /Brutal/ }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();
	await descriptionField(page).fill('hackeuse en fuite');

	await page.reload();
	await expect(characterHeading(page)).toBeVisible();
	await expect(descriptionField(page)).toHaveValue('hackeuse en fuite');
	await expect(undoButton(page)).toBeDisabled(); // the undo history does not survive a reload
	await page.getByRole('button', { name: 'Retour' }).click();
	await expect(loreField(page)).toHaveValue('Néo-Lyon sous la pluie');
	await expect(page.getByRole('button', { name: /Brutal/ })).toHaveClass(/border-primary/);
	await page.getByRole('button', { name: 'Retour' }).click();
	await expect(page.getByRole('button', { name: /Système D6/ })).toHaveClass(/ring-2/); // selected engine
});

test('leaving the wizard keeps the draft in the game list: resume, or delete it', async ({ page }) => {
	await mockApi(page);
	await startWorld(page, 'Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: 'Retour' }).click();
	await page.getByRole('button', { name: 'Annuler' }).click();

	await expect(draftCard(page)).toBeVisible();
	await expect(page.getByText('Néo-Lyon sous la pluie')).toBeVisible();
	await expect(page.getByText(/Étape 1\/3 · Moteur/)).toBeVisible();
	await page.screenshot({ path: `${SHOTS}/7-draft-card.png`, fullPage: true, animations: 'disabled' });

	// Left on the list, a reload stays on the list
	await page.reload();
	await expect(draftCard(page)).toBeVisible();

	await page.getByRole('button', { name: 'Reprendre' }).click();
	await page.getByRole('button', { name: 'Suivant' }).click();
	await expect(loreField(page)).toHaveValue('Néo-Lyon sous la pluie');

	await page.getByRole('button', { name: 'Retour' }).click();
	await page.getByRole('button', { name: 'Annuler' }).click();
	await page.getByRole('button', { name: 'Supprimer' }).click();
	await expect(draftCard(page)).toHaveCount(0);
	await page.reload();
	await expect(page.getByRole('button', { name: /Nouvelle aventure/ })).toBeVisible();
	await expect(draftCard(page)).toHaveCount(0);
});

test('a new creation replaces the draft at its first change, not before', async ({ page }) => {
	await mockApi(page);
	await startWorld(page, 'Ancien monde');
	await page.goto('/game/'); // leave without "Annuler": the draft says the wizard was open
	await expect(worldHeading(page)).toBeVisible();
	await page.getByRole('button', { name: 'Retour' }).click();
	await page.getByRole('button', { name: 'Annuler' }).click();

	// New creation, left untouched: the old draft is still offered
	await page.getByRole('button', { name: /Nouvelle aventure/ }).click();
	await page.getByRole('button', { name: 'Annuler' }).click();
	await expect(page.getByText('Ancien monde')).toBeVisible();

	// New creation with a change: it becomes the draft
	await page.getByRole('button', { name: /Nouvelle aventure/ }).click();
	await page.getByRole('button', { name: /Narratif/ }).click();
	expect((await storedDraft(page)).form.engine).toBe('narrative');
	await page.getByRole('button', { name: 'Annuler' }).click();
	await expect(page.getByText('Ancien monde')).toHaveCount(0);
	await expect(draftCard(page)).toBeVisible();
});

test('creating the game keeps the draft, attached to it, until the world is created (#88)', async ({ page }) => {
	const api = await mockApi(page);
	await startWorld(page, 'Néo-Lyon sous la pluie');
	await page.getByRole('button', { name: 'Suivant' }).click();
	expect(await storedDraft(page)).not.toBeNull();
	await page.getByRole('button', { name: 'Créer le monde' }).click();
	await expect.poll(() => api.calls.find(c => c.path === '/chat')).toBeTruthy();
	const draft = await storedDraft(page);
	expect(draft.gameId).toBe('00000000-0000-0000-0000-000000000001');
	expect(draft.submitted.worldConfig.lore).toBe('Néo-Lyon sous la pluie');
});
