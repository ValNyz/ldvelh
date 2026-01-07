/**
 * Transaction Extractor
 * Extrait les transactions financières et les mouvements d'inventaire
 */

import Anthropic from '@anthropic-ai/sdk';
import { MODELS, API_CONFIG } from '../../constants.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const PROMPT_TRANSACTIONS = `Extrais transactions et mouvements d'inventaire. Si aucun: { "transactions": [] }

TYPES:
- Financiers (montant en crédits): achat(-, +objet), vente(+, -objet), salaire(+), loyer(-), facture(-), amende(-), service(-)
- Transferts: don, cadeau_recu, pret, emprunt, retour_pret
- État: perte, oubli, vol, destruction, degradation, reparation
- Déplacement: deplacement (localisation_depuis → localisation_vers)

FORMAT:
{ "transactions": [
  {"type": "achat", "montant": -15, "objet": "Sandwich", "categorie": "nourriture", "description": "..."},
  {"type": "salaire", "montant": 1800, "description": "..."},
  {"type": "don", "objet": "Livre", "pnj_name": "Justine Lépicier"},
  {"type": "deplacement", "objet": "Tablet", "localisation_depuis": "sur_soi", "localisation_vers": "Appartement 1247"}
]}

Utiliser les noms EXACTS des objets de l'inventaire
Catégories: nourriture, equipement, vetements, electronique, decoration, documents, outils, hygiene, loisirs
États: neuf, bon, use, endommage, casse
Localisations: sur_soi, sac_a_dos, Appartement XXXX, ou nom de lieu`;

/**
 * Extrait les transactions depuis le narratif
 * @param {string} narratif 
 * @param {number} credits - Crédits actuels
 * @param {Array} inventaire - Inventaire actuel
 * @returns {Promise<{success: boolean, transactions?: Array, error?: string}>}
 */
export async function extractTransactions(narratif, credits, inventaire) {
	const start = Date.now();

	try {
		const context = buildContext(narratif, credits, inventaire);

		const response = await anthropic.messages.create({
			model: MODELS.EXTRACTION,
			max_tokens: API_CONFIG.MAX_TOKENS_EXTRACTION,
			system: [{
				type: 'text',
				text: PROMPT_TRANSACTIONS,
				cache_control: { type: 'ephemeral' }
			}],
			messages: [{ role: 'user', content: context }]
		});

		const content = response.content[0]?.text;
		const parsed = parseJSON(content);

		console.log("[Transaction] Extracted: ", JSON.stringify(parsed, null, 2))

		if (!parsed) {
			return { success: false, error: 'JSON invalide' };
		}

		const transactions = parsed.transactions || [];

		// Valider les transactions
		const validated = transactions
			.map(tx => validateTransaction(tx, credits, inventaire))
			.filter(tx => tx !== null);

		console.log(`[Transactions] ${validated.length} extraites en ${Date.now() - start}ms`);

		return { success: true, transactions: validated };

	} catch (err) {
		console.error('[Transactions] Erreur:', err.message);
		return { success: false, error: err.message };
	}
}

function buildContext(narratif, credits, inventaire) {
	let ctx = `## CRÉDITS ACTUELS: ${credits}\n\n`;

	ctx += `## INVENTAIRE\n`;
	if (inventaire?.length > 0) {
		// Grouper par localisation
		const parLoc = {};
		for (const item of inventaire) {
			const loc = item.localisation || 'sur_soi';
			if (!parLoc[loc]) parLoc[loc] = [];
			parLoc[loc].push(item);
		}

		for (const [loc, items] of Object.entries(parLoc)) {
			ctx += `${loc}:\n`;
			for (const item of items) {
				ctx += `  - ${item.objet_nom}`;
				if (item.quantite > 1) ctx += ` (x${item.quantite})`;
				if (item.etat && item.etat !== 'bon') ctx += ` [${item.etat}]`;
				ctx += '\n';
			}
		}
	} else {
		ctx += '(vide)\n';
	}

	ctx += `\n## NARRATIF\n${narratif}`;

	return ctx;
}

function validateTransaction(tx, credits, inventaire) {
	if (!tx.type) return null;

	// Vérifier que les achats ne dépassent pas le solde
	if (tx.type === 'achat' && tx.montant) {
		const montant = Math.abs(tx.montant) * -1; // Toujours négatif
		if (credits + montant < 0) {
			console.warn(`[Transactions] Achat refusé: solde insuffisant (${credits} + ${montant})`);
			return null;
		}
		tx.montant = montant;
	}

	// Vérifier que l'objet existe pour les opérations qui le requièrent
	const typesRequierentObjet = ['don', 'pret', 'deplacement', 'perte', 'oubli', 'vol', 'destruction', 'degradation', 'reparation', 'vente'];
	if (typesRequierentObjet.includes(tx.type) && tx.objet) {
		const existe = inventaire?.some(item =>
			item.objet_nom?.toLowerCase() === tx.objet?.toLowerCase()
		);
		if (!existe) {
			console.warn(`[Transactions] Objet non trouvé: ${tx.objet}`);
			// On laisse passer, le fuzzy matching s'en occupera
		}
	}

	return tx;
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
