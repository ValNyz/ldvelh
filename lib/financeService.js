/**
 * Service de gestion des finances pour LDVELH
 * 
 * Gère les crédits et l'inventaire via la table finances
 */

// ============================================================================
// CALCUL DU SOLDE
// ============================================================================

async function calculerSolde(supabase, partieId, soldeInitial = 1400) {
	const { data, error } = await supabase
		.from('finances')
		.select('montant')
		.eq('partie_id', partieId);

	if (error) {
		console.error('Erreur calcul solde:', error);
		return soldeInitial;
	}

	const totalTransactions = (data || []).reduce((sum, f) => sum + (f.montant || 0), 0);
	return soldeInitial + totalTransactions;
}

// ============================================================================
// CALCUL DE L'INVENTAIRE
// ============================================================================

async function calculerInventaire(supabase, partieId) {
	const { data, error } = await supabase
		.from('finances')
		.select('objet, quantite')
		.eq('partie_id', partieId)
		.not('objet', 'is', null);

	if (error) {
		console.error('Erreur calcul inventaire:', error);
		return [];
	}

	// Agréger par objet
	const inventaireMap = {};
	for (const item of (data || [])) {
		if (!item.objet) continue;
		inventaireMap[item.objet] = (inventaireMap[item.objet] || 0) + (item.quantite || 1);
	}

	// Filtrer les objets avec quantité > 0 et formater
	return Object.entries(inventaireMap)
		.filter(([_, qty]) => qty > 0)
		.map(([nom, qty]) => qty > 1 ? `${nom} (x${qty})` : nom);
}

// ============================================================================
// INSERTION DES TRANSACTIONS
// ============================================================================

async function insererTransactions(supabase, partieId, cycle, heure, transactions) {
	if (!transactions || transactions.length === 0) {
		return { inserted: 0, errors: [] };
	}

	// Récupérer les transactions existantes du cycle
	const { data: existantes } = await supabase
		.from('finances')
		.select('montant, description')
		.eq('partie_id', partieId)
		.eq('cycle', cycle);

	const dejaVu = new Set(
		(existantes || []).map(t => `${t.montant}|${(t.description || '').toLowerCase().slice(0, 30)}`)
	);

	const errors = [];
	const toInsert = [];

	for (const tx of transactions) {
		if (tx.montant === undefined || tx.montant === null) {
			errors.push('Transaction sans montant ignorée');
			continue;
		}

		const montant = parseInt(tx.montant, 10) || 0;
		const description = (tx.description || '').trim();
		const clé = `${montant}|${description.toLowerCase().slice(0, 30)}`;

		// Skip si doublon
		if (dejaVu.has(clé)) {
			console.log(`[FINANCES] Doublon ignoré: ${montant} - ${description}`);
			continue;
		}

		dejaVu.add(clé); // Éviter doublons dans le même batch

		toInsert.push({
			partie_id: partieId,
			cycle: cycle,
			heure: heure || null,
			type: tx.type || 'achat',
			montant: montant,
			objet: tx.objet || null,
			quantite: tx.objet ? (tx.quantite || 1) : null,
			description: description || null
		});
	}

	if (toInsert.length === 0) {
		return { inserted: 0, errors };
	}

	const { error } = await supabase.from('finances').insert(toInsert);

	if (error) {
		errors.push(`Erreur insertion transactions: ${error.message}`);
		return { inserted: 0, errors };
	}

	// Mettre à jour le solde
	const nouveauSolde = await calculerSolde(supabase, partieId);
	await supabase.from('valentin').update({ credits: nouveauSolde }).eq('partie_id', partieId);

	return { inserted: toInsert.length, errors, nouveauSolde };
}

// ============================================================================
// HISTORIQUE DES TRANSACTIONS (optionnel, pour debug/affichage)
// ============================================================================

async function getHistoriqueFinances(supabase, partieId, limit = 20) {
	const { data, error } = await supabase
		.from('finances')
		.select('*')
		.eq('partie_id', partieId)
		.order('created_at', { ascending: false })
		.limit(limit);

	if (error) {
		console.error('Erreur historique finances:', error);
		return [];
	}

	return data || [];
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	calculerSolde,
	calculerInventaire,
	insererTransactions,
	getHistoriqueFinances
};
