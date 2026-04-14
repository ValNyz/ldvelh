'use client';

import { useState, useMemo } from 'react';

const OUTCOME_LABELS = {
	failure: 'Echec',
	tie: 'Egalite',
	success: 'Reussite',
	success_with_style: 'Reussite avec style',
};

const FUDGE_SYMBOLS = { '-1': '-', '0': '0', '1': '+' };

function FudgeDie({ value }) {
	const symbol = FUDGE_SYMBOLS[String(value)] || '?';
	const color = value > 0 ? 'text-green-400' : value < 0 ? 'text-red-400' : 'text-gray-400';
	return (
		<span className={`inline-flex items-center justify-center w-7 h-7 rounded bg-gray-800 border border-gray-600 font-bold text-sm ${color}`}>
			{symbol}
		</span>
	);
}

export default function AspectInvocationModal({
	invocationData,
	onInvoke,
	onSkip,
}) {
	const { roll, aspects, fatePoints } = invocationData;
	const [selected, setSelected] = useState([]);

	const toggle = (aspectName) => {
		setSelected(prev =>
			prev.includes(aspectName)
				? prev.filter(n => n !== aspectName)
				: prev.length < fatePoints
					? [...prev, aspectName]
					: prev
		);
	};

	const previewBonus = selected.length * 2;
	const previewTotal = roll.skill_total + previewBonus;
	const difficulty = roll.details?.difficulty ?? 0;
	const previewShifts = previewTotal - difficulty;
	const previewOutcome = useMemo(() => {
		if (previewShifts < 0) return 'failure';
		if (previewShifts === 0) return 'tie';
		if (previewShifts >= 3) return 'success_with_style';
		return 'success';
	}, [previewShifts]);

	const outcomeColor = {
		failure: 'text-red-400',
		tie: 'text-yellow-400',
		success: 'text-green-400',
		success_with_style: 'text-emerald-300',
	};

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
			<div className="bg-surface border border-gray-700 rounded-xl shadow-2xl max-w-md w-full mx-4 p-6 space-y-5">
				{/* Header */}
				<div className="text-center">
					<h3 className="text-lg font-semibold text-white">Invoquer un aspect ?</h3>
					<p className="text-sm text-gray-400 mt-1">
						Votre jet a echoue. Vous pouvez invoquer des aspects pour ajouter +2 chacun.
					</p>
				</div>

				{/* Current roll display */}
				<div className="bg-gray-800 rounded-lg p-3 space-y-2">
					<div className="flex items-center justify-between text-sm">
						<span className="text-gray-400">
							{roll.details?.skill_name || '?'} ({roll.details?.skill_label || '?'})
						</span>
						<span className="text-red-400 font-medium">
							{OUTCOME_LABELS.failure}
						</span>
					</div>
					<div className="flex items-center gap-1.5">
						{roll.dice?.map((d, i) => <FudgeDie key={i} value={d} />)}
						<span className="text-gray-500 mx-1">=</span>
						<span className="text-white font-medium">{roll.skill_total}</span>
						<span className="text-gray-500 mx-1">vs</span>
						<span className="text-gray-300">{difficulty} ({roll.details?.difficulty_label || '?'})</span>
					</div>
					<div className="text-xs text-gray-500">
						Ecart : {roll.shifts >= 0 ? '+' : ''}{roll.shifts}
					</div>
				</div>

				{/* Aspect selection */}
				<div className="space-y-2">
					<div className="flex items-center justify-between text-sm">
						<span className="text-gray-300">Aspects disponibles</span>
						<span className="text-primary">
							{fatePoints - selected.length} PD restant{fatePoints - selected.length !== 1 ? 's' : ''}
						</span>
					</div>
					<div className="space-y-1.5 max-h-48 overflow-y-auto">
						{aspects.map((aspect, i) => {
							const name = typeof aspect === 'string' ? aspect : aspect.name;
							const type = typeof aspect === 'object' ? aspect.type : null;
							const isSelected = selected.includes(name);
							const canSelect = isSelected || selected.length < fatePoints;

							return (
								<button
									key={i}
									onClick={() => toggle(name)}
									disabled={!canSelect}
									className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
										isSelected
											? 'bg-primary/15 border border-primary text-white'
											: canSelect
												? 'bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700'
												: 'bg-gray-800/50 border border-gray-700/50 text-gray-600 cursor-not-allowed'
									}`}
								>
									<span className="font-medium">{name}</span>
									{type && (
										<span className="ml-2 text-xs text-gray-500">({type})</span>
									)}
									{isSelected && (
										<span className="float-right text-primary">+2</span>
									)}
								</button>
							);
						})}
					</div>
				</div>

				{/* Preview */}
				{selected.length > 0 && (
					<div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
						<div className="text-xs text-gray-400 mb-1">Apres invocation :</div>
						<div className="flex items-center gap-2 text-sm">
							<span className="text-white">{roll.skill_total}</span>
							<span className="text-primary">+{previewBonus}</span>
							<span className="text-gray-500">=</span>
							<span className="text-white font-medium">{previewTotal}</span>
							<span className="text-gray-500">vs</span>
							<span className="text-gray-300">{difficulty}</span>
							<span className="text-gray-500">→</span>
							<span className={`font-medium ${outcomeColor[previewOutcome]}`}>
								{OUTCOME_LABELS[previewOutcome]}
							</span>
							<span className="text-gray-500 text-xs">({previewShifts >= 0 ? '+' : ''}{previewShifts})</span>
						</div>
					</div>
				)}

				{/* Actions */}
				<div className="flex gap-3">
					<button
						onClick={onSkip}
						className="flex-1 px-4 py-2.5 text-gray-400 hover:text-white border border-gray-700 hover:border-gray-600 rounded-lg text-sm transition-colors"
					>
						Accepter l'echec
					</button>
					<button
						onClick={() => onInvoke(selected)}
						disabled={selected.length === 0}
						className="flex-1 px-4 py-2.5 bg-primary hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
					>
						{selected.length > 0
							? `Invoquer (${selected.length} PD)`
							: 'Choisir un aspect'}
					</button>
				</div>
			</div>
		</div>
	);
}
