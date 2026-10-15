// End-to-end tests of the static export against a mocked API (see tests/e2e/).
// Run: npm run test:e2e (builds, serves out/ on :3100, runs Chromium headless).
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: 'tests/e2e',
	outputDir: 'test-results',
	timeout: 30_000,
	use: {
		baseURL: 'http://localhost:3100',
		screenshot: 'only-on-failure',
		trace: 'retain-on-failure',
	},
	projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
	webServer: {
		command: 'npx serve out -l 3100',
		url: 'http://localhost:3100',
		reuseExistingServer: true,
	},
});
