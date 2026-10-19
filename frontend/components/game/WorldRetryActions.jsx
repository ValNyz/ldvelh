'use client';

import BackToGamesButton from './BackToGamesButton';

/** A world generation that did not finish: retry it, edit its parameters first, or leave (#88). */
export default function WorldRetryActions({ onRetry, onEdit, onBack }) {
	return (
		<div className="space-y-3">
			<button
				onClick={onRetry}
				className="w-full py-3 px-4 bg-primary hover:brightness-110 text-white font-semibold rounded-lg transition-colors"
			>
				Réessayer
			</button>
			<div className="flex flex-col sm:flex-row gap-3">
				{onEdit && (
					<button
						onClick={onEdit}
						className="flex-1 py-2.5 px-4 whitespace-nowrap bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
					>
						Modifier les paramètres
					</button>
				)}
				<BackToGamesButton onBack={onBack} className="flex-1" />
			</div>
		</div>
	);
}
