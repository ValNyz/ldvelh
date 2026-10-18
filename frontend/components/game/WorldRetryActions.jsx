'use client';

/** A world generation that did not finish: retry it, edit its parameters first, or leave (#88). */
export default function WorldRetryActions({ onRetry, onEdit, onBack }) {
	return (
		<div className="flex flex-col sm:flex-row gap-3">
			<button
				onClick={onRetry}
				className="flex-1 py-3 px-4 bg-primary hover:brightness-110 text-white font-semibold rounded-lg transition-colors"
			>
				Réessayer
			</button>
			{onEdit && (
				<button
					onClick={onEdit}
					className="flex-1 py-3 px-4 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
				>
					Modifier les paramètres
				</button>
			)}
			<button
				onClick={onBack}
				className="flex-1 py-3 px-4 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
			>
				Retour aux parties
			</button>
		</div>
	);
}
