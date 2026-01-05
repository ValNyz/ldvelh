import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import { SYSTEM_PROMPT_INIT, SYSTEM_PROMPT_LIGHT } from '../../../lib/prompt';
import { buildContext } from '../../../lib/contextBuilder';
import { sauvegarderFaits } from '../../../lib/faitsService';
import { insererTransactions, calculerSolde, calculerInventaire } from '../../../lib/financeService';
import {
	getSceneEnCours,
	creerScene,
	fermerScene,
	ajouterPnjImpliques,
	doitAnalyserIntermediaire
} from '../../../lib/sceneService';
import {
	analyserScene,
	analyserSceneIntermediaire,
	traiterFinDeCycle
} from '../../../lib/haikuService';

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
	const { data } = await supabase.from('chat_messages')
		.select('role, content, cycle, scene_id, created_at')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: true });
	return data || [];
}

// ============================================================================
// GESTION DES SCÈNES
// ============================================================================

async function gererChangementScene(supabase, partieId, cycle, ancienLieu, nouveauLieu, heure, pnjsPresents) {
	// Récupérer la scène en cours
	const sceneEnCours = await getSceneEnCours(supabase, partieId);

	// Si on a une scène en cours et que le lieu change
	if (sceneEnCours && ancienLieu && nouveauLieu && ancienLieu.toLowerCase() !== nouveauLieu.toLowerCase()) {
		console.log(`[SCENE] Changement de lieu: ${ancienLieu} → ${nouveauLieu}`);

		// Fermer l'ancienne scène
		await fermerScene(supabase, sceneEnCours.id, heure, pnjsPresents);

		// Lancer l'analyse Haiku en background (ne pas attendre)
		analyserScene(supabase, partieId, sceneEnCours.id, ancienLieu, cycle)
			.catch(err => console.error('[SCENE] Erreur analyse:', err));

		// Créer la nouvelle scène
		const nouvelleScene = await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
		return nouvelleScene;
	}

	// Si pas de scène en cours, en créer une
	if (!sceneEnCours && nouveauLieu) {
		console.log(`[SCENE] Création première scène: ${nouveauLieu}`);
		const nouvelleScene = await creerScene(supabase, partieId, cycle, nouveauLieu, heure);
		return nouvelleScene;
	}

	return sceneEnCours;
}

async function verifierAnalyseIntermediaire(supabase, partieId, sceneId, lieu, cycle) {
	const doitAnalyser = await doitAnalyserIntermediaire(supabase, sceneId);

	if (doitAnalyser) {
		console.log(`[SCENE] Déclenchement analyse intermédiaire`);
		// Lancer en background
		analyserSceneIntermediaire(supabase, partieId, sceneId, lieu, cycle)
			.catch(err => console.error('[SCENE] Erreur analyse intermédiaire:', err));
	}
}

// ============================================================================
// TRAITEMENT DES ENTITÉS (PNJ/LIEUX)
// ============================================================================

async function processEntites(supabase, partieId, entites, cycle) {
	const results = {
		pnj_crees: [],
		pnj_modifies: [],
		lieux_crees: [],
		lieux_modifies: [],
		errors: []
	};

	if (!entites || entites.length === 0) return results;

	for (const entite of entites) {
		try {
			if (entite.type === 'pnj') {
				if (entite.action === 'creer') {
					const { data: existing } = await supabase
						.from('pnj').select('id').eq('partie_id', partieId)
						.ilike('nom', entite.nom).maybeSingle();

					if (!existing) {
						const { data: inserted } = await supabase.from('pnj').insert({
							partie_id: partieId,
							nom: entite.nom,
							metier: entite.metier || null,
							physique: entite.physique || null,
							traits: entite.traits || [],
							arc: entite.arc || null,
							domicile: entite.domicile || null,
							espece: entite.espece || 'humain',
							relation: 0,
							disposition: 'neutre',
							stat_social: 3,
							stat_travail: 3,
							stat_sante: 3,
							dernier_contact: cycle
						}).select().single();

						if (inserted) results.pnj_crees.push(inserted);
					}
				} else if (entite.action === 'modifier') {
					const { data: pnj } = await supabase
						.from('pnj').select('*').eq('partie_id', partieId)
						.ilike('nom', entite.nom).maybeSingle();

					if (pnj) {
						const updateData = { updated_at: new Date().toISOString() };
						if (entite.nouveau_nom) updateData.nom = entite.nouveau_nom;
						if (entite.metier) updateData.metier = entite.metier;
						if (entite.physique) updateData.physique = entite.physique;
						if (entite.domicile) updateData.domicile = entite.domicile;
						if (entite.arc) updateData.arc = entite.arc;
						if (entite.traits?.length > 0) {
							const existingTraits = pnj.traits || [];
							const newTraits = entite.traits.filter(t => !existingTraits.includes(t));
							updateData.traits = [...existingTraits, ...newTraits];
						}

						const { data: updated } = await supabase.from('pnj')
							.update(updateData).eq('id', pnj.id).select().single();

						if (updated) results.pnj_modifies.push({ ancien_nom: pnj.nom, ...updated });
					} else {
						results.errors.push(`PNJ non trouvé: ${entite.nom}`);
					}
				}
			} else if (entite.type === 'lieu') {
				if (entite.action === 'creer') {
					const { data: existing } = await supabase
						.from('lieux').select('id').eq('partie_id', partieId)
						.ilike('nom', entite.nom).maybeSingle();

					if (!existing) {
						const { data: inserted } = await supabase.from('lieux').insert({
							partie_id: partieId,
							nom: entite.nom,
							type: entite.type_lieu || 'autre',
							secteur: entite.secteur || null,
							description: entite.description || null,
							pnjs_frequents: entite.pnjs_frequents || [],
							horaires: entite.horaires || null,
							cycles_visites: [cycle]
						}).select().single();

						if (inserted) results.lieux_crees.push(inserted);
					}
				} else if (entite.action === 'modifier') {
					const { data: lieu } = await supabase
						.from('lieux').select('*').eq('partie_id', partieId)
						.ilike('nom', entite.nom).maybeSingle();

					if (lieu) {
						const updateData = { updated_at: new Date().toISOString() };
						if (entite.description) {
							updateData.description = lieu.description
								? `${lieu.description} ${entite.description}`
								: entite.description;
						}
						if (entite.horaires) updateData.horaires = entite.horaires;
						if (entite.pnjs_frequents?.length > 0) {
							const existing = lieu.pnjs_frequents || [];
							const newPnj = entite.pnjs_frequents.filter(p => !existing.includes(p));
							updateData.pnjs_frequents = [...existing, ...newPnj];
						}

						const { data: updated } = await supabase.from('lieux')
							.update(updateData).eq('id', lieu.id).select().single();

						if (updated) results.lieux_modifies.push(updated);
					}
				}
			}
		} catch (err) {
			results.errors.push(`Erreur entité ${entite.type}/${entite.nom}: ${err.message}`);
		}
	}

	return results;
}

// ============================================================================
// MISE À JOUR PNJ PRÉSENTS
// ============================================================================

async function updatePnjsPresents(supabase, partieId, pnjsPresents, cycle, pnjList) {
	if (!pnjsPresents?.length) return;

	for (const nomPnj of pnjsPresents) {
		const pnj = pnjList.find(p =>
			p.nom.toLowerCase() === nomPnj.toLowerCase() ||
			p.nom.split(' ')[0].toLowerCase() === nomPnj.toLowerCase()
		);

		if (pnj?.id) {
			const cyclesVus = Array.isArray(pnj.cycles_vus) ? [...pnj.cycles_vus] : [];
			if (!cyclesVus.includes(cycle)) cyclesVus.push(cycle);

			await supabase.from('pnj').update({
				dernier_contact: cycle,
				cycles_vus: cyclesVus,
				updated_at: new Date().toISOString()
			}).eq('id', pnj.id);
		}
	}
}

// ============================================================================
// TRAITEMENT MODE INIT
// ============================================================================

async function processInitMode(supabase, partieId, parsed, heure) {
	console.log('[INIT] Début processInitMode');
	console.log('[INIT] Données reçues:', {
		lieu_actuel: parsed.lieu_actuel,
		pnj_initiaux: parsed.pnj_initiaux?.length || 0,
		lieux_initiaux: parsed.lieux_initiaux?.length || 0,
		arcs_potentiels: parsed.arcs_potentiels?.length || 0
	});

	// 1. Mise à jour partie
	const { error: partieError } = await supabase.from('parties').update({
		cycle_actuel: parsed.cycle || 1,
		jour: parsed.jour || 'Lundi',
		date_jeu: parsed.date_jeu,
		heure: heure,
		lieu_actuel: parsed.lieu_actuel || null,
		pnjs_presents: parsed.pnjs_presents || []
	}).eq('id', partieId);

	if (partieError) console.error('[INIT] Erreur update partie:', partieError);

	// 2. Mise à jour Valentin
	if (parsed.valentin) {
		const valentinUpdate = {};
		if (parsed.valentin.raison_depart) valentinUpdate.raison_depart = parsed.valentin.raison_depart;
		if (parsed.valentin.poste) valentinUpdate.poste = parsed.valentin.poste;
		if (parsed.valentin.hobbies?.length > 0) {
			valentinUpdate.hobbies = parsed.valentin.hobbies;
		}
		if (Object.keys(valentinUpdate).length > 0) {
			const { error } = await supabase.from('valentin').update(valentinUpdate).eq('partie_id', partieId);
			if (error) console.error('[INIT] Erreur update valentin:', error);
			else console.log('[INIT] Valentin mis à jour');
		}
	}

	// 3. Mise à jour IA
	if (parsed.ia?.nom) {
		const { error } = await supabase.from('ia_personnelle').update({ nom: parsed.ia.nom }).eq('partie_id', partieId);
		if (error) console.error('[INIT] Erreur update IA:', error);
		else console.log('[INIT] IA mise à jour:', parsed.ia.nom);
	}

	// 4. Lieux initiaux - AVANT les PNJ pour que pnjs_frequents soit valide
	if (parsed.lieux_initiaux?.length > 0) {
		console.log('[INIT] Insertion de', parsed.lieux_initiaux.length, 'lieux');

		for (const lieu of parsed.lieux_initiaux) {
			const { error } = await supabase.from('lieux').insert({
				partie_id: partieId,
				nom: lieu.nom,
				type: lieu.type || 'autre',
				secteur: lieu.secteur || null,
				description: lieu.description || null,
				horaires: lieu.horaires || null,
				pnjs_frequents: lieu.pnjs_frequents || [],
				cycles_visites: [1]
			});

			if (error) {
				console.error('[INIT] Erreur insertion lieu:', lieu.nom, error);
			} else {
				console.log('[INIT] Lieu créé:', lieu.nom);
			}
		}
	} else {
		console.warn('[INIT] Aucun lieu initial à créer!');
	}

	// 5. PNJ initiaux
	if (parsed.pnj_initiaux?.length > 0) {
		console.log('[INIT] Traitement de', parsed.pnj_initiaux.length, 'PNJ');

		for (const pnj of parsed.pnj_initiaux) {
			const { data: existing } = await supabase
				.from('pnj').select('id').eq('partie_id', partieId)
				.ilike('nom', pnj.nom).maybeSingle();

			if (existing) {
				const { error } = await supabase.from('pnj').update({
					metier: pnj.metier,
					age: pnj.age,
					espece: pnj.espece,
					domicile: pnj.domicile,
					traits: pnj.traits || [],
					arc: Array.isArray(pnj.arc) ? pnj.arc.join(', ') : pnj.arc,
					updated_at: new Date().toISOString()
				}).eq('id', existing.id);

				if (error) console.error('[INIT] Erreur update PNJ:', pnj.nom, error);
				else console.log('[INIT] PNJ mis à jour:', pnj.nom);
			} else {
				const { error } = await supabase.from('pnj').insert({
					partie_id: partieId,
					nom: pnj.nom,
					age: pnj.age,
					espece: pnj.espece,
					physique: pnj.physique,
					metier: pnj.metier,
					domicile: pnj.domicile,
					traits: pnj.traits || [],
					arc: Array.isArray(pnj.arc) ? pnj.arc.join(', ') : pnj.arc,
					relation: 0,
					disposition: 'neutre',
					stat_social: 3,
					stat_travail: 3,
					stat_sante: 3,
				});

				if (error) console.error('[INIT] Erreur insertion PNJ:', pnj.nom, error);
				else console.log('[INIT] PNJ créé:', pnj.nom);
			}
		}
	}

	// 6. Arcs potentiels
	if (parsed.arcs_potentiels?.length > 0) {
		console.log('[INIT] Insertion de', parsed.arcs_potentiels.length, 'arcs');

		const arcsToInsert = parsed.arcs_potentiels.map(a => ({
			partie_id: partieId,
			nom: a.nom,
			type: a.type,
			description: a.description || null,
			obstacles: a.obstacles || [],
			pnjs_impliques: a.pnjs_impliques || [],
			progression: 0,
			etat: 'actif'
		}));

		const { error } = await supabase.from('arcs').insert(arcsToInsert);
		if (error) console.error('[INIT] Erreur insertion arcs:', error);
		else console.log('[INIT] Arcs créés');
	}

	// 7. Monde (stocker comme faits)
	if (parsed.monde) {
		console.log('[INIT] Sauvegarde monde:', parsed.monde.nom);

		const faitsMonde = [
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: parsed.monde.nom, categorie: 'etat', fait: `Type: ${parsed.monde.type}`, importance: 3, cycle_creation: 1, valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: parsed.monde.nom, categorie: 'etat', fait: `Position: ${parsed.monde.orbite}`, importance: 3, cycle_creation: 1, valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: parsed.monde.nom, categorie: 'etat', fait: `Population: ${parsed.monde.population}`, importance: 3, cycle_creation: 1, valentin_sait: true, certitude: 'certain' },
			{ partie_id: partieId, sujet_type: 'monde', sujet_nom: parsed.monde.nom, categorie: 'trait', fait: `Ambiance: ${parsed.monde.ambiance}`, importance: 4, cycle_creation: 1, valentin_sait: true, certitude: 'certain' }
		];

		const { error } = await supabase.from('faits').insert(faitsMonde);
		if (error) console.error('[INIT] Erreur insertion faits monde:', error);
	}

	// 8. Employeur
	if (parsed.employeur) {
		console.log('[INIT] Sauvegarde employeur:', parsed.employeur.nom);

		const { error } = await supabase.from('faits').insert({
			partie_id: partieId,
			sujet_type: 'monde',
			sujet_nom: parsed.employeur.nom,
			categorie: 'etat',
			fait: `Employeur de Valentin. Type: ${parsed.employeur.type}`,
			importance: 5,
			cycle_creation: 1,
			valentin_sait: true,
			certitude: 'certain'
		});
		if (error) console.error('[INIT] Erreur insertion employeur:', error);
	}

	// 9. Créer la première scène
	if (parsed.lieu_actuel) {
		console.log('[INIT] Création scène initiale:', parsed.lieu_actuel);
		await creerScene(supabase, partieId, 1, parsed.lieu_actuel, heure);
	}

	console.log('[INIT] processInitMode terminé');
}

// ============================================================================
// APPLICATION DES DELTAS (mode light)
// ============================================================================

async function applyDeltas(supabase, partieId, parsed, pnjList, cycle, heure, sceneEnCours) {
	const results = {
		valentin: null,
		relations: 0,
		transactions: 0,
		competence: null,
		entites: null,
		sceneChanged: false,
		nouvelleScene: null
	};

	const ancienLieu = sceneEnCours?.lieu;
	const nouveauLieu = parsed.lieu_actuel;

	// 1. Deltas Valentin
	if (parsed.deltas_valentin) {
		const { data: current } = await supabase
			.from('valentin').select('energie, moral, sante')
			.eq('partie_id', partieId).single();

		if (current) {
			const d = parsed.deltas_valentin;
			const newValues = {
				energie: Math.max(1, Math.min(5, (current.energie || 3) + (d.energie || 0))),
				moral: Math.max(1, Math.min(5, (current.moral || 3) + (d.moral || 0))),
				sante: Math.max(1, Math.min(5, (current.sante || 5) + (d.sante || 0))),
				updated_at: new Date().toISOString()
			};
			await supabase.from('valentin').update(newValues).eq('partie_id', partieId);
			results.valentin = newValues;
		}
	}

	// 2. Changements de relation
	if (parsed.changements_relation?.length > 0) {
		for (const change of parsed.changements_relation) {
			if (!change.pnj) continue;
			const pnj = pnjList.find(p =>
				p.nom?.toLowerCase() === change.pnj.toLowerCase() ||
				p.nom?.split(' ')[0].toLowerCase() === change.pnj.toLowerCase()
			);

			if (pnj?.id) {
				const currentRelation = pnj.relation || 0;
				const newRelation = Math.max(0, Math.min(10, currentRelation + (change.delta || 0)));
				const updateData = { relation: newRelation, updated_at: new Date().toISOString() };
				if (change.disposition) updateData.disposition = change.disposition;
				await supabase.from('pnj').update(updateData).eq('id', pnj.id);
				results.relations++;
			}
		}
	}

	// 3. Transactions
	if (parsed.transactions?.length > 0) {
		const txResult = await insererTransactions(supabase, partieId, cycle, heure, parsed.transactions);
		results.transactions = txResult.inserted;
	}

	// 4. Progression compétence
	if (parsed.progression_competence?.competence) {
		results.competence = parsed.progression_competence.competence;
	}

	// 5. Traiter les entités (nouveaux_pnj, nouveau_lieu)
	const entites = [];

	if (parsed.nouveaux_pnj?.length > 0) {
		for (const pnj of parsed.nouveaux_pnj) {
			entites.push({ type: 'pnj', action: 'creer', ...pnj });
		}
	}

	if (parsed.nouveau_lieu) {
		entites.push({
			type: 'lieu',
			action: 'creer',
			nom: parsed.nouveau_lieu.nom,
			type_lieu: parsed.nouveau_lieu.type
		});
	}

	if (entites.length > 0) {
		results.entites = await processEntites(supabase, partieId, entites, cycle);
	}

	// 6. Gestion du changement de scène
	if (nouveauLieu && ancienLieu && nouveauLieu.toLowerCase() !== ancienLieu.toLowerCase()) {
		results.sceneChanged = true;
		results.nouvelleScene = await gererChangementScene(
			supabase, partieId, cycle, ancienLieu, nouveauLieu, heure, parsed.pnjs_presents || []
		);
	}

	// 7. Mise à jour lieu actuel + pnjs_presents
	await supabase.from('parties').update({
		lieu_actuel: nouveauLieu || ancienLieu,
		pnjs_presents: parsed.pnjs_presents || [],
		heure: heure
	}).eq('id', partieId);

	// 8. Mise à jour dernier_contact des PNJ présents
	if (parsed.pnjs_presents?.length > 0) {
		await updatePnjsPresents(supabase, partieId, parsed.pnjs_presents, cycle, pnjList);

		// Ajouter les PNJ à la scène en cours
		const sceneActive = results.nouvelleScene || sceneEnCours;
		if (sceneActive?.id) {
			await ajouterPnjImpliques(supabase, sceneActive.id, parsed.pnjs_presents);
		}
	}

	// 9. Tracker la visite du lieu
	if (nouveauLieu && !parsed.nouveau_lieu) {
		const { data: lieu } = await supabase
			.from('lieux').select('id, cycles_visites')
			.eq('partie_id', partieId).ilike('nom', nouveauLieu).maybeSingle();

		if (lieu) {
			const cyclesVisites = lieu.cycles_visites || [];
			if (!cyclesVisites.includes(cycle)) {
				await supabase.from('lieux').update({
					cycles_visites: [...cyclesVisites, cycle]
				}).eq('id', lieu.id);
			}
		}
	}

	// 10. Nouveau cycle flag → incrémenter le cycle
	if (parsed.nouveau_cycle === true) {
		// Fermer la scène en cours avant le nouveau cycle
		const sceneActive = results.nouvelleScene || sceneEnCours;
		if (sceneActive?.id) {
			await fermerScene(supabase, sceneActive.id, heure, parsed.pnjs_presents || []);
			// Lancer l'analyse en background
			analyserScene(supabase, partieId, sceneActive.id, sceneActive.lieu, cycle)
				.catch(err => console.error('[SCENE] Erreur analyse fin cycle:', err));
		}

		// Incrémenter le cycle et mettre à jour jour/date si fournis
		const updateData = { cycle_actuel: cycle + 1 };
		if (parsed.nouveau_jour) {
			updateData.jour = parsed.nouveau_jour.jour;
			updateData.date_jeu = parsed.nouveau_jour.date_jeu;
		}
		await supabase.from('parties').update(updateData).eq('id', partieId);

		results.nouveauCycle = true;
	}

	return results;
}

// ============================================================================
// GESTION PARTIES
// ============================================================================

async function deleteGame(partieId) {
	await Promise.all([
		supabase.from('chat_messages').delete().eq('partie_id', partieId),
		supabase.from('cycle_resumes').delete().eq('partie_id', partieId),
		supabase.from('faits').delete().eq('partie_id', partieId),
		supabase.from('finances').delete().eq('partie_id', partieId),
		supabase.from('scenes').delete().eq('partie_id', partieId),
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
	const { data: partie, error } = await supabase.from('parties').insert({
		nom: 'Nouvelle partie',
		cycle_actuel: 1,
		active: true,
		options: { faits_enabled: true }
	}).select().single();

	if (error) throw error;

	await Promise.all([
		supabase.from('valentin').insert({ partie_id: partie.id }),
		supabase.from('ia_personnelle').insert({ partie_id: partie.id }),
		supabase.from('pnj').insert({
			partie_id: partie.id,
			nom: 'Justine Lépicier',
			age: 32,
			espece: 'humain',
			physique: '1m54, 72kg, courbes prononcées, poitrine volumineuse, blonde en désordre, yeux bleus fatigués, cernes',
			relation: 0,
			disposition: 'neutre',
			stat_social: 4,
			stat_travail: 2,
			stat_sante: 2,
			etape_romantique: 0,
			est_initial: true,
			interet_romantique: true
		})
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
			.select('id, created_at, cycle').eq('partie_id', partieId)
			.order('created_at', { ascending: true });

		if (!allMessages || fromIndex >= allMessages.length) return Response.json({ success: true });

		const messagesToDelete = allMessages.slice(fromIndex);
		const firstDeletedAt = messagesToDelete[0]?.created_at;
		const remainingMessages = allMessages.slice(0, fromIndex);
		const lastRemainingCycle = remainingMessages.length > 0
			? remainingMessages[remainingMessages.length - 1].cycle : 1;

		if (messagesToDelete.length > 0 && firstDeletedAt) {
			await supabase.from('chat_messages').delete().in('id', messagesToDelete.map(m => m.id));
			await supabase.from('finances').delete().eq('partie_id', partieId).gte('created_at', firstDeletedAt);
			await supabase.from('faits').delete().eq('partie_id', partieId).gte('created_at', firstDeletedAt);

			// Supprimer les scènes créées après ce point
			await supabase.from('scenes').delete().eq('partie_id', partieId).gte('created_at', firstDeletedAt);

			const { data: partie } = await supabase.from('parties')
				.select('cycle_actuel').eq('id', partieId).single();

			let jourCible = null, dateCible = null;

			if (lastRemainingCycle < partie?.cycle_actuel) {
				const { data: resumeCycle } = await supabase.from('cycle_resumes')
					.select('jour, date_jeu').eq('partie_id', partieId)
					.eq('cycle', lastRemainingCycle).maybeSingle();

				if (resumeCycle) {
					jourCible = resumeCycle.jour;
					dateCible = resumeCycle.date_jeu;
				}
			}

			await supabase.from('cycle_resumes').delete()
				.eq('partie_id', partieId).gte('cycle', lastRemainingCycle + 1);

			if (partie && partie.cycle_actuel > lastRemainingCycle) {
				await supabase.from('parties').update({
					cycle_actuel: lastRemainingCycle,
					jour: jourCible,
					date_jeu: dateCible
				}).eq('id', partieId);
			}

			const nouveauSolde = await calculerSolde(supabase, partieId);
			await supabase.from('valentin').update({ credits: nouveauSolde }).eq('partie_id', partieId);
		}

		return Response.json({ success: true, deleted: messagesToDelete.length });
	} catch (e) {
		return Response.json({ error: e.message }, { status: 500 });
	}
}

// ============================================================================
// POST HANDLER
// ============================================================================

export async function POST(request) {
	try {
		const { message, partieId, gameState } = await request.json();
		const currentCycle = gameState?.partie?.cycle_actuel || gameState?.cycle || 1;

		// Déterminer le mode (INIT ou LIGHT)
		let promptMode = 'light';
		let faitsEnabled = true;
		let sceneEnCours = null;

		if (!gameState || !gameState.partie) {
			promptMode = 'init';
			console.log('[MODE] INIT - Lancement de partie');
		} else if (partieId) {
			const { data: partieData } = await supabase.from('parties')
				.select('options').eq('id', partieId).single();

			faitsEnabled = partieData?.options?.faits_enabled !== false;
			console.log('[MODE] LIGHT - Message normal');

			// Récupérer la scène en cours
			sceneEnCours = await getSceneEnCours(supabase, partieId);
		}

		// Construire le contexte
		let contextMessage, knownPnj = [];
		if (promptMode === 'init') {
			contextMessage = 'Nouvelle partie. Lance le jeu. Génère tout au lancement.';
		} else if (partieId && gameState?.partie) {
			try {
				const contextResult = await buildContext(supabase, partieId, gameState, message, { faitsEnabled });
				contextMessage = contextResult.context;
				knownPnj = contextResult.pnj || [];
				sceneEnCours = contextResult.sceneEnCours || sceneEnCours;
			} catch (err) {
				console.error('Erreur buildContext:', err);
				contextMessage = `=== ÉTAT ===\n${JSON.stringify(gameState, null, 1)}\n\n=== ACTION ===\n${message}`;
			}
		} else {
			contextMessage = message;
		}

		// Sélectionner le prompt (INIT ou LIGHT)
		let systemPrompt, maxTokens;
		if (promptMode === 'init') {
			systemPrompt = SYSTEM_PROMPT_INIT;
			maxTokens = 8192;
		} else {
			systemPrompt = SYSTEM_PROMPT_LIGHT;
			maxTokens = 4096;
		}

		const { readable, writable } = new TransformStream();
		const writer = writable.getWriter();
		const encoder = new TextEncoder();
		let pnjForTracking = knownPnj;

		(async () => {
			let fullContent = '', parsed = null, displayText = '', cycleForSave = currentCycle;

			try {
				console.log(`[STREAM] Context:`, JSON.stringify(contextMessage, null, 2));
				console.log(`[STREAM] Start streaming (${promptMode} mode)...`);
				const streamStart = Date.now();

				const streamResponse = await anthropic.messages.stream({
					model: 'claude-sonnet-4-20250514',
					temperature: 0.65,
					max_tokens: maxTokens,
					system: [{ type: 'text', text: systemPrompt, cache_control: { type: 'ephemeral' } }],
					messages: [{ role: 'user', content: contextMessage }]
				});

				for await (const event of streamResponse) {
					if (event.type === 'content_block_delta' && event.delta?.text) {
						fullContent += event.delta.text;
						await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: event.delta.text })}\n\n`));
					}
				}
				console.log(`[STREAM] Complete: ${Date.now() - streamStart}ms`);

				// Parser le JSON
				parsed = extractJSON(fullContent);
				console.log(`[STREAM] Parsed:`, JSON.stringify(parsed, null, 2));

				// Construire le texte d'affichage
				if (parsed) {
					displayText = '';
					const narratif = parsed.narratif || '';
					if (parsed.heure && !narratif.trim().startsWith(`[${parsed.heure}]`)) {
						displayText += `[${parsed.heure}] `;
					}
					displayText += narratif;
					if (parsed.choix?.length > 0) {
						displayText += '\n\n' + parsed.choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
					}
					if (parsed.nouveau_jour?.cycle) {
						cycleForSave = parsed.nouveau_jour.cycle;
					}
				} else {
					displayText = fullContent.replace(/```json[\s\S]*?```/g, '').replace(/\{[\s\S]*\}$/g, '').trim() || "Erreur de génération.";
				}

				// Récupérer/créer la scène pour associer les messages
				let sceneIdForMessages = sceneEnCours?.id;

				if (promptMode === 'light' && parsed?.lieu_actuel && !sceneIdForMessages) {
					// Créer une scène si elle n'existe pas
					const nouvelleScene = await creerScene(supabase, partieId, cycleForSave, parsed.lieu_actuel, parsed.heure);
					sceneIdForMessages = nouvelleScene?.id;
				}

				// Sauvegarder les messages
				if (partieId) {
					await supabase.from('chat_messages').insert({
						partie_id: partieId,
						scene_id: sceneIdForMessages,
						role: 'user',
						content: message,
						cycle: cycleForSave
					});
					await supabase.from('chat_messages').insert({
						partie_id: partieId,
						scene_id: sceneIdForMessages,
						role: 'assistant',
						content: displayText,
						cycle: cycleForSave
					});
				}

				// Charger PNJ si nécessaire
				if (partieId && pnjForTracking.length === 0) {
					const { data } = await supabase.from('pnj').select('*').eq('partie_id', partieId);
					pnjForTracking = data || [];
				}

				// Construire le state pour le client
				let stateForClient = null;

				if (promptMode === 'init' && parsed) {
					// En mode INIT, les données sont à la racine du JSON (pas dans parsed.init)
					stateForClient = {
						cycle: parsed.cycle || 1,
						jour: parsed.jour,
						date_jeu: parsed.date_jeu,
						lieu_actuel: parsed.lieu_actuel || null,
						pnjs_presents: parsed.pnjs_presents || [],
						valentin: {
							energie: 3, moral: 3, sante: 5, credits: 1400, inventaire: [],
							poste: parsed.valentin?.poste || null,
							raison_depart: parsed.valentin?.raison_depart || null,
							hobbies: parsed.valentin?.hobbies || ['Cuisine']
						},
						ia: parsed.ia?.nom ? { nom: parsed.ia.nom } : null,
						monde: parsed.monde || null,
						employeur: parsed.employeur || null
					};
				} else if (promptMode === 'light' && parsed && partieId) {
					const deltaResults = await applyDeltas(
						supabase, partieId, parsed, pnjForTracking, cycleForSave, parsed.heure, sceneEnCours
					);
					console.log(`[STREAM] Deltas applied:`, deltaResults);

					const [partieData, credits, inventaire] = await Promise.all([
						supabase.from('parties')
							.select('cycle_actuel, jour, date_jeu, lieu_actuel, pnjs_presents')
							.eq('id', partieId).single().then(r => r.data),
						calculerSolde(supabase, partieId),
						calculerInventaire(supabase, partieId)
					]);

					stateForClient = {
						cycle: partieData?.cycle_actuel || cycleForSave,
						jour: partieData?.jour,
						date_jeu: partieData?.date_jeu,
						lieu_actuel: parsed.lieu_actuel || partieData?.lieu_actuel,
						pnjs_presents: parsed.pnjs_presents || partieData?.pnjs_presents || [],
						valentin: { ...(deltaResults.valentin || {}), credits, inventaire },
						entites: deltaResults.entites,
						sceneChanged: deltaResults.sceneChanged
					};

					// Vérifier si analyse intermédiaire nécessaire
					const sceneActive = deltaResults.nouvelleScene || sceneEnCours;
					if (sceneActive?.id && !deltaResults.sceneChanged) {
						await verifierAnalyseIntermediaire(supabase, partieId, sceneActive.id, sceneActive.lieu, cycleForSave);
					}
				}

				// Envoyer le 'done'
				await writer.write(encoder.encode(`data: ${JSON.stringify({
					type: 'done',
					displayText,
					heure: parsed?.heure,
					mode: promptMode,
					state: stateForClient
				})}\n\n`));

				await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'saved' })}\n\n`));

			} catch (error) {
				console.error('Streaming error:', error);
				try {
					await writer.write(encoder.encode(`data: ${JSON.stringify({ type: 'error', error: error.message })}\n\n`));
				} catch (e) { }
			} finally {
				try { await writer.close(); } catch (e) { }
			}

			// === TÂCHES EN ARRIÈRE-PLAN ===
			console.log(`\n========== BACKGROUND TASKS (${promptMode}) ==========`);
			const bgStart = Date.now();

			if (partieId && parsed) {
				// MODE INIT
				if (promptMode === 'init') {
					const t0 = Date.now();
					await processInitMode(supabase, partieId, parsed, parsed.heure);
					console.log(`[BG] Process INIT: ${Date.now() - t0}ms`);
				}

				// Faits (si activé et présents dans la réponse)
				if (faitsEnabled && parsed.faits?.length > 0) {
					try {
						await sauvegarderFaits(supabase, partieId, parsed.faits, cycleForSave);
						console.log(`[BG] Faits sauvegardés: ${parsed.faits.length}`);
					} catch (err) {
						console.error('[BG] Erreur faits:', err);
					}
				}

				// Nouveau cycle détecté → lancer traitement Haiku en background
				if (parsed.nouveau_cycle === true) {
					console.log(`[BG] Nouveau cycle détecté, lancement traiterFinDeCycle`);
					traiterFinDeCycle(supabase, partieId, cycleForSave, gameState)
						.then(result => console.log(`[BG] traiterFinDeCycle terminé:`, result))
						.catch(err => console.error('[BG] Erreur traiterFinDeCycle:', err));
				}
			}

			console.log(`========== BACKGROUND END: ${Date.now() - bgStart}ms ==========\n`);
		})();

		return new Response(readable, {
			headers: {
				'Content-Type': 'text/event-stream',
				'Cache-Control': 'no-cache, no-transform',
				'Connection': 'keep-alive',
				'X-Accel-Buffering': 'no'
			}
		});
	} catch (e) {
		console.error('Erreur POST:', e);
		return Response.json({ error: e.message }, { status: 500 });
	}
}
