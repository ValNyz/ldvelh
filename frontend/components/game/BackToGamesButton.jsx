'use client';

/**
 * "Retour aux parties": back to the game list. Leaving cuts nothing: a running world
 * generation or arrival goes on and comes back when the game is reopened (#143).
 */
export default function BackToGamesButton({ onBack, className = '' }) {
	return (
		<button
			onClick={onBack}
			className={`py-2.5 px-4 whitespace-nowrap text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors ${className}`}
		>
			Retour aux parties
		</button>
	);
}
