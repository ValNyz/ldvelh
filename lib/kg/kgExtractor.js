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
import { validerOperations } from '../schemas/kg.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const HAIKU_MODEL = 'claude-haiku-4-5';
const MAX_RETRIES = 1;

// ============================================================================
// PROMPT HAIKU
// ============================================================================

const PROMPT_EXTRACTION = `# Extraction KG — LDVELH

Extrais les opérations KG depuis le narratif. JSON uniquement :
{ "resume": "2-6 phrases", "operations": [...] }

## OPÉRATIONS

### Entités (nouveaux PNJ/lieux/objets mentionnés)
- CREER_ENTITE: { op, type, nom, visible?: {}, background?: {} }
  Types: personnage, lieu, objet, organisation, arc_narratif
  • visible : OBJET avec les infos DANS le texte → { physique: "...", metier: "..." }
  • background : OBJET avec enrichissement MJ → { age: 28, secret: "...", motivations: "..." }
  • Si aucune propriété connue, omettre visible/background
  
  Exemple: { "op": "CREER_ENTITE", "type": "lieu", "nom": "Bar Eclipse", "visible": { "ambiance": "tamisée" } }

- MODIFIER_ENTITE: { op, entite, nouveau_nom?, alias_ajouter[], visible?, background? }
  → Découverte d'info (visible) ou enrichissement MJ (background)
- SUPPRIMER_ENTITE: { op, entite, raison }

### Relations (liens entre entités)
- CREER_RELATION: { op, source, cible, type, proprietes{} }
  Types: connait, ami_de, famille_de, collegue_de, superieur_de,
         habite, travaille_a, frequente, employe_de, possede, situe_dans
- TERMINER_RELATION: { op, source, cible, type, raison }

### États (propriétés variables des entités)
- MODIFIER_ETAT: { op, entite, attribut, valeur }
  Attributs PNJ: disposition, stat_social, stat_travail, stat_sante, humeur
  Attributs lieu: etat (ouvert/fermé/bondé)
  Attributs arc: progression (0-100), etat (actif/terminé)

### Événements
- CREER_EVENEMENT: { op, titre, categorie, lieu?, participants[] }
  → Ce qui VIENT de se passer

- PLANIFIER_EVENEMENT: { op, titre, categorie, cycle_prevu, heure?, lieu?, participants[], recurrence? }
  → RDV, promesses, deadlines pour le FUTUR

- REALISER_EVENEMENT: { op, titre }
- ANNULER_EVENEMENT: { op, titre, raison }

---

## PLANIFIER_EVENEMENT — RÈGLES

### Extraire si :
- Engagement temporel : "demain", "mardi", "à 14h", "la semaine prochaine"
- Formulation RDV : "on se voit", "on se retrouve", "rendez-vous", "je passe"
- Confirmation : "ça marche", "promis", "c'est noté", "je serai là"
- Deadline : "avant vendredi", "pour lundi", "date limite"
- Récurrent : "tous les lundis", "chaque mois"

### NE PAS extraire si :
- Vague : "un de ces jours", "à l'occasion", "on verra"
- Conditionnel : "on pourrait", "peut-être"
- Question sans réponse confirmée

### Calcul cycle_prevu (utiliser le mapping fourni) :
- "aujourd'hui/ce soir" → cycle actuel
- "demain" → cycle + 1
- Jour nommé → consulter mapping

### Exemples

« On se retrouve demain, 14h ? » — « Ça marche. »
→ { "op": "PLANIFIER_EVENEMENT", "titre": "RDV avec Justine", "cycle_prevu": 6, "heure": "14h00", "lieu": "Bar Eclipse", "participants": ["Justine Lépicier"] }

« Réunion tous les lundis à 9h. »
→ { "op": "PLANIFIER_EVENEMENT", "titre": "Réunion hebdo", "categorie": "travail", "cycle_prevu": 10, "heure": "09h00", "recurrence": {"frequence": "hebdo"} }

« On devrait se faire un resto un de ces quatre. »
→ NE PAS extraire (trop vague)

---

## RÈGLES GÉNÉRALES
- Noms EXACTS des entités connues
- En cas de doute sur un RDV → EXTRAIRE
- Ignorer les descriptions d'ambiance sans impact`;

// ============================================================================
// CONSTRUCTION DU PROMPT
// ============================================================================

function buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle, jour, date_jeu, evenementsAVenir, connaissancesExistantes) {
	let prompt = `## NARRATIF\n\n${narratif}\n\n`;

	// === CONTEXTE TEMPOREL ===
	prompt += `## TEMPS\n`;
	prompt += `Cycle: ${cycle} `;
	if (jour) prompt += `| ${jour} `;
	if (date_jeu) prompt += `| ${date_jeu}`;
	prompt += `\n`;

	const jours = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
	const jourActuelIndex = jour ? jours.findIndex(j => jour.toLowerCase().startsWith(j.toLowerCase())) : 0;
	const mappings = [];
	for (let i = 0; i < 7; i++) {
		const jourIndex = (jourActuelIndex + i) % 7;
		const label = i === 0 ? 'Auj' : (i === 1 ? 'Dem' : jours[jourIndex]);
		mappings.push(`${label}=${cycle + i}`);
	}
	prompt += `Mapping: ${mappings.join(', ')}\n\n`;

	// === RDV EXISTANTS ===
	if (evenementsAVenir?.length > 0) {
		prompt += `## RDV EXISTANTS\n`;
		for (const evt of evenementsAVenir) {
			prompt += `• C${evt.cycle}${evt.heure ? ' ' + evt.heure : ''}: ${evt.titre}`;
			if (evt.participants?.length > 0) {
				const autres = evt.participants.filter(p => p.toLowerCase() !== 'valentin');
				if (autres.length > 0) prompt += ` (${autres.join(', ')})`;
			}
			prompt += '\n';
		}
		prompt += '\n';
	}

	// === CONNAISSANCES EXISTANTES ===
	if (connaissancesExistantes?.length > 0) {
		prompt += `## CONNAISSANCES EXISTANTES (ne pas dupliquer)\n`;

		// Grouper par entité
		const parEntite = {};
		for (const c of connaissancesExistantes) {
			if (!parEntite[c.entite_nom]) parEntite[c.entite_nom] = [];
			parEntite[c.entite_nom].push(c);
		}

		for (const [nom, conns] of Object.entries(parEntite)) {
			prompt += `${nom}: `;
			prompt += conns.map(c => `${c.attribut}="${c.valeur}"`).join(', ');
			prompt += '\n';
		}
		prompt += '\n';
	}

	// === ENTITÉS CONNUES ===
	prompt += `## ENTITÉS CONNUES\n\n`;
	prompt += `Protagoniste: ${entitesConnues.protagoniste}\n\n`;
	if (entitesConnues.personnages?.length > 0) {
		prompt += `PNJ: ${entitesConnues.personnages.map(p => p.nom).join(', ')}\n`;
	}
	if (entitesConnues.lieux?.length > 0) {
		prompt += `Lieux: ${entitesConnues.lieux.map(l => l.nom).join(', ')}\n`;
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

		console.log(JSON.stringify(parsed, null, 2))

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
		// Événements à venir + entités (en parallèle, SANS relations)
		const [partie, evenementsAVenir, entitesConnues, relationsValentin, connaissancesExistantes] = await Promise.all([
			supabase
				.from('parties')
				.select('jour, date_jeu')
				.eq('id', partieId)
				.single()
				.then(r => r.data),
			supabase
				.from('kg_v_evenements_a_venir')
				.select('*')
				.eq('partie_id', partieId)
				.gte('cycle', cycle)
				.order('cycle')
				.limit(10)
				.then(r => r.data || []),
			getEntitesConnuesPourHaiku(supabase, partieId),
			getRelationsValentin(supabase, partieId),
			supabase
				.from('kg_v_connaissances_actives')
				.select('entite_nom, attribut, valeur')
				.eq('partie_id', partieId)
				.then(r => r.data || [])
		]);

		// Construire et appeler
		const prompt = buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle, partie?.jour, partie?.date_jeu, evenementsAVenir, connaissancesExistantes);

		const result = await appelHaiku(prompt);

		if (result.error) {
			metrics.erreurs.push(result.error);
			metrics.duree_ms = Date.now() - startTime;
			await logExtraction(supabase, partieId, cycle, sceneId, metrics);
			return { success: false, metrics };
		}

		// Valider les opérations
		const operations = result.operations || [];
		const { valides, invalides } = validerOperations(operations);

		// Log les opérations invalides
		for (const inv of invalides) {
			const opName = inv.op?.op || '?';
			metrics.erreurs.push(`${opName}: ${inv.erreur}`);
			console.warn(`[KG Extractor] Opération invalide:`, inv.op, '→', inv.erreur);
		}

		// Log les corrections (opérations normalisées)
		if (invalides.length > 0) {
			console.log(`[KG Extractor] ${valides.length} valides, ${invalides.length} rejetées`);
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
	// Toujours extraire si indicateurs explicites dans le JSON
	if (parsed?.nouveaux_pnj?.length > 0) return true;
	if (parsed?.nouveau_lieu) return true;
	if (parsed?.transactions?.length > 0) return true;
	if (parsed?.changements_relation?.length > 0) return true;
	if (parsed?.nouveau_cycle) return true;

	const texte = narratif.toLowerCase();

	// === DIALOGUES ===
	const aDialogue = texte.includes('«') || texte.includes('»');

	// === ÉVÉNEMENTS GÉNÉRAUX ===
	const motsEvenements = [
		'rencontre', 'découvre', 'apprend', 'achète', 'vend',
		'promet', 'accepte', 'refuse', 'propose', 'invite'
	];
	const aEvenement = motsEvenements.some(mot => texte.includes(mot));

	// === PATTERNS DE RDV (NOUVEAU) ===
	const patternsRdv = [
		// Temporels
		'demain', 'après-demain', 'ce soir', 'ce midi', 'cette nuit',
		'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche',
		'la semaine prochaine', 'le mois prochain', 'dans quelques jours',
		// Formulations RDV
		'on se voit', 'on se retrouve', 'on se rejoint',
		'rendez-vous', 'rdv',
		'je passe', 'tu passes', 'passe me voir', 'passe chez',
		'je viendrai', 'je serai là',
		// Confirmations
		'ça marche', 'd\'accord pour', 'c\'est noté', 'promis',
		'compte sur moi', 'sans faute',
		// Heures
		/à \d{1,2}h/, /vers \d{1,2}h/, /\d{1,2}h\d{2}/
	];

	const aPatternRdv = patternsRdv.some(pattern => {
		if (pattern instanceof RegExp) {
			return pattern.test(texte);
		}
		return texte.includes(pattern);
	});

	// === PATTERNS D'ANNULATION ===
	const patternsAnnulation = [
		'annul', 'reporter', 'décaler', 'remettre à plus tard',
		'ne pourrai pas', 'ne peux pas venir', 'empêché'
	];
	const aAnnulation = patternsAnnulation.some(p => texte.includes(p));

	return aDialogue || aEvenement || aPatternRdv || aAnnulation;
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
