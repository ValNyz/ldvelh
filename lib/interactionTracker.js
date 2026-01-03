/**
 * Interaction Tracker pour LDVELH (simplifié)
 * 
 * Ne gère plus que :
 * - L'extraction des PNJ mentionnés dans le narratif
 * - La mise à jour de dernier_contact et cycles_vus
 */

// ============================================================================
// EXTRACTION DES PNJ DEPUIS LE NARRATIF
// ============================================================================

function extractPnjFromNarratif(narratif, knownPnj) {
	if (!narratif || !knownPnj || knownPnj.length === 0) return [];

	const textLower = narratif.toLowerCase();
	const mentioned = [];

	const isWordPresent = (text, word) => {
		const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const regex = new RegExp(`(?:^|[\\s.,!?;:'"«»()\\-])${escaped}(?:[\\s.,!?;:'"«»()\\-]|$)`, 'i');
		return regex.test(text);
	};

	for (const pnj of knownPnj) {
		if (!pnj.nom) continue;

		const nomLower = pnj.nom.toLowerCase();
		const prenom = pnj.nom.split(' ')[0].toLowerCase();

		if (isWordPresent(textLower, nomLower)) {
			mentioned.push(pnj);
			continue;
		}

		if (prenom.length >= 3 && isWordPresent(textLower, prenom)) {
			mentioned.push(pnj);
		}
	}

	return mentioned;
}

// ============================================================================
// MISE À JOUR DES PNJ
// ============================================================================

async function updatePnjContact(supabase, partieId, cycle, pnjMentionnes) {
	if (!pnjMentionnes || pnjMentionnes.length === 0) {
		return { updated: 0, errors: [] };
	}

	const errors = [];
	let updated = 0;

	for (const pnj of pnjMentionnes) {
		if (!pnj.id) continue;

		const cyclesVus = Array.isArray(pnj.cycles_vus) ? [...pnj.cycles_vus] : [];
		if (!cyclesVus.includes(cycle)) {
			cyclesVus.push(cycle);
		}

		const { error } = await supabase
			.from('pnj')
			.update({
				dernier_contact: cycle,
				cycles_vus: cyclesVus,
				updated_at: new Date().toISOString()
			})
			.eq('id', pnj.id);

		if (error) {
			errors.push(`Erreur update PNJ ${pnj.id}: ${error.message}`);
		} else {
			updated++;
		}
	}

	return { updated, errors };
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	extractPnjFromNarratif,
	updatePnjContact
};
