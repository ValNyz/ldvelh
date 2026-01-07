/**
 * Entity & Relation Extractor
 * Extrait les nouvelles entités et les changements de relations
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const PROMPT_ENTITY_RELATION = `Extrais les entités et changements de relations de cette scène.

## ENTITÉS

**Types** : personnage, lieu, objet, organisation, arc_narratif

**Créer une entité si** :
- Nouveau PNJ mentionné par son nom
- Nouveau lieu visité ou mentionné précisément
- Nouvel objet significatif (pas les consommables jetables)

**Format entité** :
{
  "op": "CREER_ENTITE",
  "type": "personnage",
  "nom": "Nom Complet",
  "visible": { "physique": "...", "metier": "..." },
  "background": { "age": 35, "traits": ["curieux", "réservé"] }
}

- visible : infos explicitement DANS le texte
- background : enrichissement pour le MJ (optionnel)

**Modifier une entité** (nouvelle info découverte) :
{
  "op": "MODIFIER_ENTITE",
  "entite": "Nom Exact",
  "visible": { "metier": "ingénieur" }
}

## RELATIONS VALENTIN

**Changements de relation** avec les PNJ présents :
{
  "op": "MODIFIER_RELATION",
  "pnj": "Nom Exact du PNJ",
  "delta": 0.1,
  "disposition": "amicale",
  "raison": "conversation agréable"
}

**Barèmes delta** (STRICTS) :
- 80% des échanges = 0 (neutre, fonctionnel, oubliable)
- +0.1 : léger lien créé
- +0.2 : moment de complicité
- +0.25 : service rendu apprécié
- +0.5 : aide significative
- +0.75 max : moment fort (rare)
- -0.1 : maladresse légère
- -0.25 : gêne créée
- -0.5 : maladresse embarrassante
- -1 : remarque déplacée
- -2 : promesse non tenue
- -5 : insulte, violence

**Dispositions** : neutre, amicale, distante, agacée, chaleureuse, méfiante, pressée, curieuse, gênée, amusée

**Nouvelles relations** (première rencontre) :
{
  "op": "CREER_RELATION",
  "source": "Valentin",
  "cible": "Nom PNJ",
  "type": "connait",
  "proprietes": { "niveau": 0, "contexte": "croisé au bar" }
}

## FORMAT RÉPONSE

{
  "entites": [
    { "op": "CREER_ENTITE", ... },
    { "op": "MODIFIER_ENTITE", ... }
  ],
  "relations": [
    { "op": "MODIFIER_RELATION", ... },
    { "op": "CREER_RELATION", ... }
  ]
}

Si rien à extraire : { "entites": [], "relations": [] }`;

/**
 * Extrait entités et relations depuis le narratif
 * @param {string} narratif 
 * @param {object} entitesConnues - {personnages, lieux, organisations}
 * @param {Array} relationsValentin - Relations actuelles
 * @param {Array} pnjsPresents - PNJ dans la scène
 * @returns {Promise<{success: boolean, entites?: Array, relations?: Array, error?: string}>}
 */
export async function extractEntityRelation(narratif, entitesConnues, relationsValentin, pnjsPresents) {
	const start = Date.now();

	try {
		const context = buildContext(narratif, entitesConnues, relationsValentin, pnjsPresents);

		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: API_CONFIG.MAX_TOKENS_EXTRACTION,
			system: [{
				type: 'text',
				text: PROMPT_ENTITY_RELATION,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: context }]
		});

		const content = response.content[0]?.text;
		const parsed = parseJSON(content);

		if (!parsed) {
			return { success: false, error: 'JSON invalide' };
		}

		const entites = (parsed.entites || []).filter(validateEntiteOp);
		const relations = (parsed.relations || []).filter(validateRelationOp);

		console.log(`[EntityRelation] ${entites.length} entités, ${relations.length} relations en ${Date.now() - start}ms`);

		return { success: true, entites, relations };

	} catch (err) {
		console.error('[EntityRelation] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}

function buildContext(narratif, entitesConnues, relationsValentin, pnjsPresents) {
	let ctx = `## ENTITÉS CONNUES\n\n`;

	ctx += `Protagoniste: Valentin\n\n`;

	if (entitesConnues.personnages?.length > 0) {
		ctx += `PNJ connus:\n`;
		for (const p of entitesConnues.personnages) {
			ctx += `- ${p.nom}`;
			if (p.alias?.length > 0) ctx += ` (alias: ${p.alias.join(', ')})`;
			ctx += '\n';
		}
		ctx += '\n';
	}

	if (entitesConnues.lieux?.length > 0) {
		ctx += `Lieux connus: ${entitesConnues.lieux.map(l => l.nom).join(', ')}\n\n`;
	}

	ctx += `## RELATIONS ACTUELLES DE VALENTIN\n\n`;
	if (relationsValentin?.length > 0) {
		for (const rel of relationsValentin) {
			const niveau = rel.proprietes?.niveau ?? 0;
			ctx += `- ${rel.cible_nom}: niveau ${niveau}/10`;
			if (rel.proprietes?.etape_romantique !== undefined) {
				ctx += ` (romance: ${rel.proprietes.etape_romantique}/6)`;
			}
			ctx += '\n';
		}
	} else {
		ctx += '(aucune relation établie)\n';
	}

	ctx += `\n## PNJ PRÉSENTS DANS CETTE SCÈNE\n`;
	if (pnjsPresents?.length > 0) {
		ctx += pnjsPresents.join(', ') + '\n';
	} else {
		ctx += '(Valentin est seul)\n';
	}

	ctx += `\n## NARRATIF\n${narratif}`;

	return ctx;
}

function validateEntiteOp(op) {
	if (!op?.op) return false;

	if (op.op === 'CREER_ENTITE') {
		return op.type && op.nom;
	}
	if (op.op === 'MODIFIER_ENTITE') {
		return op.entite && (op.visible || op.background || op.nouveau_nom || op.alias_ajouter);
	}

	return false;
}

function validateRelationOp(op) {
	if (!op?.op) return false;

	if (op.op === 'MODIFIER_RELATION') {
		return op.pnj && (op.delta !== undefined || op.disposition);
	}
	if (op.op === 'CREER_RELATION') {
		return op.source && op.cible && op.type;
	}
	if (op.op === 'TERMINER_RELATION') {
		return op.source && op.cible && op.type;
	}

	return false;
}

function parseJSON(str) {
	if (!str) return null;
	try {
		let cleaned = str.trim();
		if (cleaned.startsWith('```')) {
			cleaned = cleaned.replace(/```json?\n?/g, '').replace(/```$/g, '');
		}
		return JSON.parse(cleaned);
	} catch {
		return null;
	}
}
