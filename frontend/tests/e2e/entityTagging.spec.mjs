// Entity mentions are tagged (tooltip) from the stored spans, by offsets and entity id
// (#142, #155): never by matching a name in the text.
import { test, expect } from '@playwright/test';
import { mockApi } from './mockApi.mjs';

const GAME_ID = '00000000-0000-0000-0000-0000000000dd';
const MESSAGE_ID = 'dddddddd-0000-0000-0000-000000000002';
const ENTITY_ID = 'eeeeeeee-0000-0000-0000-000000000001';
const OTHER_ID = 'eeeeeeee-0000-0000-0000-000000000002';
const TAGGED = 'span.text-blue-400.cursor-help';

/**
 * The annotations endpoint over `annotated` ([{message_id, sequence, annotations}],
 * latest first), honouring `limit` (default 10, as the backend) and `before`.
 */
function annotationPages(annotated) {
	return (_body, url) => {
		const limit = Number(url.searchParams.get('limit') || 10);
		const before = url.searchParams.get('before');
		const older = before === null ? annotated : annotated.filter(m => m.sequence < Number(before));
		return { messages: older.slice(0, limit) };
	};
}

/** The batch tooltip endpoint over `tooltips` ({id: tooltip}), for the ids asked. */
function entityTooltips(tooltips) {
	return (_body, url) => {
		const ids = (url.searchParams.get('ids') || '').split(',');
		return { tooltips: Object.fromEntries(ids.filter(id => tooltips[id]).map(id => [id, tooltips[id]])) };
	};
}

/** The mocks of a loaded game showing `messages`, with its annotations and tooltips. */
function gameMocks(messages, annotated, tooltips = {}) {
	return {
		'GET /games': () => ({ games: [{ id: GAME_ID, name: 'Partie Brume', current_cycle: 1 }] }),
		[`GET /games/${GAME_ID}`]: () => ({
			state: { game: { name: 'Partie Brume' }, world_created: true },
			messages,
		}),
		'GET /tooltips/annotations': annotationPages(annotated),
		'GET /tooltips/entities': entityTooltips(tooltips),
	};
}

/** One player action and the narrator message `narration`, with its mentions. */
function oneTurn(narration, annotations, tooltips) {
	return gameMocks(
		[
			{ id: 'dddddddd-0000-0000-0000-000000000001', role: 'user', content: "J'écoute." },
			{ id: MESSAGE_ID, role: 'assistant', content: narration },
		],
		annotations.length ? [{ message_id: MESSAGE_ID, sequence: 2, annotations }] : [],
		tooltips,
	);
}

/** The annotation of the first occurrence of `surface` in `text`, from index `from`. */
function annotation(text, surface, label, { from = 0, id = ENTITY_ID, type = 'character' } = {}) {
	const start = text.indexOf(surface, from);
	return { start, end: start + surface.length, entity_id: id, entity_type: type, label };
}

const tooltip = (name, type = 'character') => ({ icon: '👤', name, type, infos: [], relation: null });

async function openGame(page) {
	await page.goto('/game/');
	await page.getByText('Partie Brume').click();
}

test('a descriptor mention gets its tooltip', async ({ page }) => {
	const descriptor = 'La Kethari âgée';
	const narration = `${descriptor} te fixe longuement, puis détourne les yeux vers le quai.`;
	await mockApi(page, oneTurn(
		narration,
		[annotation(narration, descriptor, descriptor)],
		{ [ENTITY_ID]: tooltip(descriptor) },
	));
	const entityRequest = page.waitForRequest(r => r.url().includes('/tooltips/entities'));
	await openGame(page);

	const url = new URL((await entityRequest).url());
	expect(url.searchParams.get('ids')).toBe(ENTITY_ID);
	expect(url.searchParams.get('gameId')).toBe(GAME_ID);
	const tagged = page.locator(TAGGED);
	await expect(tagged).toHaveCount(1);
	await expect(tagged).toHaveText(descriptor);
	await expect(page.getByText(/te fixe longuement, puis détourne les yeux vers le quai\./)).toBeVisible();
	await tagged.hover();
	await expect(page.locator('div.fixed.z-50').getByText(descriptor)).toBeVisible();
	await page.screenshot({ path: 'test-results/entity-descriptor.png' });
});

test('bold text written by the narrator gets no tooltip', async ({ page }) => {
	await mockApi(page, oneTurn('**Le** cargo rentre ce soir.', []));
	await openGame(page);

	await expect(page.locator('strong', { hasText: 'Le' })).toBeVisible();
	await expect(page.locator('.cursor-help')).toHaveCount(0);
});

test('a surface inside a longer word is never tagged', async ({ page }) => {
	const narration = "Paraît qu'ils coupent un poste avant la convergence. Le cargo rentre à Vergence ce soir.";
	await mockApi(page, oneTurn(
		narration,
		[annotation(narration, 'Vergence', 'Vergence', { type: 'location' })],
		{ [ENTITY_ID]: tooltip('Vergence', 'location') },
	));
	await openGame(page);

	const tagged = page.locator(TAGGED);
	await expect(tagged).toHaveCount(1);
	await expect(tagged).toHaveText('Vergence');
	await expect(page.getByText(/avant la convergence\./)).toBeVisible();
	await page.screenshot({ path: 'test-results/entity-tagging.png' });
});

test('two identical surfaces keep their own entity and tooltip', async ({ page }) => {
	const narration = 'Le garde salue le garde.';
	const first = annotation(narration, 'garde', 'le garde du quai');
	const second = annotation(narration, 'garde', 'le garde de la porte', { from: first.end, id: OTHER_ID });
	await mockApi(page, oneTurn(narration, [first, second], {
		[ENTITY_ID]: tooltip('le garde du quai'),
		[OTHER_ID]: tooltip('le garde de la porte'),
	}));
	await openGame(page);

	const tagged = page.locator(TAGGED);
	await expect(tagged).toHaveCount(2);
	await tagged.nth(0).hover();
	await expect(page.locator('div.fixed.z-50').getByText('le garde du quai')).toBeVisible();
	await page.mouse.move(0, 0);
	await expect(page.locator('div.fixed.z-50')).toHaveCount(0);
	await tagged.nth(1).hover();
	await expect(page.locator('div.fixed.z-50').getByText('le garde de la porte')).toBeVisible();
});

test('every shown message keeps its mentions beyond one page of annotations', async ({ page }) => {
	// 55 annotated narrator messages: more than the backend's default 10 and than one
	// page of 50, so the older ones come from a page read back with `before`.
	const narration = 'Le cargo rentre à Vergence.';
	const messages = [];
	const annotated = [];
	for (let i = 1; i <= 55; i++) {
		const id = `dddddddd-0000-0000-0000-${String(i).padStart(12, '0')}`;
		messages.push({ id, role: 'assistant', content: `${narration} (${i})` });
		annotated.unshift({
			message_id: id,
			sequence: i,
			annotations: [annotation(narration, 'Vergence', 'Vergence', { type: 'location' })],
		});
	}
	const api = await mockApi(page, gameMocks(messages, annotated, { [ENTITY_ID]: tooltip('Vergence', 'location') }));
	await openGame(page);

	await expect(page.locator(TAGGED)).toHaveCount(55);
	const pages = api.calls.filter(c => c.path === '/tooltips/annotations');
	expect(pages.length).toBeGreaterThanOrEqual(2);
	// One batch request for the one entity, not one per message.
	expect(api.calls.filter(c => c.path === '/tooltips/entities')).toHaveLength(1);
});

test('the world panel sets apart an NPC not identified, under its descriptor', async ({ page }) => {
	await mockApi(page, {
		...oneTurn('Le quai est calme.', []),
		[`GET /games/${GAME_ID}/world`]: () => ({
			npcs: [
				{ id: 'n1', name: 'Ossek', known: true, relationship: 'Neutre', relation_level: 5 },
				{ id: 'n2', name: 'La silhouette au manteau gris', known: false, relationship: null, relation_level: null },
			],
			locations: [],
			quests: [],
			organizations: [],
		}),
	});
	await openGame(page);
	await page.getByTitle('Monde').click();

	const unknown = page.locator('[data-known="false"]');
	await expect(unknown).toHaveCount(1);
	await expect(unknown).toHaveText('La silhouette au manteau gris');
	await expect(unknown.locator('span.italic')).toBeVisible();
	await expect(page.locator('[data-known="true"]')).toHaveText('Ossek');
});
