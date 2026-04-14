/**
 * LDVELH - Engine Configuration
 * Engine options, genre/difficulty constants, skill/attribute lists.
 * Mirrors backend engine_data.py for wizard validation.
 */

// ============================================================================
// ENGINE DEFINITIONS
// ============================================================================

export const ENGINES = [
	{
		id: 'none',
		name: 'Mode Libre',
		description: 'Narration pure, sans mécanique de jeu. Le narrateur décide de tout.',
		icon: '📖',
		color: 'gray',
	},
	{
		id: 'narrative',
		name: 'Narratif',
		description: 'Traits de personnage influencent la narration. Pas de dés, le narrateur juge la difficulté.',
		icon: '🎭',
		color: 'emerald',
	},
	{
		id: 'fate_core',
		name: 'Fate Core',
		description: 'Dés Fudge, aspects, points de destin. Système narratif avec mécanique légère.',
		icon: '🎲',
		color: 'amber',
	},
	{
		id: 'd6',
		name: 'Système D6',
		description: 'Dés à 6 faces + dé sauvage. Système classique avec attributs et compétences.',
		icon: '🎯',
		color: 'blue',
	},
];

// ============================================================================
// GENRES
// ============================================================================

export const GENRES = [
	{ id: 'sci-fi', name: 'Science-Fiction', icon: '🚀' },
	{ id: 'fantasy', name: 'Fantasy', icon: '🗡️' },
	{ id: 'cthulhu', name: 'Cthulhu', icon: '🐙' },
	{ id: 'historical', name: 'Historique', icon: '🏛️' },
	{ id: 'contemporary', name: 'Contemporain', icon: '🌆' },
];

// ============================================================================
// DIFFICULTY
// ============================================================================

export const DIFFICULTIES = [
	{ id: 'easy', name: 'Facile', description: 'Tests rares, conséquences légères' },
	{ id: 'moderate', name: 'Modéré', description: 'Équilibre action/narration' },
	{ id: 'hard', name: 'Difficile', description: 'Tests fréquents, conséquences sévères' },
	{ id: 'brutal', name: 'Brutal', description: 'Survie incertaine, chaque choix compte' },
];

// ============================================================================
// FATE CORE SKILLS
// ============================================================================

const FATE_SKILLS_BASE = [
	'Athlétisme', 'Cambriolage', 'Combat', 'Commandement', 'Conduite',
	'Contacts', 'Discrétion', 'Empathie', 'Érudition', 'Intimidation',
	'Investigation', 'Métiers', 'Perception', 'Persuasion', 'Physique',
	'Provocation', 'Ressources', 'Tir', 'Tromperie', 'Volonté',
];

const FATE_SKILLS_BY_GENRE = {
	'fantasy': { add: ['Magie', 'Équitation', 'Survie'], remove: [] },
	'sci-fi': { add: ['Pilotage', 'Technologie', 'Piratage'], remove: ['Équitation'] },
	'cthulhu': { add: ['Occultisme', 'Santé Mentale', 'Langues Anciennes'], remove: ['Commandement'] },
	'historical': { add: ['Équitation', 'Survie', 'Artisanat'], remove: ['Pilotage', 'Technologie'] },
	'contemporary': { add: ['Informatique', 'Réseau Social'], remove: [] },
};

export function getFateSkills(genre) {
	const skills = [...FATE_SKILLS_BASE];
	const mods = FATE_SKILLS_BY_GENRE[genre];
	if (mods) {
		for (const s of mods.remove) {
			const idx = skills.indexOf(s);
			if (idx >= 0) skills.splice(idx, 1);
		}
		skills.push(...mods.add);
	}
	return skills.sort();
}

// Fate difficulty ladder labels
export const FATE_LADDER = {
	0: 'Médiocre', 1: 'Moyen', 2: 'Correct', 3: 'Bon',
	4: 'Excellent', 5: 'Superbe', 6: 'Fantastique', 7: 'Épique', 8: 'Légendaire',
};

// Default skill pyramid: 1 at +4, 2 at +3, 3 at +2, 4 at +1
export const FATE_DEFAULT_PYRAMID = { 4: 1, 3: 2, 2: 3, 1: 4 };

// ============================================================================
// D6 SYSTEM
// ============================================================================

export const D6_ATTRIBUTES = [
	'Dextérité', 'Connaissance', 'Mécanique', 'Perception', 'Force', 'Technique',
];

export const D6_STARTING_ATTRIBUTE_DICE = 18;
export const D6_STARTING_SKILL_DICE = 7;
