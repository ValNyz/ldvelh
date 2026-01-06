/**
 * Fuzzy matching générique pour le KG
 * Évite les doublons quand Claude utilise des noms légèrement différents
 */

// ============================================================================
// NORMALISATION
// ============================================================================

/**
 * Normalise une chaîne pour comparaison
 * "Du Café moulu!" → "cafe moulu"
 */
export function normaliser(str) {
	if (!str) return '';
	return str
		.toLowerCase()
		.normalize('NFD')
		.replace(/[\u0300-\u036f]/g, '') // Accents
		.replace(/^(le|la|les|l'|un|une|des|du|de la|de l'|d')\s*/i, '') // Articles FR
		.replace(/[^a-z0-9\s]/g, '') // Ponctuation
		.trim()
		.replace(/\s+/g, ' '); // Espaces multiples
}

// ============================================================================
// DISTANCE DE LEVENSHTEIN
// ============================================================================

/**
 * Calcule la distance d'édition entre deux chaînes
 */
export function levenshtein(a, b) {
	if (!a || !b) return Math.max(a?.length || 0, b?.length || 0);

	const matrix = [];

	for (let i = 0; i <= b.length; i++) {
		matrix[i] = [i];
	}
	for (let j = 0; j <= a.length; j++) {
		matrix[0][j] = j;
	}

	for (let i = 1; i <= b.length; i++) {
		for (let j = 1; j <= a.length; j++) {
			if (b[i - 1] === a[j - 1]) {
				matrix[i][j] = matrix[i - 1][j - 1];
			} else {
				matrix[i][j] = Math.min(
					matrix[i - 1][j - 1] + 1,
					matrix[i][j - 1] + 1,
					matrix[i - 1][j] + 1
				);
			}
		}
	}

	return matrix[b.length][a.length];
}

// ============================================================================
// CALCUL DE CONFIANCE
// ============================================================================

/**
 * Calcule un score de confiance entre 0 et 100
 */
export function calculerConfiance(input, candidat) {
	const inputNorm = normaliser(input);
	const nomNorm = normaliser(candidat.nom || candidat.titre || '');

	// Match exact
	if (inputNorm === nomNorm) {
		return { confiance: 100, raison: 'exact' };
	}

	// Match sur alias
	const aliasMatch = (candidat.alias || []).some(
		a => normaliser(a) === inputNorm
	);
	if (aliasMatch) {
		return { confiance: 95, raison: 'alias' };
	}

	// Levenshtein sur nom normalisé
	const dist = levenshtein(inputNorm, nomNorm);
	const maxLen = Math.max(inputNorm.length, nomNorm.length);

	if (dist <= 2 && maxLen > 4) {
		const confiance = 90 - (dist * 5);
		return { confiance, raison: `levenshtein:${dist}` };
	}

	// Inclusion
	if (nomNorm.includes(inputNorm) && inputNorm.length >= 3) {
		const ratio = inputNorm.length / nomNorm.length;
		const confiance = Math.round(70 + (ratio * 15));
		return { confiance: Math.min(confiance, 85), raison: 'inclusion:input_dans_nom' };
	}

	if (inputNorm.includes(nomNorm) && nomNorm.length >= 3) {
		const ratio = nomNorm.length / inputNorm.length;
		const confiance = Math.round(65 + (ratio * 15));
		return { confiance: Math.min(confiance, 80), raison: 'inclusion:nom_dans_input' };
	}

	// Similarité Levenshtein
	if (maxLen > 0) {
		const similarity = 1 - (dist / maxLen);
		if (similarity >= 0.6) {
			return { confiance: Math.round(similarity * 80), raison: `similarite:${similarity.toFixed(2)}` };
		}
	}

	return { confiance: 0, raison: 'no_match' };
}

// ============================================================================
// RECHERCHE FUZZY GÉNÉRIQUE
// ============================================================================

/**
 * Cherche un élément par fuzzy matching
 * @param {string} input - Nom recherché
 * @param {Array} candidats - Éléments existants [{id?, nom|titre, alias?, ...}]
 * @param {number} seuil - Seuil de confiance minimum (défaut: 70)
 * @returns {object|null} { element, confiance, raison, ajouterAlias }
 */
export function fuzzyFind(input, candidats, seuil = 70) {
	if (!input || !candidats?.length) return null;

	const matches = [];

	for (const candidat of candidats) {
		const { confiance, raison } = calculerConfiance(input, candidat);

		if (confiance >= seuil) {
			matches.push({ element: candidat, confiance, raison });
		}
	}

	if (matches.length === 0) return null;

	// Trier par confiance décroissante
	matches.sort((a, b) => b.confiance - a.confiance);

	const best = matches[0];
	const nomCandidat = best.element.nom || best.element.titre || '';

	return {
		element: best.element,
		confiance: best.confiance,
		raison: best.raison,
		ajouterAlias: best.confiance < 90 && normaliser(input) !== normaliser(nomCandidat),
		ambiguite: matches.length > 1 ? matches.length : undefined
	};
}

// ============================================================================
// RECHERCHE FUZZY OBJETS (avec désambiguïsation par récence)
// ============================================================================

/**
 * Cherche un objet par fuzzy matching avec désambiguïsation
 */
export function fuzzyFindObjet(input, objets, relations = [], seuil = 70) {
	if (!input || !objets?.length) return null;

	const matches = [];

	for (const objet of objets) {
		const { confiance, raison } = calculerConfiance(input, objet);
		if (confiance >= seuil) {
			matches.push({ objet, confiance, raison });
		}
	}

	if (matches.length === 0) return null;

	if (matches.length === 1) {
		const m = matches[0];
		return {
			objet: m.objet,
			confiance: m.confiance,
			raison: m.raison,
			ajouterAlias: m.confiance < 90 && normaliser(input) !== normaliser(m.objet.nom)
		};
	}

	// Désambiguïser par récence
	const cycleMap = new Map();
	for (const rel of relations) {
		const cycle = rel.proprietes?.dernier_cycle_utilise ?? rel.proprietes?.depuis_cycle ?? 0;
		cycleMap.set(rel.cible_id, cycle);
	}

	matches.sort((a, b) => {
		const cycleA = cycleMap.get(a.objet.id) ?? 0;
		const cycleB = cycleMap.get(b.objet.id) ?? 0;
		if (cycleB !== cycleA) return cycleB - cycleA;
		return b.confiance - a.confiance;
	});

	const best = matches[0];
	return {
		objet: best.objet,
		confiance: best.confiance,
		raison: `${best.raison}+recent`,
		ajouterAlias: best.confiance < 90 && normaliser(input) !== normaliser(best.objet.nom),
		ambiguite: matches.length
	};
}

// ============================================================================
// RECHERCHE FUZZY ÉVÉNEMENTS
// ============================================================================

/**
 * Cherche un événement similaire par fuzzy matching
 * @param {object} nouvelEvt - {titre, cycle, heure?, participants?}
 * @param {Array} evenements - Événements existants
 * @param {number} seuil - Seuil de confiance (défaut: 75)
 * @returns {object|null} { evenement, confiance, raison }
 */
export function fuzzyFindEvenement(nouvelEvt, evenements, seuil = 75) {
	if (!nouvelEvt?.titre || !evenements?.length) return null;

	const matches = [];

	for (const evt of evenements) {
		// Score de base sur le titre
		const { confiance: confianceTitre, raison } = calculerConfiance(nouvelEvt.titre, { nom: evt.titre });

		if (confianceTitre < 50) continue; // Titre trop différent

		let score = confianceTitre;
		let bonus = [];

		// Bonus si même cycle
		if (nouvelEvt.cycle && evt.cycle === nouvelEvt.cycle) {
			score += 15;
			bonus.push('meme_cycle');
		}

		// Bonus si cycles proches (±1)
		else if (nouvelEvt.cycle && Math.abs(evt.cycle - nouvelEvt.cycle) <= 1) {
			score += 5;
			bonus.push('cycle_proche');
		}

		// Bonus si même heure (±30min)
		if (nouvelEvt.heure && evt.heure) {
			const diff = Math.abs(parseHeure(nouvelEvt.heure) - parseHeure(evt.heure));
			if (diff <= 30) {
				score += 10;
				bonus.push('meme_heure');
			}
		}

		// Bonus si participants communs
		if (nouvelEvt.participants?.length && evt.participants?.length) {
			const nouveaux = new Set(nouvelEvt.participants.map(p => normaliser(p)));
			const existants = evt.participants.map(p => normaliser(p));
			const communs = existants.filter(p => nouveaux.has(p)).length;

			if (communs > 0) {
				score += Math.min(communs * 5, 15);
				bonus.push(`participants:${communs}`);
			}
		}

		// Plafonner à 100
		score = Math.min(score, 100);

		if (score >= seuil) {
			matches.push({
				evenement: evt,
				confiance: score,
				raison: bonus.length ? `${raison}+${bonus.join('+')}` : raison
			});
		}
	}

	if (matches.length === 0) return null;

	matches.sort((a, b) => b.confiance - a.confiance);
	return matches[0];
}

/**
 * Parse une heure en minutes depuis minuit
 */
function parseHeure(heureStr) {
	if (!heureStr) return 0;
	const match = heureStr.match(/(\d{1,2})[h:]?(\d{2})?/);
	if (!match) return 0;
	return parseInt(match[1]) * 60 + parseInt(match[2] || '0');
}

// ============================================================================
// RECHERCHE FUZZY TRANSACTIONS
// ============================================================================

/**
 * Vérifie si une transaction existe déjà
 * @param {object} nouvelleTx - {type, montant, objet?, description?}
 * @param {Array} transactions - Transactions existantes du cycle
 * @param {number} seuil - Seuil de confiance (défaut: 80)
 * @returns {object|null} { transaction, confiance, raison }
 */
export function fuzzyFindTransaction(nouvelleTx, transactions, seuil = 80) {
	if (!nouvelleTx || !transactions?.length) return null;

	for (const tx of transactions) {
		let score = 0;
		let raisons = [];

		// Même type = base de 30
		if (tx.type === nouvelleTx.type) {
			score += 30;
			raisons.push('type');
		} else {
			continue; // Type différent = pas le même
		}

		// Même montant = +40
		if (tx.montant === nouvelleTx.montant) {
			score += 40;
			raisons.push('montant_exact');
		} else if (Math.abs(tx.montant - nouvelleTx.montant) <= Math.abs(nouvelleTx.montant * 0.1)) {
			// Montant proche (±10%)
			score += 20;
			raisons.push('montant_proche');
		}

		// Même objet (fuzzy)
		if (nouvelleTx.objet && tx.objet) {
			const { confiance } = calculerConfiance(nouvelleTx.objet, { nom: tx.objet });
			if (confiance >= 70) {
				score += 30;
				raisons.push('objet');
			}
		} else if (!nouvelleTx.objet && !tx.objet) {
			// Ni l'un ni l'autre n'ont d'objet
			score += 15;
		}

		// Description similaire
		if (nouvelleTx.description && tx.description) {
			const { confiance } = calculerConfiance(nouvelleTx.description, { nom: tx.description });
			if (confiance >= 60) {
				score += 15;
				raisons.push('description');
			}
		}

		if (score >= seuil) {
			return {
				transaction: tx,
				confiance: Math.min(score, 100),
				raison: raisons.join('+')
			};
		}
	}

	return null;
}

// ============================================================================
// AJOUT D'ALIAS
// ============================================================================

/**
 * Ajoute un alias à une entité si pas déjà présent
 */
export async function ajouterAliasSiNouveau(supabase, entiteId, nouvelAlias) {
	const aliasNorm = normaliser(nouvelAlias);

	const { data: entite } = await supabase
		.from('kg_entites')
		.select('nom, alias')
		.eq('id', entiteId)
		.single();

	if (!entite) return false;

	const aliasExistants = (entite.alias || []).map(a => normaliser(a));
	if (aliasExistants.includes(aliasNorm) || normaliser(entite.nom) === aliasNorm) {
		return false;
	}

	const nouveauxAlias = [...(entite.alias || []), nouvelAlias];

	await supabase
		.from('kg_entites')
		.update({ alias: nouveauxAlias })
		.eq('id', entiteId);

	console.log(`[FUZZY] Alias ajouté: "${nouvelAlias}" → ${entite.nom}`);
	return true;
}
