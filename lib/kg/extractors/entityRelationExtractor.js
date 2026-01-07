/**
 * Entity & Relation Extractor
 * Extrait les nouvelles entités et les changements de relations
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';
import { withCache } from '@/lib/cache/sessionCache.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });


const PROMPT_ENTITY_RELATION = `Extrais entités nouvelles et changements de relations. Si rien: { "entites": [], "relations": [] }

ENTITÉS (types: personnage, lieu, objet, organisation, arc_narratif):
Créer une entité si : nouveau PNJ, nouveau lieu, nouvel objet
{ "op": "CREER_ENTITE", "type": "personnage", "nom": "...", "visible": {infos explicitement dans le texte}, "background": {enrichissement pour le MJ} }
Modifier une entité si nouvelle info sur une entité existante
{ "op": "MODIFIER_ENTITE", "entite": "Nom Exact", "visible": {"metier": "ingénieur"} }

RELATIONS VALENTIN (80% = delta 0):
{ "op": "MODIFIER_RELATION", "pnj": "Nom Exact", "delta": 0.1, "disposition": "amicale", "raison": "..." }
{ "op": "CREER_RELATION", "source": "Valentin", "cible": "...", "type": "connait", "proprietes": {"niveau": 0} }

Barèmes delta:
+0.1 léger lien | +0.2 complicité | +0.5 aide significative | +0.75 max (rare)
-0.1 maladresse | -0.5 gêne | -1 remarque déplacée | -2 promesse non tenue
80% des échanges neutres

Dispositions: neutre, amicale, distante, agacée, chaleureuse, méfiante, pressée, curieuse, gênée, amusée

FORMAT: { "entites": [...], "relations": [...] }`;

/**
 * Extrait entités et relations depuis le narratif
 * @param {string} narratif 
 * @param {object} entitesConnues - {personnages, lieux, organisations}
 * @param {Array} relationsValentin - Relations actuelles
 * @param {Array} pnjsPresents - PNJ dans la scène
 * @returns {Promise<{success: boolean, entites?: Array, relations?: Array, error?: string}>}
 */
export async function extractEntityRelation(narratif, ia, entitesConnues, relationsValentin, pnjsPresents) {
	const start = Date.now();

	try {
		const context = buildContext(narratif, ia, entitesConnues, relationsValentin, pnjsPresents);

		// console.log("[EntityRelation] Context: ", context)

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

		console.log("[EntityRelation] Extracted: ", JSON.stringify(parsed, null, 2))

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

function buildContext(narratif, ia, entitesConnues, relationsValentin, pnjsPresents) {
	let ctx = `## ENTITÉS CONNUES\n\n`;

	ctx += `Protagoniste: Valentin\n`;
	ctx += `IA: ${ia.nom}\n\n`;

	if (entitesConnues.personnages?.length > 0) {
		ctx += `PNJ connus: ${entitesConnues.personnages.map(l => l.nom).join(' | ')}\n\n`;
	}

	if (entitesConnues.lieux?.length > 0) {
		ctx += `Lieux connus: ${entitesConnues.lieux.map(l => l.nom).join(' | ')}\n\n`;
	}

	if (relationsValentin?.length > 0) {
		let title = false
		for (const rel of relationsValentin) {
			const niveau = rel.proprietes?.niveau ?? 0;
			if (niveau > 0) {
				if (!title) {
					ctx += `## RELATIONS ACTUELLES DE VALENTIN\n\n`;
					start = false
				}
				ctx += `- ${rel.cible_nom}: niveau ${niveau}/10`;
				if (rel.proprietes?.etape_romantique !== undefined) {
					ctx += ` (romance: ${rel.proprietes.etape_romantique}/6)`;
				}
				ctx += '\n';
			}
		}
	} else {
		ctx += '(aucune relation établie)\n';
	}

	if (pnjsPresents?.length > 0) {
		ctx += `\n## PNJ PRÉSENTS DANS CETTE SCÈNE\n`;
		ctx += pnjsPresents.join(', ') + '\n';
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
