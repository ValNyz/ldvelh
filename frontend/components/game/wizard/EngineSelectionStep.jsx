'use client';

import { ENGINES } from '../../../lib/game/engineConfig';

const COLOR_MAP = {
	gray: 'border-gray-600 hover:border-gray-400 bg-gray-800/50',
	emerald: 'border-emerald-700 hover:border-emerald-500 bg-emerald-900/20',
	purple: 'border-purple-700 hover:border-purple-500 bg-purple-900/20',
	blue: 'border-blue-700 hover:border-blue-500 bg-blue-900/20',
};

const SELECTED_MAP = {
	gray: 'border-gray-400 bg-gray-800 ring-2 ring-gray-400/30',
	emerald: 'border-emerald-500 bg-emerald-900/40 ring-2 ring-emerald-500/30',
	purple: 'border-purple-500 bg-purple-900/40 ring-2 ring-purple-500/30',
	blue: 'border-blue-500 bg-blue-900/40 ring-2 ring-blue-500/30',
};

export default function EngineSelectionStep({ value, onChange }) {
	return (
		<div className="space-y-4">
			<h2 className="text-xl font-semibold text-white">Choisis ton moteur de jeu</h2>
			<p className="text-gray-400 text-sm">
				Le moteur détermine comment les tests et la progression fonctionnent.
			</p>
			<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{ENGINES.map((eng) => {
					const selected = value === eng.id;
					return (
						<button
							key={eng.id}
							onClick={() => onChange(eng.id)}
							className={`text-left p-4 rounded-lg border-2 transition-all ${
								selected ? SELECTED_MAP[eng.color] : COLOR_MAP[eng.color]
							}`}
						>
							<div className="flex items-center gap-3 mb-2">
								<span className="text-2xl">{eng.icon}</span>
								<span className="text-white font-medium">{eng.name}</span>
							</div>
							<p className="text-gray-400 text-sm">{eng.description}</p>
						</button>
					);
				})}
			</div>
		</div>
	);
}
