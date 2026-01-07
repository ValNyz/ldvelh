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
		const [stats, inventaire, relationsValentin, entitesConnues, rdvExistants] = await Promise.all([
			getStatsValentin(supabase, partieId),
			getInventaire(supabase, partieId),
			getRelationsValentin(supabase, partieId),
			getEntitesConnuesPourHaiku(supabase, partieId),
			getEvenementsAVenir(supabase, partieId, cycle, { limit: 15, skipCache: true })
		]);

		console.log(`[Extractors] Contexte chargé en ${Date.now() - startTime}ms`);

		// === PHASE 2 : Lancer les extracteurs en parallèle ===
		const extractionStart = Date.now();

		const [
			resumeResult,
			statsResult,
			transactionsResult,
			entityRelationResult,
			eventsResult
		] = await Promise.all([
			extractResume(narratif),
			extractStats(narratif, stats),
			extractTransactions(narratif, stats.credits, inventaire),
			extractEntityRelation(narratif, entitesConnues, relationsValentin, pnjsPresents),
			extractEvents(narratif, cycle, partie?.jour, partie?.date_jeu, rdvExistants)
		]);

		console.log(`[Extractors] Extraction parallèle en ${Date.now() - extractionStart}ms`);

		// Collecter les métriques
		metrics.extracteurs = {
			resume: resumeResult.success,
			stats: statsResult.success,
			transactions: transactionsResult.success,
			entityRelation: entityRelationResult.success,
			events: eventsResult.success
		};

		// === PHASE 3 : Appliquer les résultats (séquentiel ordonné) ===

		// 3.1 Entités et relations (d'abord car les autres peuvent les référencer)
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

		// 3.2 Stats Valentin
		if (statsResult.success && statsResult.deltas) {
			const { energie, moral, sante } = statsResult.deltas;
			if (energie !== 0 || moral !== 0 || sante !== 0) {
				await updateStatsValentin(supabase, partieId, cycle, statsResult.deltas);
				metrics.etats_modifies++;
			}
		} else if (statsResult.error) {
			metrics.erreurs.push(`[Stats] ${statsResult.error}`);
		}

		// 3.3 Transactions
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

		// 3.4 Événements
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

		// 3.5 Résumé (sauvegarde sur la scène)
		let resume = null;
		if (resumeResult.success && resumeResult.resume) {
			resume = resumeResult.resume;

			if (sceneId) {
				await supabase
					.from('scenes')
					.update({ resume })
					.eq('id', sceneId);
			}
		} else if (resumeResult.error) {
			metrics.erreurs.push(`[Resume] ${resumeResult.error}`);
		}

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
