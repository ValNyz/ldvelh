'use client';

// ============================================================================
// DICE ROLL DISPLAY (inline in assistant messages)
// ============================================================================

const OUTCOME_STYLES = {
	success: 'bg-green-900/60 text-green-300 border-green-700/50',
	success_with_style: 'bg-emerald-900/60 text-emerald-300 border-emerald-700/50',
	tie: 'bg-yellow-900/60 text-yellow-300 border-yellow-700/50',
	failure: 'bg-red-900/60 text-red-300 border-red-700/50',
};

const OUTCOME_LABELS = {
	success: 'Réussite',
	success_with_style: 'Réussite avec style',
	tie: 'Égalité',
	failure: 'Échec',
};

// Fudge die faces: -1, 0, +1
const FUDGE_SYMBOLS = { '-1': '−', '0': '0', '1': '+' };
const FUDGE_COLORS = {
	'-1': 'bg-red-800 text-red-200',
	'0': 'bg-gray-700 text-gray-300',
	'1': 'bg-blue-800 text-blue-200',
};

function FudgeDie({ value }) {
	const key = String(value);
	return (
		<span className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold ${FUDGE_COLORS[key] || 'bg-gray-700 text-gray-300'}`}>
			{FUDGE_SYMBOLS[key] || value}
		</span>
	);
}

function D6Die({ value, isWild, isComplication }) {
	const base = isWild
		? (isComplication ? 'bg-red-800 text-red-200 ring-1 ring-red-500' : 'bg-primary/20 text-primary ring-1 ring-primary')
		: 'bg-gray-700 text-gray-200';
	return (
		<span className={`inline-flex items-center justify-center w-6 h-6 rounded text-xs font-bold ${base}`}>
			{value}
		</span>
	);
}

function OutcomeBadge({ outcome }) {
	const style = OUTCOME_STYLES[outcome] || OUTCOME_STYLES.failure;
	const label = OUTCOME_LABELS[outcome] || outcome;
	return (
		<span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${style}`}>
			{label}
		</span>
	);
}

function FateRollDisplay({ roll }) {
	const details = roll.details || {};
	return (
		<div className="flex flex-wrap items-center gap-2">
			{details.skill_name && (
				<span className="text-gray-400 text-xs">{details.skill_name}</span>
			)}
			<div className="flex gap-1">
				{roll.dice.map((d, i) => <FudgeDie key={i} value={d} />)}
			</div>
			<span className="text-gray-500 text-xs">= {roll.skill_total}</span>
			{details.difficulty != null && (
				<span className="text-gray-500 text-xs">
					vs {details.difficulty}
					{details.difficulty_label && ` (${details.difficulty_label})`}
				</span>
			)}
			{roll.shifts != null && (
				<span className="text-gray-500 text-xs">
					({roll.shifts >= 0 ? '+' : ''}{roll.shifts})
				</span>
			)}
			<OutcomeBadge outcome={roll.outcome} />
		</div>
	);
}

function D6RollDisplay({ roll }) {
	const details = roll.details || {};
	const regularDice = details.regular_dice || [];
	const wildDieRolls = details.wild_die_rolls || [];
	return (
		<div className="flex flex-wrap items-center gap-2">
			{details.skill_name && (
				<span className="text-gray-400 text-xs">
					{details.skill_name}
					{details.dice_code && ` (${details.dice_code})`}
				</span>
			)}
			<div className="flex gap-1">
				{regularDice.map((d, i) => <D6Die key={`r${i}`} value={d} />)}
				{wildDieRolls.map((d, i) => (
					<D6Die key={`w${i}`} value={d} isWild isComplication={roll.complication && i === 0 && d === 1} />
				))}
			</div>
			<span className="text-gray-500 text-xs">= {roll.total}</span>
			{details.difficulty != null && (
				<span className="text-gray-500 text-xs">vs {details.difficulty}</span>
			)}
			{roll.complication && (
				<span className="text-amber-400 text-[11px] font-semibold">Complication!</span>
			)}
			<OutcomeBadge outcome={roll.outcome} />
		</div>
	);
}

export default function DiceRollDisplay({ roll, engine }) {
	if (!roll || !roll.outcome) return null;

	return (
		<div className="mb-2 px-3 py-1.5 bg-gray-900/80 rounded-lg border border-gray-700/50 font-mono text-xs">
			{engine === 'fate_core' ? (
				<FateRollDisplay roll={roll} />
			) : engine === 'd6' ? (
				<D6RollDisplay roll={roll} />
			) : (
				<div className="flex items-center gap-2">
					<span className="text-gray-400">Roll: {roll.total}</span>
					<OutcomeBadge outcome={roll.outcome} />
				</div>
			)}
		</div>
	);
}
