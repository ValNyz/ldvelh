/**
 * Extracteur KG pour LDVELH
 * Appelle Haiku pour extraire les opérations KG depuis le narratif
 */

import Anthropic from '@anthropic-ai/sdk';
import {
	getEntitesConnuesPourHaiku,
	getRelationsValentin
} from './kgService.js';
import { appliquerOperations, logExtraction } from './kgOperations.js';
import { marquerAnalysee } from '../scene/sceneService.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const HAIKU_MODEL = 'claude-haiku-4-5';
const MAX_RETRIES = 1;

// ============================================================================
// PROMPT HAIKU
// ============================================================================

const PROMPT_EXTRACTION = `# Extraction Knowledge Graph — LDVELH

Tu analyses un narratif de jeu de rôle SF pour en extraire les opérations sur le Knowledge Graph.

## FORMAT OBLIGATOIRE

Réponds UNIQUEMENT avec un JSON valide :
{
  "resume": "Résumé en 2-6 phrases",
  "operations": [...],
  "contradictions": [],
  "entites_ambigues": []
}

## OPÉRATIONS DISPONIBLES

- CREER_ENTITE: { op, type, nom, alias[], proprietes{}, confirme }
- MODIFIER_ENTITE: { op, entite, nouveau_nom?, alias_ajouter[], proprietes{} }
- SUPPRIMER_ENTITE: { op, entite, raison }
- CREER_RELATION: { op, source, cible, type, proprietes{}, certitude, verite, source_info }
- MODIFIER_RELATION: { op, source, cible, type, proprietes{}, raison }
- TERMINER_RELATION: { op, source, cible, type, raison }
- MODIFIER_ETAT: { op, entite, attribut, valeur, details{} }
- CREER_EVENEMENT: { op, titre, categorie, description?, lieu?, heure?, participants[], montant? }
- PLANIFIER_EVENEMENT: { op, titre, categorie, cycle_prevu, heure?, lieu?, participants[] }

## RÈGLES

- Utilise les noms EXACTS des entités connues
- 80% des échanges = pas de changement de relation
- Progression relation: échange poli = 0, complicité = +0.2, service = +0.5, maladresse = -0.25
- Ne pas extraire les descriptions d'ambiance sans impact`;

// ============================================================================
// CONSTRUCTION DU PROMPT
// ============================================================================

function buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle) {
	let prompt = `## NARRATIF\n\n${narratif}\n\n`;
	prompt += `## CYCLE ACTUEL: ${cycle}\n\n`;
	prompt += `## ENTITÉS CONNUES\n\n`;
	prompt += `Protagoniste: ${entitesConnues.protagoniste}\n\n`;

	if (entitesConnues.personnages?.length > 0) {
		prompt += `Personnages:\n`;
		for (const p of entitesConnues.personnages) {
			const aliases = p.alias?.length > 0 ? ` (alias: ${p.alias.join(', ')})` : '';
			prompt += `- ${p.nom}${aliases}\n`;
		}
		prompt += '\n';
	}

	if (entitesConnues.lieux?.length > 0) {
		prompt += `Lieux:\n`;
		for (const l of entitesConnues.lieux) {
			prompt += `- ${l.nom}\n`;
		}
		prompt += '\n';
	}

	if (relationsValentin?.length > 0) {
		prompt += `## RELATIONS VALENTIN\n\n`;
		for (const r of relationsValentin) {
			const niveau = r.proprietes?.niveau ?? '?';
			prompt += `- ${r.type_relation}: ${r.cible_nom} (niveau: ${niveau})\n`;
		}
	}

	return prompt;
}

// ============================================================================
// PARSING JSON
// ============================================================================

function tryParseJSON(str) {
	if (!str || typeof str !== 'string') return null;

	let cleaned = str.trim();
	if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
	if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
	if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
	cleaned = cleaned.trim();

	const firstBrace = cleaned.indexOf('{');
	if (firstBrace > 0) cleaned = cleaned.slice(firstBrace);
	if (firstBrace === -1) return null;

	try {
		return JSON.parse(cleaned);
	} catch (e) {
		return tryRepairJSON(cleaned);
	}
}

function tryRepairJSON(str) {
	try {
		let braceCount = 0;
		let lastValidIndex = -1;
		let inString = false;
		let escapeNext = false;

		for (let i = 0; i < str.length; i++) {
			const char = str[i];
			if (escapeNext) { escapeNext = false; continue; }
			if (char === '\\' && inString) { escapeNext = true; continue; }
			if (char === '"' && !escapeNext) { inString = !inString; continue; }
			if (!inString) {
				if (char === '{') braceCount++;
				if (char === '}') { braceCount--; if (braceCount === 0) lastValidIndex = i; }
			}
		}

		if (lastValidIndex > 0) {
			return JSON.parse(str.slice(0, lastValidIndex + 1));
		}

		let fixed = str;
		if (inString) fixed += '"';
		while (braceCount > 0) { fixed += '}'; braceCount--; }

		return JSON.parse(fixed);
	} catch (e) {
		return null;
	}
}

// ============================================================================
// VALIDATION
// ============================================================================

const TYPES_ENTITES = ['personnage', 'lieu', 'objet', 'organisation', 'arc_narratif'];
const TYPES_RELATIONS = [
	'connait', 'ami_de', 'famille_de', 'collegue_de', 'superieur_de',
	'habite', 'travaille_a', 'frequente', 'a_visite',
	'employe_de', 'membre_de', 'possede', 'implique_dans',
	'situe_dans', 'assiste'
];
const ATTRIBUTS_ETAT = [
	'energie', 'moral', 'sante', 'credits', 'humeur', 'localisation',
	'disposition', 'stat_social', 'stat_travail', 'stat_sante', 'etat', 'progression'
];

function validerOperation(op) {
	if (!op?.op) return { valide: false, raison: 'Opération sans type' };

	switch (op.op) {
		case 'CREER_ENTITE':
			if (!op.type || !TYPES_ENTITES.includes(op.type)) {
				return { valide: false, raison: `Type entité invalide: ${op.type}` };
			}
			if (!op.nom?.trim()) return { valide: false, raison: 'Nom manquant' };
			break;

		case 'MODIFIER_ENTITE':
		case 'SUPPRIMER_ENTITE':
			if (!op.entite) return { valide: false, raison: 'Entité cible manquante' };
			break;

		case 'CREER_RELATION':
		case 'MODIFIER_RELATION':
		case 'TERMINER_RELATION':
			if (!op.source || !op.cible) return { valide: false, raison: 'Source ou cible manquante' };
			if (!op.type || !TYPES_RELATIONS.includes(op.type)) {
				return { valide: false, raison: `Type relation invalide: ${op.type}` };
			}
			break;

		case 'MODIFIER_ETAT':
			if (!op.entite) return { valide: false, raison: 'Entité manquante' };
			if (!op.attribut || !ATTRIBUTS_ETAT.includes(op.attribut)) {
				return { valide: false, raison: `Attribut invalide: ${op.attribut}` };
			}
			if (op.valeur === undefined) return { valide: false, raison: 'Valeur manquante' };
			break;

		case 'CREER_EVENEMENT':
		case 'PLANIFIER_EVENEMENT':
			if (!op.titre) return { valide: false, raison: 'Titre manquant' };
			break;

		default:
			return { valide: false, raison: `Opération inconnue: ${op.op}` };
	}

	return { valide: true };
}

function filtrerOperationsValides(operations) {
	const valides = [];
	const invalides = [];

	for (const op of operations) {
		const result = validerOperation(op);
		if (result.valide) {
			valides.push(op);
		} else {
			invalides.push({ op, raison: result.raison });
		}
	}

	return { valides, invalides };
}

// ============================================================================
// APPEL HAIKU
// ============================================================================

async function appelHaiku(prompt, retryCount = 0) {
	try {
		const response = await anthropic.messages.create({
			model: HAIKU_MODEL,
			max_tokens: 4096,
			system: PROMPT_EXTRACTION,
			messages: [{ role: 'user', content: prompt }]
		});

		const content = response.content[0]?.text;
		const parsed = tryParseJSON(content);

		if (!parsed) {
			if (retryCount < MAX_RETRIES) {
				console.log('[KG Extractor] JSON invalide, retry...');
				return appelHaiku(prompt, retryCount + 1);
			}
			return { error: 'JSON invalide après retry', raw: content };
		}

		return parsed;

	} catch (err) {
		console.error('[KG Extractor] Erreur appel Haiku:', err);
		return { error: err.message };
	}
}

// ============================================================================
// FONCTION PRINCIPALE
// ============================================================================

/**
 * Extrait les opérations KG et les applique
 */
export async function extraireEtAppliquer(supabase, partieId, narratif, cycle, sceneId = null) {
	const startTime = Date.now();

	const metrics = {
		duree_ms: 0,
		nb_operations: 0,
		entites_creees: 0,
		relations_creees: 0,
		evenements_crees: 0,
		etats_modifies: 0,
		contradictions: [],
		entites_non_resolues: 0,
		erreurs: []
	};

	try {
		// Contexte pour Haiku
		const [entitesConnues, relationsValentin] = await Promise.all([
			getEntitesConnuesPourHaiku(supabase, partieId),
			getRelationsValentin(supabase, partieId)
		]);

		// Construire et appeler
		const prompt = buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle);
		const result = await appelHaiku(prompt);

		if (result.error) {
			metrics.erreurs.push(result.error);
			metrics.duree_ms = Date.now() - startTime;
			await logExtraction(supabase, partieId, cycle, sceneId, metrics);
			return { success: false, metrics };
		}

		// Valider les opérations
		const operations = result.operations || [];
		const { valides, invalides } = filtrerOperationsValides(operations);

		metrics.nb_operations = valides.length;
		for (const inv of invalides) {
			metrics.erreurs.push(`${inv.op?.op || '?'}: ${inv.raison}`);
		}

		if (result.contradictions?.length > 0) {
			metrics.contradictions = result.contradictions;
		}

		// Appliquer
		if (valides.length > 0) {
			const resultats = await appliquerOperations(supabase, partieId, valides, cycle);
			metrics.entites_creees = resultats.entites_creees + resultats.entites_modifiees;
			metrics.relations_creees = resultats.relations_creees + resultats.relations_modifiees;
			metrics.evenements_crees = resultats.evenements_crees;
			metrics.etats_modifies = resultats.etats_modifies;
			if (resultats.erreurs?.length > 0) {
				metrics.erreurs.push(...resultats.erreurs);
			}
		}

		metrics.duree_ms = Date.now() - startTime;
		await logExtraction(supabase, partieId, cycle, sceneId, metrics);

		console.log(`[KG Extractor] ${metrics.nb_operations} ops en ${metrics.duree_ms}ms`);

		return {
			success: true,
			metrics,
			resume: result.resume || null,
			contradictions: result.contradictions || [],
			entites_ambigues: result.entites_ambigues || []
		};

	} catch (err) {
		console.error('[KG Extractor] Erreur:', err);
		metrics.erreurs.push(err.message);
		metrics.duree_ms = Date.now() - startTime;
		await logExtraction(supabase, partieId, cycle, sceneId, metrics);
		return { success: false, metrics };
	}
}

// ============================================================================
// HEURISTIQUE D'EXTRACTION
// ============================================================================

/**
 * Détermine si une extraction est nécessaire
 */
export function doitExtraire(narratif, parsed) {
	// Toujours extraire si indicateurs explicites
	if (parsed?.nouveaux_pnj?.length > 0) return true;
	if (parsed?.nouveau_lieu) return true;
	if (parsed?.transactions?.length > 0) return true;
	if (parsed?.changements_relation?.length > 0) return true;
	if (parsed?.nouveau_cycle) return true;

	// Heuristiques sur le texte
	const texte = narratif.toLowerCase();

	// Dialogues
	const aDialogue = texte.includes('«') || texte.includes('»');

	// Mots-clés d'événements
	const motsEvenements = ['rencontre', 'découvre', 'apprend', 'achète', 'vend', 'promet', 'accepte', 'refuse'];
	const aEvenement = motsEvenements.some(mot => texte.includes(mot));

	return aDialogue || aEvenement;
}

// ============================================================================
// EXTRACTION FIN DE CYCLE
// ============================================================================

export async function extraireFinDeCycle(supabase, partieId, messagesComplets, cycle, sceneId = null) {
	const narratifComplet = messagesComplets
		.filter(m => m.role === 'assistant')
		.map(m => m.content)
		.join('\n\n---\n\n');

	if (!narratifComplet.trim()) {
		return { success: true, metrics: { nb_operations: 0 } };
	}

	return extraireEtAppliquer(supabase, partieId, narratifComplet, cycle, sceneId);
}
