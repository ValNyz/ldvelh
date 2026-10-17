// Logout revokes the session on the backend before leaving (#83).
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

test('Deconnexion calls /auth/logout, then opens the login page', async ({ page }) => {
	const api = await mockApi(page, { 'POST /auth/logout': () => ({ success: true }) });
	await page.goto('/game/');
	await page.getByRole('button', { name: 'Deconnexion' }).click();
	await expect(page).toHaveURL(/\/login\/?$/);
	expect(api.calls.filter(c => c.method === 'POST' && c.path === '/auth/logout')).toHaveLength(1);
});
