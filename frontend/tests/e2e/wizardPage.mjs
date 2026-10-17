/** Locators and steps of the creation wizard, shared by the e2e specs. */
import { expect } from '@playwright/test';

export const SHOTS = 'test-results/screens';

export const loreField = (page) => page.getByPlaceholder(/cyberpunk sous une pluie éternelle/);
export const descriptionField = (page) => page.getByPlaceholder(/ancienne pilote de course/);
export const enhanceButton = (page) => page.getByRole('button', { name: /avec l'IA|Nouvelle version/ });
export const suggestions = (page) => page.getByLabel("Suggéré par l'IA");
export const undoButton = (page) => page.getByRole('button', { name: /Défaire/ });
export const redoButton = (page) => page.getByRole('button', { name: /Refaire/ });
export const worldHeading = (page) => page.getByRole('heading', { name: 'Configuration du monde' });
export const characterHeading = (page) => page.getByRole('heading', { name: 'Création du personnage' });

export async function openWizard(page) {
	await page.goto('/game/');
	await page.getByRole('button', { name: /Nouvelle aventure/ }).click();
	await expect(page.getByText('Moteur', { exact: true })).toBeVisible();
}
