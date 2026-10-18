'use client';

import WorldRetryActions from './WorldRetryActions';

/**
 * Reopened game whose world was never generated (failed, or left during the generation).
 * The server kept the parameters of the first __INIT__; `params` are the ones this browser
 * still holds (wizard draft), shown so the player knows what the retry uses (#88).
 */
export default function WorldPendingScreen({ params, error, onRetry, onEdit, onBack }) {
	const world = params?.worldConfig;
	const name = params?.characterData?.name?.trim();
	return (
		<div className="min-h-screen bg-surface flex flex-col items-center justify-center p-4 md:p-8">
			<div className="max-w-xl w-full space-y-6">
				<div className="text-center">
					<h1 className="text-3xl font-bold text-white mb-2">Monde à créer</h1>
					<p className="text-gray-400">
						La génération du monde de cette partie n’a pas abouti. Elle reprendra avec les
						paramètres choisis à la création.
					</p>
				</div>

				{params && (
					<div className="bg-gray-800 rounded-lg p-4 space-y-1 text-sm" data-testid="pending-params">
						<p className="text-gray-400">Paramètres enregistrés</p>
						{world?.genre && <p className="text-white">Genre : {world.genre}</p>}
						{name && <p className="text-white">Personnage : {name}</p>}
						{world?.lore && <p className="text-gray-300 italic line-clamp-3">{world.lore}</p>}
					</div>
				)}

				{error && (
					<div className="bg-red-900/50 border border-red-700 rounded-lg p-4">
						<p className="text-red-400">{error}</p>
					</div>
				)}

				<WorldRetryActions onRetry={onRetry} onEdit={onEdit} onBack={onBack} />
			</div>
		</div>
	);
}
