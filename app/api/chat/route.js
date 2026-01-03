import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT } from '../../../lib/prompt';
import { buildContextForClaude } from '../../../lib/contextBuilder';
import { updatePnjContact, extractPnjFromNarratif } from '../../../lib/interactionTracker';
import { extraireFaits, sauvegarderFaits, PROMPT_ADDON_FAITS } from '../../../lib/faitsService';

export const dynamic = 'force-dynamic';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase = createClient(
	process.env.NEXT_PUBLIC_SUPABASE_URL,
	process.env.SUPABASE_SERVICE_KEY
);

// ============================================================================
// FONCTIONS DE RÉPARATION JSON
// ============================================================================

function tryFixJSON(jsonStr) {
	if (!jsonStr || typeof jsonStr !== 'string') return null;
	let fixed = jsonStr.trim();
	if (fixed.startsWith('```json')) fixed = fixed.slice(7);
	if (fixed.startsWith('```')) fixed = fixed.slice(3);
	if (fixed.endsWith('```')) fixed = fixed.slice(0, -3);
	fixed = fixed.trim();
	const firstBrace = fixed.indexOf('{');
	if (firstBrace > 0) fixed = fixed.slice(firstBrace);
	else if (firstBrace === -1) return null;
	try { return JSON.parse(fixed); } catch (e) { }
	let lastValidIndex = -1, braceCount = 0, inString = false, escapeNext = false;
	for (let i = 0; i < fixed.length; i++) {
		const char = fixed[i];
		if (escapeNext) { escapeNext = false; continue; }
		if (char === '\\' && inString) { escapeNext = true; continue; }
		if (char === '"' && !escapeNext) { inString = !inString; continue; }
		if (!inString) {
			if (char === '{') braceCount++;
			if (char === '}') { braceCount--; if (braceCount === 0) lastValidIndex = i; }
		}
	}
	if (lastValidIndex > 0) {
		try { return JSON.parse(fixed.slice(0, lastValidIndex + 1)); } catch (e) { }
	}
	let openBraces = 0, openBrackets = 0;
	inString = false; escapeNext = false;
	for (let i = 0; i < fixed.length; i++) {
		const char = fixed[i];
		if (escapeNext) { escapeNext = false; continue; }
		if (char === '\\' && inString) { escapeNext = true; continue; }
		if (char === '"') { inString = !inString; continue; }
		if (!inString) {
			if (char === '{') openBraces++;
			if (char === '}') openBraces--;
			if (char === '[') openBrackets++;
			if (char === ']') openBrackets--;
		}
	}
	if (inString) fixed += '"';
	while (openBrackets > 0) { fixed += ']'; openBrackets--; }
	while (openBraces > 0) { fixed += '}'; openBraces--; }
	try { return JSON.parse(fixed); } catch (e) { }
	fixed = fixed.replace(/,(\s*[}\]])/g, '$1').replace(/:\s*([}\]])/g, ': null$1').replace(/:\s*,/g, ': null,');
	try { return JSON.parse(fixed); } catch (e) { return null; }
}

function extractJSON(content) {
	if (!content) return null;
	if (content.trim().startsWith('{')) {
		const result = tryFixJSON(content);
		if (result) return result;
	}
	const lastBraceIndex = content.lastIndexOf('\n{');
	if (lastBraceIndex > 0) {
		const result = tryFixJSON(content.slice(lastBraceIndex + 1));
		if (result) return result;
	}
	const firstBraceIndex = content.indexOf('{');
	if (firstBraceIndex >= 0) {
		const result = tryFixJSON(content.slice(firstBraceIndex));
		if (result) return result;
	}
	return null;
}

// ============================================================================
// VALIDATION ET MERGE DU STATE
// ============================================================================

function validateAndMergeState(existingState, newState) {
	if (!newState) return null;
	return {
		cycle: newState.cycle ?? existingState?.partie?.cycle_actuel ?? 1,
		jour: newState.jour ?? existingState?.partie?.jour ?? 'Lundi',
		date_jeu: newState.date_jeu ?? existingState?.partie?.date_jeu,
		valentin: newState.valentin
			? { ...(existingState?.valentin || {}), ...newState.valentin }
			: existingState?.valentin,
		ia: newState.ia
			? { ...(existingState?.ia || {}), ...newState.ia }
			: existingState?.ia,
		pnj: Array.isArray(newState.pnj) && newState.pnj.length > 0
			? newState.pnj
			: (existingState?.pnj || []),
		arcs: Array.isArray(newState.arcs) && newState.arcs.length > 0
			? newState.arcs
			: (existingState?.arcs || []),
		lieux: Array.isArray(newState.lieux) && newState.lieux.length > 0
			? newState.lieux
			: (existingState?.lieux || []),
		a_venir: Array.isArray(newState.a_venir)
			? newState.a_venir
			: (existingState?.aVenir || [])
	};
}

// ============================================================================
// CHARGEMENT DES DONNÉES
// ============================================================================

async function loadGameState(partieId) {
	const [partie, valentin, ia, pnj, arcs, lieux, aVenir] = await Promise.all([
		supabase.from('parties').select('*').eq('id', partieId).single(),
		supabase.from('valentin').select('*').eq('partie_id', partieId).single(),
		supabase.from('ia_personnelle').select('*').eq('partie_id', partieId).single(),
		supabase.from('pnj').select('*').eq('partie_id', partieId),
		supabase.from('arcs').select('*').eq('partie_id', partieId),
		supabase.from('lieux').select('*').eq('partie_id', partieId),
		supabase.from('a_venir').select('*').eq('partie_id', partieId).eq('realise', false)
	]);

	return {
		partie: partie.data,
		valentin: valentin.data,
		ia: ia.data,
		pnj: pnj.data || [],
		arcs: arcs.data || [],
		lieux: lieux.data || [],
		aVenir: aVenir.data || []
	};
}

async function loadChatMessages(partieId) {
	const { data } = await supabase.from('chat_messages').select('role, content, cycle, created_at')
		.eq('partie_id', partieId).order('created_at', { ascending: true });
	return data || [];
}

// ============================================================================
// GÉNÉRATION RÉSUMÉ CYCLE
// ============================================================================

async function generateCycleResume(partieId, cycle, messages, gameState) {
	if (!messages || messages.length === 0) return null;
	const prompt = `Résume ce cycle en 2 phrases max. Liste max 2 événements clés.\nCycle ${cycle}:\n${messages.map(m => `${m.role}: ${m.content.slice(0, 200)}`).join(' | ')}\nRéponds en JSON uniquement:\n{"resume": "...", "evenements_cles": ["...", "..."]}`;
	try {
		const response = await anthropic.messages.create({
			model: 'claude-sonnet-4-20250514', max_tokens: 300,
			messages: [{ role: 'user', content: prompt }]
		});
		let content = response.content[0].text.trim();
		if (content.startsWith('```json')) content = content.slice(7);
		if (content.startsWith('```')) content = content.slice(3);
		if (content.endsWith('```')) content = content.slice(0, -3);
		const parsed = JSON.parse(content.trim());
		await supabase.from('cycle_resumes').upsert({
			partie_id: partieId, cycle, jour: gameState?.partie?.jour,
			date_jeu: gameState?.partie?.date_jeu, resume: parsed.resume,
			evenements_cles: parsed.evenements_cles || []
		});
		return parsed;
	} catch (e) { console.error('Erreur génération résumé:', e); return null; }
}

// ============================================================================
// SAUVEGARDE STATE
// ============================================================================

async function saveGameState(partieId, state) {
	const { partie, valentin, ia, pnj, arcs, lieux, aVenir } = state;

	const batch1 = [];

	if (partie) {
		batch1.push(
			supabase.from('parties').update({
				cycle_actuel: partie.cycle_actuel,
				jour: partie.jour,
				date_jeu: partie.date_jeu,
				heure: partie.heure
			}).eq('id', partieId)
		);
	}

	if (valentin) {
		batch1.push(supabase.from('valentin').update(valentin).eq('partie_id', partieId));
	}

	if (ia) {
		batch1.push(supabase.from('ia_personnelle').update(ia).eq('partie_id', partieId));
	}

	if (batch1.length > 0) {
		const results = await Promise.all(batch1);
		results.forEach((r, i) => {
			if (r.error) console.error(`Batch1[${i}] error:`, r.error);
		});
	}

	const batch2 = [];

	if (pnj?.length > 0) {
		for (const p of pnj.filter(x => x.id)) {
			batch2.push(supabase.from('pnj').update(p).eq('id', p.id));
		}
		const ins = pnj.filter(x => !x.id).map(x => ({ ...x, partie_id: partieId }));
		if (ins.length > 0) batch2.push(supabase.from('pnj').insert(ins));
	}

	if (arcs?.length > 0) {
		for (const a of arcs.filter(x => x.id)) {
			batch2.push(supabase.from('arcs').update(a).eq('id', a.id));
		}
		const ins = arcs.filter(x => !x.id).map(x => ({ ...x, partie_id: partieId }));
		if (ins.length > 0) batch2.push(supabase.from('arcs').insert(ins));
	}

	if (lieux?.length > 0) {
		for (const l of lieux.filter(x => x.id)) {
			batch2.push(supabase.from('lieux').update(l).eq('id', l.id));
		}
		const ins = lieux.filter(x => !x.id).map(x => ({ ...x, partie_id: partieId }));
		if (ins.length > 0) batch2.push(supabase.from('lieux').insert(ins));
	}

	if (aVenir?.length > 0) {
		for (const x of aVenir.filter(x => x.id)) {
			batch2.push(supabase.from('a_venir').update(x).eq('id', x.id));
		}
		const ins = aVenir.filter(x => !x.id).map(x => ({ ...x, partie_id: partieId }));
		if (ins.length > 0) batch2.push(supabase.from('a_venir').insert(ins));
	}

	if (batch2.length > 0) {
		const results = await Promise.all(batch2);
		results.forEach((r, i) => {
			if (r.error) console.error(`Batch2[${i}] error:`, r.error);
		});
	}
}

// ============================================================================
// GESTION PARTIES
// ============================================================================

async function deleteGame(partieId) {
	await Promise.all([
		supabase.from('chat_messages').delete().eq('partie_id', partieId),
		supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
		supabase.from('interactions').delete().eq('partie_id', partieId),
		supabase.from('faits').delete().eq('partie_id', partieId),
		supabase.from('lieux').delete().eq('partie_id', partieId),
		supabase.from('a_venir').delete().eq('partie_id', partieId),
		supabase.from('arcs').delete().eq('partie_id', partieId),
		supabase.from('pnj').delete().eq('partie_id', partieId),
		supabase.from('ia_personnelle').delete().eq('partie_id', partieId),
		supabase.from('valentin').delete().eq('partie_id', partieId)
	]);
	await supabase.from('parties').delete().eq('id', partieId);
}

async function createNewGame() {
	const { data: partie, error } = await supabase
		.from('parties')
		.insert({ nom: 'Nouvelle partie', cycle_actuel: 1, active: true, options: { faits_enabled: true } })
		.select()
		.single();
	if (error) throw error;

	await Promise.all([
		supabase.from('valentin').insert({ partie_id: partie.id }),
		supabase.from('ia_personnelle').insert({ partie_id: partie.id })
	]);

	return partie.id;
}

// ============================================================================
// GET HANDLER
// ============================================================================

export async function GET(request) {
	const { searchParams } = new URL(request.url);
	const action = searchParams.get('action');
	const partieId = searchParams.get('partieId');

	if (action === 'load' && partieId) {
		const state = await loadGameState(partieId);
		const messages = await loadChatMessages(partieId);
		return Response.json({ state, messages });
	}
	if (action === 'list') {
		const { data } = await supabase.from('parties')
			.select('id, nom, cycle_actuel, updated_at, created_at, options')
			.eq('active', true).order('updated_at', { ascending: false });
		return Response.json({ parties: data });
	}
	if (action === 'new') {
		try {
			const partieId = await createNewGame();
			return Response.json({ partieId });
		} catch (e) { return Response.json({ error: e.message }, { status: 500 }); }
	}
	if (action === 'delete' && partieId) {
		await deleteGame(partieId);
		return Response.json({ success: true });
	}
	if (action === 'rename' && partieId) {
		const newName = searchParams.get('name');
		if (newName) {
			await supabase.from('parties').update({ nom: newName }).eq('id', partieId);
			return Response.json({ success: true });
		}
		return Response.json({ error: 'Nom manquant' }, { status: 400 });
	}
	if (action === 'toggle-faits' && partieId) {
		const enabled = searchParams.get('enabled') === 'true';
		const { data: current } = await supabase.from('parties').select('options').eq('id', partieId).single();
		const newOptions = { ...(current?.options || {}), faits_enabled: enabled };
		await supabase.from('parties').update({ options: newOptions }).eq('id', partieId);
		return Response.json({ success: true, faits_enabled: enabled });
	}
	return Response.json({ error: 'Action non reconnue' });
}

// ============================================================================
// DELETE HANDLER
// ============================================================================

export async function DELETE(request) {
	try {
		const { partieId, fromIndex } = await request.json();
		if (!partieId) return Response.json({ error: 'partieId manquant' }, { status: 400 });
		const { data: allMessages } = await supabase.from('chat_messages')
			.select('id, created_at').eq('partie_id', partieId).order('created_at', { ascending: true });
		if (!allMessages || fromIndex >= allMessages.length) return Response.json({ success: true });
		const messagesToDelete = allMessages.slice(fromIndex).map(m => m.id);
		if (messagesToDelete.length > 0) {
			await supabase.from('chat_messages').delete().in('id', messagesToDelete);
		}
		return Response.json({ success: true, deleted: messagesToDelete.length });
	} catch (e) { return Response.json({ error: e.message }, { status: 500 }); }
}

// ============================================================================
// POST HANDLER
// ============================================================================

export async function POST(request) {
	try {
		const { message, partieId, gameState } = await request.json();
		const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

		let faitsEnabled = true;
		if (partieId) {
			const { data: partieData } = await supabase.from('parties').select('options').eq('id', partieId).single();
			faitsEnabled = partieData?.options?.faits_enabled !== false;
		}

		let contextMessage, knownPnj = [];
		if (partieId && gameState?.partie) {
			try {
				const contextResult = await buildContextForClaude(supabase, partieId, gameState, message, null, { faitsEnabled });
				contextMessage = contextResult.context;
				knownPnj = contextResult.pnj || [];
			} catch (err) {
				console.error('Erreur buildContextForClaude:', err);
				contextMessage = `=== ÉTAT ===\n${JSON.stringify(gameState, null, 1)}\n\n=== ACTION ===\n${message}`;
			}
		} else {
			contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
		}

		const systemPrompt = faitsEnabled ? SYSTEM_PROMPT + PROMPT_ADDON_FAITS : SYSTEM_PROMPT;

		const { readable, writable } = new TransformStream();
		const writer = writable.getWriter();
		const encoder = new TextEncoder();
		let pnjForTracking = knownPnj;

		(async () => {
			let fullContent = '', parsed = null, displayText = '', cycleForSave = currentCycle;

			try {
				const streamResponse = await anthropic.messages.stream({
					model: 'claude-sonnet-4-20250514', max_tokens: 8192,
					system: systemPrompt,
					messages: [{ role: 'user', content: contextMessage }]
				});

				for await (const event of streamResponse) {
					if (event.type === 'content_block_delta' && event.delta?.text) {
						fullContent += event.delta.text;
						await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: event.delta.text })}\n\n`));
					}
				}

				const rawParsed = extractJSON(fullContent);
				const validatedState = rawParsed?.state ? validateAndMergeState(gameState, rawParsed.state) : null;
				parsed = rawParsed ? { ...rawParsed, state: validatedState } : null;

				if (parsed) {
					displayText = '';
					if (parsed.heure) displayText += `[${parsed.heure}] `;
					if (parsed.narratif) displayText += parsed.narratif;
					if (parsed.choix?.length > 0) displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
					cycleForSave = validatedState?.cycle || currentCycle;
				} else {
					displayText = fullContent.replace(/```json[\s\S]*?```/g, '').replace(/\{[\s\S]*\}$/g, '').trim() || "Erreur de génération.";
				}

				await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'done', displayText, state: parsed?.state, heure: parsed?.heure })}\n\n`));

				if (partieId) {
					await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'user', content: message, cycle: cycleForSave });
					await supabase.from('chat_messages').insert({ partie_id: partieId, role: 'assistant', content: displayText, cycle: cycleForSave });
				}
				await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

			} catch (error) {
				console.error('Streaming error:', error);
				try { await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`)); } catch (e) { }
			} finally {
				try { await writer.close(); } catch (e) { }
			}

			// === TÂCHES EN ARRIÈRE-PLAN ===

			if (partieId && pnjForTracking.length === 0) {
				const { data } = await supabase.from('pnj').select('*').eq('partie_id', partieId);
				pnjForTracking = data || [];
			}

			// Mise à jour des relations (nouveau système simplifié)
			if (partieId && parsed?.changements_relation?.length > 0) {
				for (const change of parsed.changements_relation) {
					if (!change.pnj || change.delta === undefined) continue;

					const pnj = pnjForTracking.find(p =>
						p.nom && (
							p.nom.toLowerCase() === change.pnj.toLowerCase() ||
							p.nom.split(' ')[0].toLowerCase() === change.pnj.toLowerCase()
						)
					);

					if (pnj?.id) {
						const currentRelation = pnj.relation || 0;
						const newRelation = Math.max(0, Math.min(10, currentRelation + change.delta));

						await supabase.from('pnj').update({
							relation: newRelation,
							updated_at: new Date().toISOString()
						}).eq('id', pnj.id);

						console.log(`>>> Relation ${pnj.nom}: ${currentRelation} → ${newRelation} (${change.delta > 0 ? '+' : ''}${change.delta}: ${change.raison})`);
					}
				}
			}

			// Mise à jour dernier_contact pour PNJ mentionnés dans le narratif
			if (partieId && parsed?.narratif && pnjForTracking.length > 0) {
				const pnjMentionnes = extractPnjFromNarratif(parsed.narratif, pnjForTracking);
				if (pnjMentionnes.length > 0) {
					updatePnjContact(supabase, partieId, cycleForSave, pnjMentionnes)
						.then(r => console.log(`>>> Contact: ${r.updated} PNJ mis à jour`))
						.catch(err => console.error('Erreur updatePnjContact:', err));
				}
			}

			if (partieId && parsed && faitsEnabled) {
				try {
					const extraction = extraireFaits(parsed, cycleForSave);
					if (extraction.nouveaux.length > 0 || extraction.modifies.length > 0) {
						const pnjMap = new Map(pnjForTracking.map(p => [p.nom.toLowerCase(), p.id]));
						const resultats = await sauvegarderFaits(supabase, partieId, extraction, pnjMap);
						console.log(`>>> Faits: +${resultats.ajoutes} ajoutés, ~${resultats.invalides} invalidés`);
					}
				} catch (err) { console.error('Erreur faits:', err); }
			}

			if (partieId && parsed?.state) {
				saveGameState(partieId, {
					partie: { cycle_actuel: parsed.state.cycle, jour: parsed.state.jour, date_jeu: parsed.state.date_jeu, heure: parsed.heure },
					valentin: parsed.state.valentin,
					ia: parsed.state.ia,
					pnj: parsed.state.pnj,
					arcs: parsed.state.arcs,
					lieux: parsed.state.lieux,
					aVenir: parsed.state.a_venir
				}).catch(err => console.error('Erreur save state:', err));
			}

			if (partieId && parsed && cycleForSave > currentCycle) {
				supabase.from('chat_messages').select('role, content').eq('partie_id', partieId).eq('cycle', currentCycle)
					.order('created_at', { ascending: true })
					.then(({ data }) => data && generateCycleResume(partieId, currentCycle, data, gameState))
					.catch(err => console.error('Erreur résumé:', err));
			}
		})();

		return new Response(readable, {
			headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' }
		});
	} catch (e) {
		console.error('Erreur POST:', e);
		return Response.json({ error: e.message }, { status: 500 });
	}
}
