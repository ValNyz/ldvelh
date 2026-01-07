/**
 * Orchestrateur d'extraction KG
 * Lance les 5 extracteurs en parallèle et applique les résultats
 */

import { extractResume } from './resumeExtractor.js';
import { extractStats } from './statsExtractor.js';
import { extractTransactions } from './transactionExtractor.js';
import { extractEntityRelation } from './entityRelationExtractor.js';
import { extractEvents } from './eventExtractor.js';

import {
	getProtagoniste,
	getIA,
	getStatsValentin,
	getInventaire,
	getRelationsValentin,
	getEntitesConnuesPourHaiku,
	getEvenementsAVenir,
	updateStatsValentin,
	creerTransaction
} from '../kgService.js';
import { appliquerOperations, logExtraction } from '../kgOperations.js';
import { validerOperations } from '../../schemas/kg.js';

/**
 * Lance tous les extracteurs en parallèle et applique les résultats
 * @param {object} supabase 
 * @param {string} partieId 
 * @param {string} narratif 
 * @param {number} cycle 
 * @param {object} partie - {jour, date_jeu, heure}
 * @param {Array} pnjsPresents
 * @param {string} sceneId
 * @returns {Promise<object>}
 */
export async function runExtractors(supabase, partieId, narratif, cycle, partie, pnjsPresents, sceneId) {
	const startTime = Date.now();
	const timings = {};

	const metrics = {
		duree_ms: 0,
		extracteurs: {},
		entites_creees: 0,
		relations_creees: 0,
		evenements_crees: 0,
		etats_modifies: 0,
		transactions_traitees: 0,
		erreurs: []
	};

	try {
		// === PHASE 1 : Charger le contexte (parallèle) ===
		const contextStart = Date.now();

		const [stats, inventaire, relationsValentin, ia, entitesConnues, rdvExistants] = await Promise.all([
			getStatsValentin(supabase, partieId).then(r => { timings.ctx_stats = Date.now() - contextStart; return r; }),
			getInventaire(supabase, partieId).then(r => { timings.ctx_inventaire = Date.now() - contextStart; return r; }),
			getRelationsValentin(supabase, partieId).then(r => { timings.ctx_relations = Date.now() - contextStart; return r; }),
			getIA(supabase, partieId).then(r => { timings.ctx_relations = Date.now() - contextStart; return r; }),
			getEntitesConnuesPourHaiku(supabase, partieId).then(r => { timings.ctx_entites = Date.now() - contextStart; return r; }),
			getEvenementsAVenir(supabase, partieId, cycle, { limit: 15, skipCache: true }).then(r => { timings.ctx_rdv = Date.now() - contextStart; return r; })
		]);

		timings.phase1_total = Date.now() - contextStart;
		console.log(`[Extractors] PHASE 1 - Contexte: ${timings.phase1_total}ms`,
			`(stats:${timings.ctx_stats} inv:${timings.ctx_inventaire} rel:${timings.ctx_relations} ent:${timings.ctx_entites} rdv:${timings.ctx_rdv})`);

		// === PHASE 2 : Lancer les extracteurs en parallèle ===
		const extractionStart = Date.now();

		const [
			resumeResult,
			statsResult,
			transactionsResult,
			entityRelationResult,
			eventsResult
		] = await Promise.all([
			extractResume(narratif).then(r => { timings.ext_resume = Date.now() - extractionStart; return r; }),
			extractStats(narratif, stats).then(r => { timings.ext_stats = Date.now() - extractionStart; return r; }),
			extractTransactions(narratif, stats.credits, inventaire).then(r => { timings.ext_transactions = Date.now() - extractionStart; return r; }),
			extractEntityRelation(narratif, ia, entitesConnues, relationsValentin, pnjsPresents).then(r => { timings.ext_entityRelation = Date.now() - extractionStart; return r; }),
			extractEvents(narratif, cycle, partie?.jour, partie?.date_jeu, rdvExistants).then(r => { timings.ext_events = Date.now() - extractionStart; return r; })
		]);

		timings.phase2_total = Date.now() - extractionStart;
		console.log(`[Extractors] PHASE 2 - Extraction: ${timings.phase2_total}ms`,
			`(resume:${timings.ext_resume} stats:${timings.ext_stats} tx:${timings.ext_transactions} entity:${timings.ext_entityRelation} events:${timings.ext_events})`);

		// Identifier le plus lent
		const extracteurPlusLent = Object.entries(timings)
			.filter(([k]) => k.startsWith('ext_'))
			.sort((a, b) => b[1] - a[1])[0];
		console.log(`[Extractors] Goulot phase 2: ${extracteurPlusLent[0]} (${extracteurPlusLent[1]}ms)`);

		// Collecter les métriques
		metrics.extracteurs = {
			resume: resumeResult.success,
			stats: statsResult.success,
			transactions: transactionsResult.success,
			entityRelation: entityRelationResult.success,
			events: eventsResult.success
		};

		// === PHASE 3 : Appliquer les résultats (séquentiel ordonné) ===
		const applyStart = Date.now();

		// 3.1 Entités et relations (d'abord car les autres peuvent les référencer)
		const apply1Start = Date.now();
		if (entityRelationResult.success) {
			const ops = [
				...(entityRelationResult.entites || []),
				...convertRelationOps(entityRelationResult.relations || [])
			];

			if (ops.length > 0) {
				// Valider les opérations avec Zod
				const { valides, invalides } = validerOperations(ops);

				// Logger les opérations invalides
				for (const inv of invalides) {
					console.warn(`[EntityRelation] Opération invalide:`, inv.op?.op, '→', inv.erreur);
					metrics.erreurs.push(`[EntityRelation] ${inv.op?.op || '?'}: ${inv.erreur}`);
				}

				if (valides.length > 0) {
					const result = await appliquerOperations(supabase, partieId, valides, cycle);
					metrics.entites_creees += result.entites_creees + result.entites_modifiees;
					metrics.relations_creees += result.relations_creees + result.relations_modifiees;
					if (result.erreurs?.length > 0) {
						metrics.erreurs.push(...result.erreurs.map(e => `[EntityRelation] ${e}`));
					}
				}
			}
		} else if (entityRelationResult.error) {
			metrics.erreurs.push(`[EntityRelation] ${entityRelationResult.error}`);
		}
		timings.apply_entityRelation = Date.now() - apply1Start;

		// 3.2 Stats Valentin
		const apply2Start = Date.now();
		if (statsResult.success && statsResult.deltas) {
			const { energie, moral, sante } = statsResult.deltas;
			if (energie !== 0 || moral !== 0 || sante !== 0) {
				await updateStatsValentin(supabase, partieId, cycle, statsResult.deltas);
				metrics.etats_modifies++;
			}
		} else if (statsResult.error) {
			metrics.erreurs.push(`[Stats] ${statsResult.error}`);
		}
		timings.apply_stats = Date.now() - apply2Start;

		// 3.3 Transactions
		const apply3Start = Date.now();
		if (transactionsResult.success && transactionsResult.transactions?.length > 0) {
			for (const tx of transactionsResult.transactions) {
				const result = await creerTransaction(supabase, partieId, cycle, tx);
				if (result.success) {
					metrics.transactions_traitees++;
				} else if (result.error && !result.doublon) {
					metrics.erreurs.push(`[Transaction] ${tx.type}: ${result.error}`);
				}
			}
		} else if (transactionsResult.error) {
			metrics.erreurs.push(`[Transactions] ${transactionsResult.error}`);
		}
		timings.apply_transactions = Date.now() - apply3Start;

		// 3.4 Événements
		const apply4Start = Date.now();
		if (eventsResult.success) {
			const eventOps = [
				...(eventsResult.evenements_passes || []),
				...(eventsResult.evenements_planifies || []),
				...(eventsResult.annulations || [])
			];

			if (eventOps.length > 0) {
				// Valider les opérations avec Zod
				const { valides, invalides } = validerOperations(eventOps);

				// Logger les opérations invalides
				for (const inv of invalides) {
					console.warn(`[Events] Opération invalide:`, inv.op?.op, '→', inv.erreur);
					metrics.erreurs.push(`[Events] ${inv.op?.op || '?'}: ${inv.erreur}`);
				}

				if (valides.length > 0) {
					const result = await appliquerOperations(supabase, partieId, valides, cycle);
					metrics.evenements_crees += result.evenements_crees;
					if (result.erreurs?.length > 0) {
						metrics.erreurs.push(...result.erreurs.map(e => `[Events] ${e}`));
					}
				}
			}
		} else if (eventsResult.error) {
			metrics.erreurs.push(`[Events] ${eventsResult.error}`);
		}
		timings.apply_events = Date.now() - apply4Start;

		// 3.5 Résumé (sauvegarde sur le dernier message assistant)
		const apply5Start = Date.now();
		let resume = null;
		if (resumeResult.success && resumeResult.resume) {
			resume = resumeResult.resume;

			// Sauvegarder sur le dernier message assistant du cycle
			const { data: lastMsg } = await supabase
				.from('chat_messages')
				.select('id')
				.eq('partie_id', partieId)
				.eq('role', 'assistant')
				.order('created_at', { ascending: false })
				.limit(1)
				.single();

			if (lastMsg) {
				await supabase
					.from('chat_messages')
					.update({ resume })
					.eq('id', lastMsg.id);
			}
		} else if (resumeResult.error) {
			metrics.erreurs.push(`[Resume] ${resumeResult.error}`);
		}
		timings.apply_resume = Date.now() - apply5Start;

		timings.phase3_total = Date.now() - applyStart;
		console.log(`[Extractors] PHASE 3 - Application: ${timings.phase3_total}ms`,
			`(entity:${timings.apply_entityRelation} stats:${timings.apply_stats} tx:${timings.apply_transactions} events:${timings.apply_events} resume:${timings.apply_resume})`);

		// === PHASE 4 : Finalisation ===
		metrics.duree_ms = Date.now() - startTime;

		await logExtraction(supabase, partieId, cycle, sceneId, {
			...metrics,
			nb_operations: metrics.entites_creees + metrics.relations_creees +
				metrics.evenements_crees + metrics.transactions_traitees
		});

		console.log(`[Extractors] Terminé en ${metrics.duree_ms}ms - ` +
			`E:${metrics.entites_creees} R:${metrics.relations_creees} ` +
			`Ev:${metrics.evenements_crees} Tx:${metrics.transactions_traitees}`);

		// Log récapitulatif des timings
		console.log(`[Extractors] RÉCAP TIMINGS:`, {
			phase1_contexte: timings.phase1_total,
			phase2_extraction: timings.phase2_total,
			phase3_application: timings.phase3_total,
			total: metrics.duree_ms
		});

		return {
			success: true,
			resume,
			metrics
		};

	} catch (err) {
		console.error('[Extractors] Erreur globale:', err);
		metrics.erreurs.push(err.message);
		metrics.duree_ms = Date.now() - startTime;

		await logExtraction(supabase, partieId, cycle, sceneId, metrics);

		return { success: false, metrics };
	}
}

/**
 * Convertit les ops MODIFIER_RELATION en format standard
 */
function convertRelationOps(relations) {
	return relations.map(rel => {
		if (rel.op === 'MODIFIER_RELATION') {
			// Convertir en MODIFIER_RELATION standard pour kgOperations
			return {
				op: 'MODIFIER_RELATION',
				source: 'Valentin',
				cible: rel.pnj,
				type: 'connait',
				proprietes: {
					...(rel.delta !== undefined && { niveau_delta: rel.delta }),
					...(rel.disposition && { disposition: rel.disposition })
				},
				_raison: rel.raison // Pour le log
			};
		}
		return rel;
	});
}

export { extractResume, extractStats, extractTransactions, extractEntityRelation, extractEvents };
