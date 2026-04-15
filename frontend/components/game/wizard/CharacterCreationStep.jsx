'use client';

import { getFateSkills, FATE_LADDER, D6_ATTRIBUTES, D6_STARTING_ATTRIBUTE_DICE } from '../../../lib/game/engineConfig';

// ============================================================================
// NONE ENGINE
// ============================================================================

function NoneCharacter() {
	return (
		<div className="text-center py-8 text-gray-400">
			<p className="text-lg mb-2">Mode libre</p>
			<p className="text-sm">Pas de configuration mécanique nécessaire.</p>
			<p className="text-sm">Le narrateur gère tout.</p>
		</div>
	);
}

// ============================================================================
// NARRATIVE ENGINE — Traits
// ============================================================================

function NarrativeCharacter({ data, onChange }) {
	const traits = data.traits || [{ name: '', description: '' }];

	const updateTrait = (idx, field, val) => {
		const next = traits.map((t, i) => (i === idx ? { ...t, [field]: val } : t));
		onChange({ ...data, traits: next });
	};

	const addTrait = () => {
		if (traits.length < 5) {
			onChange({ ...data, traits: [...traits, { name: '', description: '' }] });
		}
	};

	const removeTrait = (idx) => {
		if (traits.length > 1) {
			onChange({ ...data, traits: traits.filter((_, i) => i !== idx) });
		}
	};

	return (
		<div className="space-y-3">
			<p className="text-gray-400 text-sm">
				Définis 1 à 5 traits qui caractérisent ton personnage.
			</p>
			{traits.map((t, i) => (
				<div key={i} className="flex gap-2 items-start">
					<div className="flex-1 space-y-1">
						<input
							value={t.name}
							onChange={(e) => updateTrait(i, 'name', e.target.value)}
							placeholder={`Trait ${i + 1}`}
							className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
						/>
						<input
							value={t.description}
							onChange={(e) => updateTrait(i, 'description', e.target.value)}
							placeholder="Description courte"
							className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-gray-300 text-xs placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
						/>
					</div>
					{traits.length > 1 && (
						<button
							onClick={() => removeTrait(i)}
							className="p-1.5 text-gray-500 hover:text-red-400 transition-colors"
						>
							✕
						</button>
					)}
				</div>
			))}
			{traits.length < 5 && (
				<button
					onClick={addTrait}
					className="text-sm text-emerald-400 hover:text-emerald-300 transition-colors"
				>
					+ Ajouter un trait
				</button>
			)}
		</div>
	);
}

// ============================================================================
// FATE CORE — Aspects + Skill Pyramid
// ============================================================================

function FateCoreCharacter({ data, onChange, genre }) {
	const skills = getFateSkills(genre);
	const aspects = data.aspects || { high_concept: '', trouble: '', other: ['', '', ''] };
	const skillPicks = data.skills || {};
	// Pyramid: 1 at +4, 2 at +3, 3 at +2, 4 at +1
	const pyramidSlots = { 4: 1, 3: 2, 2: 3, 1: 4 };

	const updateAspect = (key, val) => {
		const next = { ...aspects, [key]: val };
		onChange({ ...data, aspects: next });
	};

	const updateOtherAspect = (idx, val) => {
		const other = [...aspects.other];
		other[idx] = val;
		updateAspect('other', other);
	};

	const setSkillLevel = (skill, level) => {
		const next = { ...skillPicks };
		// Remove from any current level
		Object.keys(next).forEach(k => {
			if (Array.isArray(next[k])) {
				next[k] = next[k].filter(s => s !== skill);
				if (next[k].length === 0) delete next[k];
			}
		});
		// Add to new level
		if (level > 0) {
			const key = String(level);
			if (!next[key]) next[key] = [];
			next[key].push(skill);
		}
		onChange({ ...data, skills: next });
	};

	const getSkillLevel = (skill) => {
		for (const [level, arr] of Object.entries(skillPicks)) {
			if (Array.isArray(arr) && arr.includes(skill)) return parseInt(level);
		}
		return 0;
	};

	const slotsUsed = {};
	Object.entries(skillPicks).forEach(([level, arr]) => {
		if (Array.isArray(arr)) slotsUsed[level] = arr.length;
	});

	return (
		<div className="space-y-5">
			{/* Aspects */}
			<div className="space-y-2">
				<label className="block text-sm text-gray-300 font-medium">Aspects</label>
				<div>
					<span className="text-xs text-gray-500">Concept principal</span>
					<input
						value={aspects.high_concept}
						onChange={(e) => updateAspect('high_concept', e.target.value)}
						placeholder="Ex: Pilote intrépide de cargos spatiaux"
						className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary/50"
					/>
				</div>
				<div>
					<span className="text-xs text-gray-500">Problème</span>
					<input
						value={aspects.trouble}
						onChange={(e) => updateAspect('trouble', e.target.value)}
						placeholder="Ex: Recherché par la guilde des marchands"
						className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary/50"
					/>
				</div>
				{aspects.other.map((a, i) => (
					<div key={i}>
						<span className="text-xs text-gray-500">Aspect {i + 3}</span>
						<input
							value={a}
							onChange={(e) => updateOtherAspect(i, e.target.value)}
							placeholder="Aspect libre..."
							className="w-full px-3 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary/50"
						/>
					</div>
				))}
			</div>

			{/* Skill pyramid */}
			<div>
				<label className="block text-sm text-gray-300 font-medium mb-2">
					Pyramide de compétences
				</label>
				<div className="space-y-2">
					{[4, 3, 2, 1].map(level => (
						<div key={level} className="flex items-center gap-2">
							<span className="text-xs text-gray-400 w-20 text-right">
								+{level} {FATE_LADDER[level]}
							</span>
							<span className="text-xs text-gray-600">
								({(slotsUsed[String(level)] || 0)}/{pyramidSlots[level]})
							</span>
						</div>
					))}
				</div>
				<div className="mt-3 flex flex-wrap gap-1.5">
					{skills.map(skill => {
						const level = getSkillLevel(skill);
						return (
							<button
								key={skill}
								onClick={() => {
									// Cycle: 0 → 1 → 2 → 3 → 4 → 0
									const nextLevel = (level + 1) % 5;
									// Check slot availability
									if (nextLevel > 0) {
										const used = slotsUsed[String(nextLevel)] || 0;
										if (used >= pyramidSlots[nextLevel]) {
											setSkillLevel(skill, 0);
											return;
										}
									}
									setSkillLevel(skill, nextLevel);
								}}
								className={`px-2 py-1 rounded text-xs transition-colors ${
									level > 0
										? 'bg-primary/25 border border-primary text-primary-fixed'
										: 'bg-gray-800 text-gray-400 border border-gray-700 hover:border-gray-600'
								}`}
								title={level > 0 ? `+${level} ${FATE_LADDER[level]}` : 'Non assignée'}
							>
								{skill}{level > 0 && ` +${level}`}
							</button>
						);
					})}
				</div>
			</div>
		</div>
	);
}

// ============================================================================
// D6 SYSTEM — Attribute Allocation
// ============================================================================

function D6Character({ data, onChange }) {
	const attrs = data.attributes || {};
	const totalDice = D6_STARTING_ATTRIBUTE_DICE;

	// Parse "3D+1" format to pips (1D = 3 pips)
	const parseDice = (str) => {
		if (!str) return 6; // 2D default
		const m = str.match(/(\d+)D(?:\+(\d+))?/i);
		if (!m) return 6;
		return parseInt(m[1]) * 3 + parseInt(m[2] || 0);
	};

	const formatDice = (pips) => {
		const dice = Math.floor(pips / 3);
		const rem = pips % 3;
		return rem > 0 ? `${dice}D+${rem}` : `${dice}D`;
	};

	const usedPips = D6_ATTRIBUTES.reduce((sum, a) => sum + parseDice(attrs[a]), 0);
	const remainingPips = totalDice * 3 - usedPips;

	const updateAttr = (attr, delta) => {
		const current = parseDice(attrs[attr]);
		const next = current + delta;
		if (next < 3 || next > 15) return; // Min 1D, max 5D
		if (delta > 0 && remainingPips < delta) return;
		onChange({ ...data, attributes: { ...attrs, [attr]: formatDice(next) } });
	};

	return (
		<div className="space-y-4">
			<p className="text-gray-400 text-sm">
				Répartis {totalDice}D entre 6 attributs (min 1D, max 5D).
				<span className={`ml-2 font-mono ${remainingPips >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
					Reste: {formatDice(remainingPips > 0 ? remainingPips : 0)}
				</span>
			</p>
			<div className="space-y-2">
				{D6_ATTRIBUTES.map(attr => {
					const pips = parseDice(attrs[attr]);
					return (
						<div key={attr} className="flex items-center gap-3">
							<span className="text-sm text-gray-300 w-28">{attr}</span>
							<button
								onClick={() => updateAttr(attr, -1)}
								className="w-7 h-7 flex items-center justify-center bg-gray-800 border border-gray-700 rounded text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
							>
								-
							</button>
							<span className="text-sm text-white font-mono w-12 text-center">
								{formatDice(pips)}
							</span>
							<button
								onClick={() => updateAttr(attr, 1)}
								className="w-7 h-7 flex items-center justify-center bg-gray-800 border border-gray-700 rounded text-gray-400 hover:text-white hover:border-gray-500 transition-colors"
							>
								+
							</button>
							{/* Visual bar */}
							<div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
								<div
									className="h-full bg-blue-500 transition-all"
									style={{ width: `${(pips / 15) * 100}%` }}
								/>
							</div>
						</div>
					);
				})}
			</div>
		</div>
	);
}

// ============================================================================
// MAIN DISPATCH
// ============================================================================

export default function CharacterCreationStep({ engine, genre, data, onChange }) {
	return (
		<div className="space-y-6">
			<h2 className="text-xl font-semibold text-white">Création du personnage</h2>

			{/* Common character identity — all engines */}
			<div className="space-y-4">
				<div>
					<label className="block text-sm text-on-surface-variant mb-1">Nom du protagoniste</label>
					<input
						value={data.name || ''}
						onChange={(e) => onChange({ ...data, name: e.target.value })}
						placeholder="Valentin"
						className="w-full px-3 py-2 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface text-sm placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/50"
					/>
				</div>

				<div className="grid grid-cols-2 gap-4">
					<div>
						<label className="block text-sm text-on-surface-variant mb-1">Genre</label>
						<select
							value={data.gender || ''}
							onChange={(e) => onChange({ ...data, gender: e.target.value })}
							className="w-full px-3 py-2 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
						>
							<option value="">Non précisé</option>
							<option value="male">Homme</option>
							<option value="female">Femme</option>
							<option value="non-binary">Non-binaire</option>
							<option value="other">Autre</option>
						</select>
					</div>
					<div>
						<label className="block text-sm text-on-surface-variant mb-1">Occupation</label>
						<input
							value={data.occupation || ''}
							onChange={(e) => onChange({ ...data, occupation: e.target.value })}
							placeholder="Ex: mécanicien, archiviste, mercenaire..."
							className="w-full px-3 py-2 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface text-sm placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/50"
						/>
					</div>
				</div>

				<div>
					<label className="block text-sm text-on-surface-variant mb-1">Description</label>
					<textarea
						value={data.description || ''}
						onChange={(e) => onChange({ ...data, description: e.target.value })}
						placeholder="Apparence, personnalité, passé... Décris ton personnage en quelques lignes."
						rows={3}
						className="w-full px-3 py-2 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface text-sm placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
					/>
					<p className="text-xs text-on-surface-variant/40 mt-1">Optionnel — le MJ inventera ce que tu ne précises pas</p>
				</div>
			</div>

			{/* Engine-specific mechanics */}
			{engine === 'none' && <NoneCharacter />}
			{engine === 'narrative' && <NarrativeCharacter data={data} onChange={onChange} />}
			{engine === 'fate_core' && <FateCoreCharacter data={data} onChange={onChange} genre={genre} />}
			{engine === 'd6' && <D6Character data={data} onChange={onChange} />}
		</div>
	);
}
