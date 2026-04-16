'use client';

// ============================================================================
// DICE ROLL DISPLAY — Mechanical encadré with rule explanations
// ============================================================================

const OUTCOME_STYLES = {
	success: 'border-green-700/50 bg-green-900/30',
	success_with_style: 'border-emerald-700/50 bg-emerald-900/30',
	tie: 'border-yellow-700/50 bg-yellow-900/30',
	failure: 'border-red-700/50 bg-red-900/30',
};

const OUTCOME_LABELS = {
	success: 'Réussite',
	success_with_style: 'Réussite avec style',
	tie: 'Égalité',
	failure: 'Échec',
};

const OUTCOME_COLORS = {
	success: 'text-green-400',
	success_with_style: 'text-emerald-400',
	tie: 'text-yellow-400',
	failure: 'text-red-400',
};

const OUTCOME_EXPLANATIONS = {
	success: 'Tu réussis sans coût particulier.',
	success_with_style: 'Réussite exceptionnelle — un avantage supplémentaire.',
	tie: 'Tu réussis, mais avec un coût mineur.',
	failure: 'L\'action échoue ou réussit avec un coût majeur.',
};

// Fudge die faces
const FUDGE_SYMBOLS = { '-1': '−', '0': '0', '1': '+' };
const FUDGE_COLORS = {
	'-1': 'bg-red-800/80 text-red-200',
	'0': 'bg-surface-container-high text-on-surface-variant',
	'1': 'bg-blue-800/80 text-blue-200',
};

function FudgeDie({ value }) {
	const key = String(value);
	return (
		<span className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-sm font-bold ${FUDGE_COLORS[key] || 'bg-surface-container-high text-on-surface-variant'}`}>
			{FUDGE_SYMBOLS[key] || value}
		</span>
	);
}

function D6Die({ value, isWild, isComplication }) {
	const base = isWild
		? (isComplication ? 'bg-red-800/80 text-red-200 ring-1 ring-red-500' : 'bg-primary/20 text-primary ring-1 ring-primary')
		: 'bg-surface-container-high text-on-surface';
	return (
		<span className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-sm font-bold ${base}`}>
			{value}{isWild && !isComplication && <span className="text-[8px] ml-0.5 text-primary">★</span>}
		</span>
	);
}

function FateRollDetails({ roll }) {
	const details = roll.details || {};
	const hasOpposition = !!details.opposition;

	return (
		<div className="space-y-2">
			{/* Dice row */}
			<div className="flex items-center gap-3">
				<div className="flex gap-1">
					{roll.dice.map((d, i) => <FudgeDie key={i} value={d} />)}
				</div>
				<span className="text-on-surface-variant text-xs">
					= {roll.total >= 0 ? '+' : ''}{roll.total}
				</span>
				{details.skill_name && (
					<span className="text-on-surface text-xs">
						+ {details.skill_name} ({details.skill_label || `+${details.skill_value}`})
					</span>
				)}
				<span className="text-on-surface font-bold text-sm">
					→ {roll.skill_total >= 0 ? '+' : ''}{roll.skill_total}
				</span>
			</div>

			{/* Opposition or difficulty */}
			<div className="text-xs text-on-surface-variant">
				{hasOpposition ? (
					<>
						vs <span className="text-on-surface">{details.opposition.npc_name || 'Opposition'}</span>
						{details.opposition_dice && (
							<span className="ml-1">
								({details.opposition_dice.map(d => d >= 0 ? `+${d}` : d).join(', ')}
								{details.opposition.skill && ` + ${details.opposition.skill} +${details.opposition.skill_value}`}
								{` = ${roll.opposition_total >= 0 ? '+' : ''}${roll.opposition_total}`})
							</span>
						)}
					</>
				) : (
					<>
						Difficulté : <span className="text-on-surface">{details.difficulty_label || details.difficulty}</span>
						{details.difficulty_label && ` (${details.difficulty >= 0 ? '+' : ''}${details.difficulty})`}
					</>
				)}
			</div>

			{/* Shifts */}
			{roll.shifts != null && (
				<div className="text-xs text-on-surface-variant">
					Marge : <span className={`font-bold ${roll.shifts >= 0 ? 'text-green-400' : 'text-red-400'}`}>
						{roll.shifts >= 0 ? '+' : ''}{roll.shifts} shift{Math.abs(roll.shifts) !== 1 ? 's' : ''}
					</span>
				</div>
			)}
		</div>
	);
}

function D6RollDetails({ roll }) {
	const details = roll.details || {};
	const regularDice = details.regular_dice || [];
	const wildDieRolls = details.wild_die_rolls || [];
	const hasExplosion = wildDieRolls.some((_, i) => i > 0);

	return (
		<div className="space-y-2">
			{/* Dice row */}
			<div className="flex items-center gap-3">
				<div className="flex gap-1">
					{regularDice.map((d, i) => <D6Die key={`r${i}`} value={d} />)}
					{wildDieRolls.map((d, i) => (
						<D6Die key={`w${i}`} value={d} isWild isComplication={roll.complication && i === 0 && d === 1} />
					))}
				</div>
				{details.pip_bonus > 0 && (
					<span className="text-on-surface-variant text-xs">+{details.pip_bonus}</span>
				)}
				<span className="text-on-surface font-bold text-sm">= {roll.total}</span>
			</div>

			{/* Skill info */}
			{details.skill_name && (
				<div className="text-xs text-on-surface-variant">
					Compétence : <span className="text-on-surface">{details.skill_name}</span>
					{details.dice_code && ` (${details.dice_code})`}
				</div>
			)}

			{/* Difficulty */}
			<div className="text-xs text-on-surface-variant">
				{details.opposition ? (
					<>
						vs <span className="text-on-surface">{details.opposition.npc_name || 'Opposition'}</span>
						{roll.opposition_total != null && ` (${roll.opposition_total})`}
					</>
				) : (
					<>
						Difficulté : <span className="text-on-surface">
							{details.difficulty_label || details.difficulty}
						</span>
						{details.difficulty_label && ` (${details.difficulty})`}
					</>
				)}
			</div>

			{/* Special events */}
			{hasExplosion && (
				<div className="text-xs text-primary font-semibold">
					Le dé sauvage explose ! ({wildDieRolls.join(' → ')})
				</div>
			)}
			{roll.complication && (
				<div className="text-xs text-red-400 font-semibold">
					Complication ! Le dé sauvage tombe sur 1 — le dé le plus haut est retiré.
				</div>
			)}

			{/* Margin */}
			{roll.shifts != null && (
				<div className="text-xs text-on-surface-variant">
					Marge : <span className={`font-bold ${roll.shifts >= 0 ? 'text-green-400' : 'text-red-400'}`}>
						{roll.shifts >= 0 ? '+' : ''}{roll.shifts}
					</span>
				</div>
			)}
		</div>
	);
}

export default function DiceRollDisplay({ roll, engine }) {
	if (!roll || !roll.outcome) return null;

	const details = roll.details || {};
	const outcomeStyle = OUTCOME_STYLES[roll.outcome] || OUTCOME_STYLES.failure;
	const outcomeLabel = OUTCOME_LABELS[roll.outcome] || roll.outcome;
	const outcomeColor = OUTCOME_COLORS[roll.outcome] || 'text-on-surface';
	const explanation = OUTCOME_EXPLANATIONS[roll.outcome] || '';

	return (
		<div className={`mb-3 rounded-lg border ${outcomeStyle} overflow-hidden`}>
			{/* Header */}
			<div className="px-4 py-2 flex items-center justify-between border-b border-outline-variant/10">
				<div className="flex items-center gap-2">
					<span className="text-sm">🎲</span>
					<span className="text-xs font-label uppercase tracking-wider text-on-surface-variant">
						{details.reason || 'Jet de compétence'}
					</span>
				</div>
				<span className={`text-sm font-bold ${outcomeColor}`}>
					{outcomeLabel}
				</span>
			</div>

			{/* Roll details */}
			<div className="px-4 py-3">
				{engine === 'fate_core' ? (
					<FateRollDetails roll={roll} />
				) : engine === 'd6' ? (
					<D6RollDetails roll={roll} />
				) : (
					<div className="text-xs text-on-surface-variant">
						Total : {roll.total} — {outcomeLabel}
					</div>
				)}
			</div>

			{/* Explanation footer */}
			{explanation && (
				<div className="px-4 py-2 border-t border-outline-variant/10 text-[11px] text-on-surface-variant/60 italic">
					{explanation}
				</div>
			)}
		</div>
	);
}
