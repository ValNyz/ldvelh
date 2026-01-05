/**
 * Service Haiku pour analyses en background
 * - Analyse de scène (changement de lieu)
 * - Analyse intermédiaire (tous les 30 messages)
 * - Fin de cycle (nouveau_cycle: true)
 */

import Anthropic from '@anthropic-ai/sdk';
import { PROMPT_HAIKU_SCENE, PROMPT_HAIKU_NEWCYCLE } from './prompt.js';
import {
	getMessagesScene,
	marquerAnalysee,
	ajouterResumeIntermediaire,
	getDernierMessageScene,
	getScenesCompleteCycle,
	formaterResumesIntermediaires
} from './sceneService.js';
import { sauvegarderFaits } from './faitsService.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const HAIKU_MODEL = 'claude-3-5-haiku-20241022';

// ============================================================================
// UTILITAIRES
// ============================================================================

function tryParseJSON(str) {
	if (!str) return null;
	try {
		let cleaned = str.trim();
		if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
		if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
		if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
		cleaned = cleaned.trim();

		const firstBrace = cleaned.indexOf('{');
		if (firstBrace > 0) cleaned = cleaned.slice(firstBrace);
		if (firstBrace === -1) return null;

		return JSON.parse(cleaned);
	} catch (e) {
		console.error('[Haiku] Erreur parsing JSON:', e.message);
		return null;
	}
}

function formaterMessagesForHaiku(messages) {
	return messages
		.map(m => `${m.role === 'user' ? 'VALENTIN' : 'MJ'}: ${m.content}`)
		.join('\n\n');
}

// ============================================================================
// ANALYSE DE SCÈNE COMPLÈTE (changement de lieu)
// ============================================================================

export async function analyserScene(supabase, partieId, sceneId, lieu, cycleActuel) {
	console.log(`[Haiku] Analyse scène: ${lieu} (scene ${sceneId})`);

	try {
		// Récupérer tous les messages de la scène
		const messages = await getMessagesScene(supabase, sceneId);

		if (messages.length === 0) {
			console.log('[Haiku] Aucun message dans la scène, skip');
			await marquerAnalysee(supabase, sceneId, 'Scène sans contenu');
			return null;
		}

		// Récupérer les résumés intermédiaires s'il y en a
		const { data: scene } = await supabase
			.from('scenes')
			.select('resume_intermediaire')
			.eq('id', sceneId)
			.single();

		const resumesIntermediaires = formaterResumesIntermediaires(scene?.resume_intermediaire);

		// Construire le prompt
		let contenu = `## Scène à analyser\n\n`;
		contenu += `**Lieu:** ${lieu}\n\n`;

		if (resumesIntermediaires) {
			contenu += `**Résumés intermédiaires (déjà traités):**\n${resumesIntermediaires}\n\n`;
			contenu += `**Messages depuis le dernier résumé:**\n\n`;
		} else {
			contenu += `**Conversation:**\n\n`;
		}

		contenu += formaterMessagesForHaiku(messages);

		// Appel Haiku
		const response = await anthropic.messages.create({
			model: HAIKU_MODEL,
			max_tokens: 2048,
			system: PROMPT_HAIKU_SCENE,
			messages: [{ role: 'user', content: contenu }]
		});

		const content = response.content[0]?.text;
		const parsed = tryParseJSON(content);

		if (!parsed) {
			console.error('[Haiku] Impossible de parser la réponse');
			await marquerAnalysee(supabase, sceneId, 'Erreur analyse');
			return null;
		}

		// Construire le résumé final
		let resumeFinal = parsed.resume || '';
		if (resumesIntermediaires) {
			resumeFinal = `${resumesIntermediaires} ${resumeFinal}`;
		}

		// Sauvegarder le résumé
		await marquerAnalysee(supabase, sceneId, resumeFinal);

		// Enrichir les PNJ
		if (parsed.pnj_enrichis?.length > 0) {
			await enrichirPNJ(supabase, partieId, parsed.pnj_enrichis);
		}

		// Enrichir les lieux
		if (parsed.lieux_enrichis?.length > 0) {
			await enrichirLieux(supabase, partieId, parsed.lieux_enrichis);
		}

		// Sauvegarder les faits
		if (parsed.faits?.length > 0) {
			await sauvegarderFaits(supabase, partieId, parsed.faits, cycleActuel);
		}

		console.log(`[Haiku] Scène analysée: "${resumeFinal.slice(0, 60)}..."`);
		return parsed;

	} catch (err) {
		console.error('[Haiku] Erreur analyse scène:', err);
		return null;
	}
}

// ============================================================================
// ANALYSE INTERMÉDIAIRE (tous les 30 messages)
// ============================================================================

export async function analyserSceneIntermediaire(supabase, partieId, sceneId, lieu, cycleActuel) {
	console.log(`[Haiku] Analyse intermédiaire: ${lieu}`);

	try {
		// Récupérer la scène pour le dernier message résumé
		const { data: scene } = await supabase
			.from('scenes')
			.select('dernier_message_resume_id, resume_intermediaire')
			.eq('id', sceneId)
			.single();

		// Messages depuis le dernier résumé (ou tous si premier résumé)
		const messages = await getMessagesScene(supabase, sceneId, scene?.dernier_message_resume_id);

		if (messages.length === 0) {
			console.log('[Haiku] Aucun nouveau message pour résumé intermédiaire');
			return null;
		}

		// Contexte des résumés précédents
		const resumesPrecedents = formaterResumesIntermediaires(scene?.resume_intermediaire);

		let contenu = `## Analyse intermédiaire de scène\n\n`;
		contenu += `**Lieu:** ${lieu}\n\n`;

		if (resumesPrecedents) {
			contenu += `**Ce qui s'est passé avant dans cette scène:**\n${resumesPrecedents}\n\n`;
		}

		contenu += `**Nouveaux échanges à résumer:**\n\n`;
		contenu += formaterMessagesForHaiku(messages);

		// Appel Haiku
		const response = await anthropic.messages.create({
			model: HAIKU_MODEL,
			max_tokens: 1024,
			system: PROMPT_HAIKU_SCENE,
			messages: [{ role: 'user', content: contenu }]
		});

		const content = response.content[0]?.text;
		const parsed = tryParseJSON(content);

		if (!parsed?.resume) {
			console.error('[Haiku] Pas de résumé dans la réponse intermédiaire');
			return null;
		}

		// Récupérer l'ID du dernier message
		const dernierMessage = await getDernierMessageScene(supabase, sceneId);

		// Ajouter le résumé intermédiaire
		await ajouterResumeIntermediaire(supabase, sceneId, parsed.resume, dernierMessage?.id);

		// Enrichissements
		if (parsed.pnj_enrichis?.length > 0) {
			await enrichirPNJ(supabase, partieId, parsed.pnj_enrichis);
		}
		if (parsed.lieux_enrichis?.length > 0) {
			await enrichirLieux(supabase, partieId, parsed.lieux_enrichis);
		}
		if (parsed.faits?.length > 0) {
			await sauvegarderFaits(supabase, partieId, parsed.faits, cycleActuel);
		}

		console.log(`[Haiku] Résumé intermédiaire: "${parsed.resume.slice(0, 60)}..."`);
		return parsed;

	} catch (err) {
		console.error('[Haiku] Erreur analyse intermédiaire:', err);
		return null;
	}
}

// ============================================================================
// FIN DE CYCLE (nouveau_cycle: true)
// ============================================================================

export async function traiterFinDeCycle(supabase, partieId, cycleActuel, gameState) {
	console.log(`[Haiku] Traitement fin de cycle ${cycleActuel}`);

	try {
		// Récupérer les scènes du cycle
		const scenes = await getScenesCompleteCycle(supabase, partieId, cycleActuel);

		// Construire les résumés des scènes
		const resumesScenes = scenes.map(s => {
			let r = `[${s.lieu}`;
			if (s.heure_debut) r += ` ${s.heure_debut}`;
			if (s.heure_fin) r += `-${s.heure_fin}`;
			r += `] `;

			// Combiner résumé final + intermédiaires
			const intermediaires = formaterResumesIntermediaires(s.resume_intermediaire);
			r += intermediaires ? `${intermediaires} ${s.resume || ''}` : (s.resume || 'Pas de résumé');

			return r;
		}).filter(Boolean);

		// Récupérer les PNJ actifs
		const { data: pnjActifs } = await supabase
			.from('pnj')
			.select('nom, relation, disposition, stat_social, stat_travail, stat_sante, dernier_contact')
			.eq('partie_id', partieId)
			.or(`dernier_contact.gte.${cycleActuel - 3},relation.gt.0`);

		// Récupérer les arcs en cours
		const { data: arcs } = await supabase
			.from('arcs')
			.select('nom, type, progression')
			.eq('partie_id', partieId)
			.eq('etat', 'actif');

		// État de Valentin
		const valentin = gameState?.valentin || {};

		// Construire le prompt
		let contenu = `## Fin de cycle ${cycleActuel}\n\n`;

		contenu += `### Journée: ${gameState?.partie?.jour || ''} ${gameState?.partie?.date_jeu || ''}\n\n`;

		contenu += `### État de Valentin en fin de journée\n`;
		contenu += `- Énergie: ${valentin.energie || 3}/5\n`;
		contenu += `- Moral: ${valentin.moral || 3}/5\n`;
		contenu += `- Santé: ${valentin.sante || 5}/5\n\n`;

		contenu += `### Scènes de la journée\n`;
		if (resumesScenes.length > 0) {
			resumesScenes.forEach((r, i) => {
				contenu += `${i + 1}. ${r}\n`;
			});
		} else {
			contenu += `Aucune scène enregistrée.\n`;
		}
		contenu += '\n';

		contenu += `### PNJ actifs\n`;
		if (pnjActifs?.length > 0) {
			pnjActifs.forEach(p => {
				contenu += `- ${p.nom} (rel: ${p.relation}, ${p.disposition}) — Social: ${p.stat_social}/5, Travail: ${p.stat_travail}/5, Santé: ${p.stat_sante}/5\n`;
			});
		} else {
			contenu += `Aucun PNJ actif.\n`;
		}
		contenu += '\n';

		contenu += `### Arcs en cours\n`;
		if (arcs?.length > 0) {
			arcs.forEach(a => {
				contenu += `- ${a.nom} (${a.type}) — ${a.progression}%\n`;
			});
		} else {
			contenu += `Aucun arc actif.\n`;
		}

		// Appel Haiku
		const response = await anthropic.messages.create({
			model: HAIKU_MODEL,
			max_tokens: 2048,
			system: PROMPT_HAIKU_NEWCYCLE,
			messages: [{ role: 'user', content: contenu }]
		});

		const content = response.content[0]?.text;
		const parsed = tryParseJSON(content);

		if (!parsed) {
			console.error('[Haiku] Impossible de parser la réponse newcycle');
			return null;
		}

		// Sauvegarder le résumé du cycle
		if (parsed.resume_cycle) {
			await supabase.from('cycle_resumes').insert({
				partie_id: partieId,
				cycle: cycleActuel,
				jour: gameState?.partie?.jour,
				date_jeu: gameState?.partie?.date_jeu,
				resume: parsed.resume_cycle.resume,
				evenements_cles: parsed.resume_cycle.evenements_cles || []
			});
			console.log(`[Haiku] Résumé cycle sauvegardé`);
		}

		// Mettre à jour les évolutions PNJ
		if (parsed.evolutions_pnj?.length > 0) {
			await appliquerEvolutionsPNJ(supabase, partieId, parsed.evolutions_pnj, cycleActuel);
		}

		// Sauvegarder les événements à venir
		if (parsed.evenements_a_venir?.length > 0) {
			await sauvegarderEvenementsAVenir(supabase, partieId, parsed.evenements_a_venir);
		}

		console.log(`[Haiku] Fin de cycle traitée`);

		// Retourner les infos pour le réveil
		return {
			nuit: parsed.nuit || { qualite: 'bonne', reveil_energie: 4, reveil_moral: 3, reveil_sante: 5 },
			evolutions_pnj: parsed.evolutions_pnj || [],
			evenements_a_venir: parsed.evenements_a_venir || []
		};

	} catch (err) {
		console.error('[Haiku] Erreur traitement fin de cycle:', err);
		return null;
	}
}

// ============================================================================
// ENRICHISSEMENT PNJ
// ============================================================================

async function enrichirPNJ(supabase, partieId, pnjList) {
	for (const pnj of pnjList) {
		if (!pnj.nom) continue;

		// Trouver le PNJ existant
		const { data: existing } = await supabase
			.from('pnj')
			.select('id, traits, physique')
			.eq('partie_id', partieId)
			.ilike('nom', pnj.nom)
			.maybeSingle();

		if (!existing) {
			console.log(`[Haiku] PNJ non trouvé pour enrichissement: ${pnj.nom}`);
			continue;
		}

		const update = { updated_at: new Date().toISOString() };

		// Enrichir les champs non vides
		if (pnj.age) update.age = pnj.age;
		if (pnj.metier) update.metier = pnj.metier;
		if (pnj.domicile) update.domicile = pnj.domicile;
		if (pnj.arc) update.arc = pnj.arc;

		// Compléter le physique si plus détaillé
		if (pnj.physique && (!existing.physique || pnj.physique.length > existing.physique.length)) {
			update.physique = pnj.physique;
		}

		// Fusionner les traits
		if (pnj.traits?.length > 0) {
			const existingTraits = existing.traits || [];
			const nouveauxTraits = pnj.traits.filter(t =>
				!existingTraits.some(et => et.toLowerCase() === t.toLowerCase())
			);
			if (nouveauxTraits.length > 0) {
				update.traits = [...existingTraits, ...nouveauxTraits];
			}
		}

		// Appliquer si des changements
		if (Object.keys(update).length > 1) { // Plus que juste updated_at
			await supabase.from('pnj').update(update).eq('id', existing.id);
			console.log(`[Haiku] PNJ enrichi: ${pnj.nom}`);
		}
	}
}

// ============================================================================
// ENRICHISSEMENT LIEUX
// ============================================================================

async function enrichirLieux(supabase, partieId, lieuxList) {
	for (const lieu of lieuxList) {
		if (!lieu.nom) continue;

		// Trouver le lieu existant
		const { data: existing } = await supabase
			.from('lieux')
			.select('id, description, pnj_frequents')
			.eq('partie_id', partieId)
			.ilike('nom', lieu.nom)
			.maybeSingle();

		if (!existing) {
			console.log(`[Haiku] Lieu non trouvé pour enrichissement: ${lieu.nom}`);
			continue;
		}

		const update = { updated_at: new Date().toISOString() };

		// Enrichir les champs
		if (lieu.type) update.type = lieu.type;
		if (lieu.secteur) update.secteur = lieu.secteur;
		if (lieu.horaires) update.horaires = lieu.horaires;

		// Description: remplacer si plus détaillée ou si vide
		if (lieu.description && (!existing.description || lieu.description.length > existing.description.length)) {
			update.description = lieu.description;
		}

		// Fusionner pnj_frequents
		if (lieu.pnj_frequents?.length > 0) {
			const existants = existing.pnj_frequents || [];
			const nouveaux = lieu.pnj_frequents.filter(p =>
				!existants.some(e => e.toLowerCase() === p.toLowerCase())
			);
			if (nouveaux.length > 0) {
				update.pnj_frequents = [...existants, ...nouveaux];
			}
		}

		// Appliquer si des changements
		if (Object.keys(update).length > 1) {
			await supabase.from('lieux').update(update).eq('id', existing.id);
			console.log(`[Haiku] Lieu enrichi: ${lieu.nom}`);
		}
	}
}

// ============================================================================
// ÉVOLUTIONS PNJ (fin de cycle)
// ============================================================================

async function appliquerEvolutionsPNJ(supabase, partieId, evolutions, cycleActuel) {
	for (const ev of evolutions) {
		if (!ev.nom) continue;

		const { data: pnj } = await supabase
			.from('pnj')
			.select('id')
			.eq('partie_id', partieId)
			.ilike('nom', ev.nom)
			.maybeSingle();

		if (!pnj) continue;

		const update = { updated_at: new Date().toISOString() };

		if (ev.disposition) update.disposition = ev.disposition;
		if (ev.stat_social !== undefined) update.stat_social = ev.stat_social;
		if (ev.stat_travail !== undefined) update.stat_travail = ev.stat_travail;
		if (ev.stat_sante !== undefined) update.stat_sante = ev.stat_sante;

		await supabase.from('pnj').update(update).eq('id', pnj.id);

		// Sauvegarder l'événement hors-champ comme fait (si présent)
		if (ev.evenement_horschamp) {
			await sauvegarderFaits(supabase, partieId, [{
				sujet_nom: ev.nom,
				sujet_type: 'pnj',
				categorie: 'evenement',
				fait: ev.evenement_horschamp,
				importance: 3,
				valentin_sait: false
			}], cycleActuel);
		}
	}

	console.log(`[Haiku] ${evolutions.length} évolutions PNJ appliquées`);
}

// ============================================================================
// ÉVÉNEMENTS À VENIR
// ============================================================================

async function sauvegarderEvenementsAVenir(supabase, partieId, evenements) {
	const toInsert = evenements
		.filter(ev => ev.evenement && ev.cycle_prevu)
		.map(ev => ({
			partie_id: partieId,
			cycle_prevu: ev.cycle_prevu,
			evenement: ev.evenement,
			type: ev.type || 'autre',
			pnj_impliques: ev.pnj_impliques || [],
			lieu: ev.lieu || null,
			realise: false
		}));

	if (toInsert.length > 0) {
		await supabase.from('a_venir').insert(toInsert);
		console.log(`[Haiku] ${toInsert.length} événements à venir enregistrés`);
	}
}

// ============================================================================
// EXPORTS
// ============================================================================

export { HAIKU_MODEL };
