/**
 * Extracteur KG pour LDVELH
 * Appelle Haiku pour extraire les opérations KG depuis le narratif Sonnet
 */

import Anthropic from '@anthropic-ai/sdk';
import {
	getEntitesConnuesPourHaiku,
	getRelationsValentin,
	appliquerOperations,
	logExtraction
} from './kgService.js';

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const HAIKU_MODEL = 'claude-3-5-haiku-20241022';
const MAX_RETRIES = 1;

// ============================================================================
// PROMPT HAIKU EXTRACTION
// ============================================================================

const PROMPT_EXTRACTION = `# Extraction Knowledge Graph — LDVELH

Tu analyses un narratif de jeu de rôle SF pour extraire les opérations sur le Knowledge Graph.

## FORMAT OBLIGATOIRE

Réponds UNIQUEMENT avec un JSON valide :
- Commence par \`{\`, termine par \`}\`
- AUCUN texte avant/après, AUCUN backtick

{
  "operations": [
    { "op": "...", ... }
  ],
  "contradictions": [],
  "entites_ambigues": []
}

---

## OPÉRATIONS DISPONIBLES

### CREER_ENTITE
Nouveau personnage, lieu, objet, organisation mentionné pour la première fois.

{
  "op": "CREER_ENTITE",
  "type": "personnage|lieu|objet|organisation",
  "nom": "Nom complet si connu",
  "alias": ["surnom", "description"],
  "proprietes": {
    // personnage: age, espece, metier, physique, traits[]
    // lieu: niveau (zone|secteur|lieu), type_lieu, ambiance
    // objet: type_objet, valeur, etat
    // organisation: type_org, domaine
  },
  "confirme": true
}

Note: \`confirme: false\` si le personnage est juste mentionné mais pas rencontré.

### MODIFIER_ENTITE
Enrichir une entité existante avec de nouvelles infos.

{
  "op": "MODIFIER_ENTITE",
  "entite": "Nom existant",
  "nouveau_nom": "Si on apprend le vrai nom",
  "alias_ajouter": ["nouveau surnom"],
  "proprietes": { "metier": "nouveau métier découvert" },
  "confirme": true
}

### SUPPRIMER_ENTITE
Quand une entité disparaît (mort, départ, destruction).

{
  "op": "SUPPRIMER_ENTITE",
  "entite": "Nom",
  "raison": "mort|parti|detruit|vendu"
}

### CREER_RELATION
Nouvelle relation entre deux entités.

{
  "op": "CREER_RELATION",
  "source": "Nom source",
  "cible": "Nom cible",
  "type": "connait|employe_de|habite|possede|...",
  "proprietes": {
    // connait: niveau (0-10), etape_romantique (0-6), contexte
    // employe_de: poste, horaires
    // possede: quantite
  },
  "certitude": "certain|croit|soupconne|rumeur",
  "verite": true,
  "source_info": "vu|entendu de X|deduit"
}

Types de relations:
- Personnage↔Personnage: connait, ami_de, famille_de, collegue_de, superieur_de, interesse_par, rival_de, a_aide, doit_service_a
- Personnage↔Lieu: habite, travaille_a, frequente, a_visite
- Personnage↔Organisation: employe_de, membre_de, client_de
- Personnage↔Objet: possede, veut, a_perdu
- Lieu↔Lieu: situe_dans (hiérarchie), connecte_a, proche_de

### MODIFIER_RELATION
Mettre à jour une relation existante (ex: niveau relation augmente).

{
  "op": "MODIFIER_RELATION",
  "source": "Nom source",
  "cible": "Nom cible", 
  "type": "connait",
  "proprietes": { "niveau": 2 },
  "raison": "conversation approfondie"
}

### TERMINER_RELATION
Quand une relation prend fin.

{
  "op": "TERMINER_RELATION",
  "source": "Nom source",
  "cible": "Nom cible",
  "type": "possede|employe_de|...",
  "raison": "vendu|licencie|rupture|..."
}

### MODIFIER_ETAT
Changer un état temporel d'une entité.

{
  "op": "MODIFIER_ETAT",
  "entite": "Nom",
  "attribut": "humeur|disposition|energie|moral|sante|credits|localisation|etat",
  "valeur": "nouvelle valeur",
  "details": { "cause": "..." }
}

Attributs courants:
- Valentin: energie (1-5), moral (1-5), sante (1-5), credits, humeur, localisation
- Personnages: disposition (envers Valentin), humeur, localisation
- Lieux: etat (ouvert|ferme|bonde|vide|en_travaux)
- Objets: etat (neuf|bon|use|abime|casse)

### CREER_EVENEMENT
Événement passé significatif.

{
  "op": "CREER_EVENEMENT",
  "titre": "Titre court",
  "categorie": "social|travail|transaction|deplacement|decouverte|incident",
  "description": "Description optionnelle",
  "lieu": "Nom du lieu",
  "heure": "14h30",
  "participants": ["Valentin", "Autre personnage"],
  "montant": -50
}

Créer un événement si:
- Implique une interaction sociale significative
- Transaction financière
- Découverte ou révélation
- Incident ou conflit
- Premier contact avec un lieu/personnage

NE PAS créer d'événement pour:
- Actions mécaniques sans contexte social
- Simples déplacements sans interaction
- Répétition de routines établies

### PLANIFIER_EVENEMENT
Événement futur mentionné.

{
  "op": "PLANIFIER_EVENEMENT",
  "titre": "RDV avec Dr. Chen",
  "categorie": "travail",
  "cycle_prevu": 5,
  "heure": "9h00",
  "lieu": "Bureau Nexus",
  "participants": ["Dr. Chen"]
}

---

## RÈGLES D'EXTRACTION

### Utilise les noms EXACTS
- Si "Justine Lépicier" existe, utilise ce nom, pas "Justine" seul
- Vérifie la liste des entités connues AVANT de créer

### Résolution d'ambiguïtés
Si "la serveuse" pourrait être Justine (connue comme serveuse):
- Utilise "Justine Lépicier" comme nom
- Signale dans entites_ambigues

### Contradictions
Si le narratif dit "Appartement C-247" mais l'entité connue est "Appartement 1247":
- N'applique PAS l'opération contradictoire
- Signale dans contradictions

### Progression relation "connait"
- Échange poli standard: niveau inchangé (pas d'opération)
- Conversation qui crée un lien: +0.1 à +0.2
- Moment de complicité: +0.2 à +0.3
- Service rendu: +0.25 à +0.5
- Maladresse/gêne: -0.1 à -0.25
- Conflit ouvert: -0.5 à -1

### Ce qu'il ne faut PAS extraire
- Descriptions d'ambiance sans impact
- Pensées passagères de Valentin
- Répétitions d'infos déjà dans le KG
- Actions triviales sans conséquence narrative

---

## FORMAT SORTIE

{
  "operations": [
    // Liste des opérations à appliquer
  ],
  "contradictions": [
    {
      "type": "nom_different|info_contradictoire",
      "attendu": "Ce qui est dans le KG",
      "trouve": "Ce qui est dans le narratif",
      "action": "ignore|signale"
    }
  ],
  "entites_ambigues": [
    {
      "mention": "la serveuse",
      "candidats": ["Justine Lépicier"],
      "choix": "Justine Lépicier",
      "confiance": "haute|moyenne|basse"
    }
  ]
}
`;

// ============================================================================
// CONSTRUCTION DU PROMPT
// ============================================================================

function buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle) {
	let prompt = `## NARRATIF À ANALYSER\n\n${narratif}\n\n`;

	prompt += `## CYCLE ACTUEL\n${cycle}\n\n`;

	prompt += `## ENTITÉS CONNUES (utiliser ces noms exacts)\n\n`;

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
			const aliases = l.alias?.length > 0 ? ` (alias: ${l.alias.join(', ')})` : '';
			prompt += `- ${l.nom}${aliases}\n`;
		}
		prompt += '\n';
	}

	if (entitesConnues.organisations?.length > 0) {
		prompt += `Organisations:\n`;
		for (const o of entitesConnues.organisations) {
			prompt += `- ${o.nom}\n`;
		}
		prompt += '\n';
	}

	if (entitesConnues.objets?.length > 0) {
		prompt += `Objets possédés: ${entitesConnues.objets.join(', ')}\n\n`;
	}

	if (relationsValentin?.length > 0) {
		prompt += `## RELATIONS ACTUELLES DE VALENTIN\n\n`;
		for (const r of relationsValentin) {
			const niveau = r.proprietes?.niveau ?? '?';
			prompt += `- ${r.type_relation}: ${r.cible_nom} (niveau: ${niveau})\n`;
		}
		prompt += '\n';
	}

	prompt += `## INSTRUCTIONS\n`;
	prompt += `Extrais les opérations KG du narratif ci-dessus.\n`;
	prompt += `Utilise les noms EXACTS des entités connues.\n`;
	prompt += `Si nouvelle entité, crée-la. Si ambiguïté, préfère l'entité existante.\n`;

	return prompt;
}

// ============================================================================
// PARSING JSON
// ============================================================================

function tryParseJSON(str) {
	if (!str || typeof str !== 'string') return null;

	let cleaned = str.trim();

	// Retirer les backticks markdown
	if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
	if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
	if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
	cleaned = cleaned.trim();

	// Trouver le premier {
	const firstBrace = cleaned.indexOf('{');
	if (firstBrace > 0) cleaned = cleaned.slice(firstBrace);
	if (firstBrace === -1) return null;

	try {
		return JSON.parse(cleaned);
	} catch (e) {
		// Tenter de réparer
		return tryRepairJSON(cleaned);
	}
}

function tryRepairJSON(str) {
	try {
		// Trouver la dernière accolade fermante valide
		let braceCount = 0;
		let lastValidIndex = -1;
		let inString = false;
		let escapeNext = false;

		for (let i = 0; i < str.length; i++) {
			const char = str[i];

			if (escapeNext) {
				escapeNext = false;
				continue;
			}

			if (char === '\\' && inString) {
				escapeNext = true;
				continue;
			}

			if (char === '"' && !escapeNext) {
				inString = !inString;
				continue;
			}

			if (!inString) {
				if (char === '{') braceCount++;
				if (char === '}') {
					braceCount--;
					if (braceCount === 0) lastValidIndex = i;
				}
			}
		}

		if (lastValidIndex > 0) {
			return JSON.parse(str.slice(0, lastValidIndex + 1));
		}

		// Tenter de fermer les accolades manquantes
		let fixed = str;
		if (inString) fixed += '"';
		while (braceCount > 0) {
			fixed += '}';
			braceCount--;
		}

		return JSON.parse(fixed);
	} catch (e) {
		return null;
	}
}

// ============================================================================
// VALIDATION DES OPÉRATIONS
// ============================================================================

const TYPES_ENTITES_VALIDES = ['personnage', 'lieu', 'objet', 'organisation', 'arc_narratif'];
const TYPES_RELATIONS_VALIDES = [
	'connait', 'ami_de', 'famille_de', 'collegue_de', 'superieur_de', 'subordonne_de',
	'en_couple_avec', 'ex_de', 'interesse_par', 'rival_de', 'ennemi_de', 'mefiant_envers',
	'a_aide', 'doit_service_a', 'a_promis_a',
	'habite', 'travaille_a', 'frequente', 'a_visite', 'evite',
	'employe_de', 'membre_de', 'dirige', 'a_quitte', 'client_de',
	'possede', 'veut', 'a_perdu', 'a_prete_a', 'a_emprunte_a',
	'implique_dans',
	'situe_dans', 'connecte_a', 'proche_de', 'vue_sur',
	'appartient_a', 'siege_de',
	'partenaire_de', 'concurrent_de', 'filiale_de',
	'assiste'
];
const ATTRIBUTS_ETAT_VALIDES = [
	'energie', 'moral', 'sante', 'credits', 'humeur', 'localisation',
	'disposition', 'stat_social', 'stat_travail', 'stat_sante',
	'etat', 'ambiance', 'progression'
];

function validerOperation(op) {
	if (!op || !op.op) return { valide: false, raison: 'Opération sans type' };

	switch (op.op) {
		case 'CREER_ENTITE':
			if (!op.type || !TYPES_ENTITES_VALIDES.includes(op.type)) {
				return { valide: false, raison: `Type entité invalide: ${op.type}` };
			}
			if (!op.nom || op.nom.trim().length === 0) {
				return { valide: false, raison: 'Nom entité manquant' };
			}
			break;

		case 'MODIFIER_ENTITE':
		case 'SUPPRIMER_ENTITE':
			if (!op.entite) {
				return { valide: false, raison: 'Entité cible manquante' };
			}
			break;

		case 'CREER_RELATION':
		case 'MODIFIER_RELATION':
		case 'TERMINER_RELATION':
			if (!op.source || !op.cible) {
				return { valide: false, raison: 'Source ou cible manquante' };
			}
			if (!op.type || !TYPES_RELATIONS_VALIDES.includes(op.type)) {
				return { valide: false, raison: `Type relation invalide: ${op.type}` };
			}
			break;

		case 'MODIFIER_ETAT':
			if (!op.entite) {
				return { valide: false, raison: 'Entité cible manquante' };
			}
			if (!op.attribut || !ATTRIBUTS_ETAT_VALIDES.includes(op.attribut)) {
				return { valide: false, raison: `Attribut invalide: ${op.attribut}` };
			}
			if (op.valeur === undefined || op.valeur === null) {
				return { valide: false, raison: 'Valeur manquante' };
			}
			break;

		case 'CREER_EVENEMENT':
			if (!op.titre) {
				return { valide: false, raison: 'Titre événement manquant' };
			}
			break;

		case 'PLANIFIER_EVENEMENT':
			if (!op.titre || !op.cycle_prevu) {
				return { valide: false, raison: 'Titre ou cycle_prevu manquant' };
			}
			break;

		case 'ANNULER_EVENEMENT':
			if (!op.titre) {
				return { valide: false, raison: 'Titre événement manquant' };
			}
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
 * Extrait les opérations KG depuis un narratif et les applique
 * 
 * @param {object} supabase - Client Supabase
 * @param {string} partieId - ID de la partie
 * @param {string} narratif - Texte narratif de Sonnet
 * @param {number} cycle - Cycle actuel
 * @param {string} sceneId - ID de la scène (optionnel, pour logs)
 * @returns {object} Résultats de l'extraction
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
		// 1. Récupérer le contexte pour Haiku
		const [entitesConnues, relationsValentin] = await Promise.all([
			getEntitesConnuesPourHaiku(supabase, partieId),
			getRelationsValentin(supabase, partieId)
		]);

		// 2. Construire le prompt
		const prompt = buildPromptExtraction(narratif, entitesConnues, relationsValentin, cycle);

		// 3. Appeler Haiku
		const result = await appelHaiku(prompt);

		if (result.error) {
			metrics.erreurs.push(result.error);
			metrics.duree_ms = Date.now() - startTime;
			await logExtraction(supabase, partieId, cycle, sceneId, metrics);
			return { success: false, metrics };
		}

		// 4. Valider les opérations
		const operations = result.operations || [];
		const { valides, invalides } = filtrerOperationsValides(operations);

		metrics.nb_operations = valides.length;
		for (const inv of invalides) {
			metrics.erreurs.push(`${inv.op?.op || '?'}: ${inv.raison}`);
		}

		// 5. Enregistrer contradictions et ambiguïtés
		if (result.contradictions?.length > 0) {
			metrics.contradictions = result.contradictions;
		}
		if (result.entites_ambigues?.length > 0) {
			const nonResolues = result.entites_ambigues.filter(e => e.confiance === 'basse');
			metrics.entites_non_resolues = nonResolues.length;
		}

		// 6. Appliquer les opérations valides
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

		// 7. Logger les métriques
		metrics.duree_ms = Date.now() - startTime;
		await logExtraction(supabase, partieId, cycle, sceneId, metrics);

		console.log(`[KG Extractor] ${metrics.nb_operations} ops en ${metrics.duree_ms}ms`);

		return {
			success: true,
			metrics,
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
// EXTRACTION FIN DE CYCLE (plus complète)
// ============================================================================

/**
 * Extraction spéciale fin de cycle
 * Analyse tous les messages du cycle pour un résumé complet
 */
export async function extraireFinDeCycle(supabase, partieId, messagesComplets, cycle, sceneId = null) {
	// Concaténer tous les narratifs du cycle
	const narratifComplet = messagesComplets
		.filter(m => m.role === 'assistant')
		.map(m => m.content)
		.join('\n\n---\n\n');

	if (!narratifComplet.trim()) {
		return { success: true, metrics: { nb_operations: 0 } };
	}

	// Extraction standard mais avec le narratif complet
	return extraireEtAppliquer(supabase, partieId, narratifComplet, cycle, sceneId);
}

// ============================================================================
// EXTRACTION CONDITIONNELLE
// ============================================================================

/**
 * Détermine si une extraction est nécessaire
 * Basé sur des heuristiques simples
 */
export function doitExtraire(narratif, parsed) {
	// Toujours extraire si:

	// Nouveau PNJ mentionné
	if (parsed?.nouveaux_pnj?.length > 0) return true;

	// Nouveau lieu
	if (parsed?.nouveau_lieu) return true;

	// Transaction
	if (parsed?.transactions?.length > 0) return true;

	// Changement de relation
	if (parsed?.changements_relation?.length > 0) return true;

	// Nouveau cycle
	if (parsed?.nouveau_cycle) return true;

	// Heuristiques sur le texte
	const texte = narratif.toLowerCase();

	// Mention de noms propres (majuscule après un espace)
	const mentionNom = /[.!?]\s+[A-Z][a-z]+\s/.test(narratif);

	// Dialogues (guillemets français)
	const aDialogue = texte.includes('«') || texte.includes('»');

	// Mots-clés d'événements
	const motsEvenements = ['rencontre', 'découvre', 'apprend', 'achète', 'vend', 'promet', 'accepte', 'refuse'];
	const aEvenement = motsEvenements.some(mot => texte.includes(mot));

	return mentionNom || aDialogue || aEvenement;
}

// ============================================================================
// EXPORTS
// ============================================================================

export {
	PROMPT_EXTRACTION,
	buildPromptExtraction,
	validerOperation,
	filtrerOperationsValides
};
