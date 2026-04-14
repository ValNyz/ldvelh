'use client';

import { useState } from 'react';

export default function GamesList({
	parties,
	loading,
	error,
	onSelect,
	onNew,
	onDelete,
	onSettings,
	onLogout
}) {
	const [confirmDelete, setConfirmDelete] = useState(null);

	const formatDate = (d) => {
		if (!d) return '';
		return new Date(d).toLocaleDateString('fr-FR', {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	};

	const handleDelete = (e, id) => {
		e.stopPropagation();
		onDelete(id);
		setConfirmDelete(null);
	};

	return (
		<div className="min-h-screen bg-surface-container-lowest text-white flex flex-col">
			{/* Header */}
			<header className="bg-surface/80 border-b border-gray-800/50 px-6 py-4 flex items-center justify-between">
				<div className="flex items-center gap-3">
					<span className="text-2xl">🚀</span>
					<div>
						<h1 className="text-lg font-bold text-primary">
							LDVELH
						</h1>
						<p className="text-xs text-gray-500">Chroniques de l'Exil Stellaire</p>
					</div>
				</div>
				<div className="flex items-center gap-2">
				{onSettings && (
					<button
						onClick={onSettings}
						className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
					>
						⚙️
					</button>
				)}
				{onLogout && (
					<button
						onClick={onLogout}
						className="px-3 py-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors text-sm"
					>
						Deconnexion
					</button>
				)}
			</div>
			</header>

			{/* Content */}
			<div className="flex-1 overflow-auto">
				<div className="max-w-2xl mx-auto p-6">
					{/* New game */}
					<div className="mb-6">
						<button
							onClick={() => onNew()}
							disabled={loading}
							className="w-full px-6 py-4 bg-primary hover:brightness-110 rounded-xl text-white font-medium transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-primary/25 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
						>
							{loading ? (
								<>
									<LoadingIcon className="w-5 h-5 animate-spin" />
									Création...
								</>
							) : (
								<>
									<span className="text-xl">✨</span>
									Nouvelle aventure
								</>
							)}
						</button>
					</div>

					{/* Error */}
					{error && (
						<div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-6 text-red-400">
							{error}
						</div>
					)}

					{/* Games list */}
					<h2 className="text-sm text-gray-500 uppercase tracking-wider mb-4">
						Parties sauvegardées
					</h2>

					{parties.length === 0 ? (
						<div className="text-center py-12 text-gray-500">
							<span className="text-4xl block mb-3">🎮</span>
							<p>Aucune partie sauvegardée</p>
							<p className="text-sm mt-1">Crée une nouvelle aventure pour commencer</p>
						</div>
					) : (
						<div className="space-y-3">
							{parties.map((game) => (
								<div
									key={game.id}
									onClick={() => onSelect(game.id)}
									className="group bg-surface/80 border border-gray-800 rounded-xl p-4 hover:border-primary/50 hover:bg-surface transition-all cursor-pointer"
								>
									<div className="flex justify-between items-start">
										<div>
											<h3 className="text-white font-medium group-hover:text-primary transition-colors">
												{game.name}
											</h3>
											<div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
												<span className="flex items-center gap-1">
													🔄 Cycle {game.current_cycle || 1}
												</span>
												{game.current_location && (
													<span className="flex items-center gap-1">
														📍 {game.current_location}
													</span>
												)}
												<span>{formatDate(game.updated_at)}</span>
											</div>
										</div>

										{/* Delete button */}
										{confirmDelete === game.id ? (
											<div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
												<button
													onClick={(e) => handleDelete(e, game.id)}
													className="px-2 py-1 bg-red-600 hover:bg-red-500 text-white text-xs rounded transition-colors"
												>
													Confirmer
												</button>
												<button
													onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }}
													className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded transition-colors"
												>
													Annuler
												</button>
											</div>
										) : (
											<button
												onClick={(e) => { e.stopPropagation(); setConfirmDelete(game.id); }}
												className="p-2 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all rounded hover:bg-red-500/10"
												title="Supprimer"
											>
												🗑️
											</button>
										)}
									</div>
								</div>
							))}
						</div>
					)}
				</div>
			</div>

			{/* Footer */}
			<footer className="bg-surface/80 border-t border-gray-800/50 px-6 py-3 flex items-center justify-between text-xs text-gray-500">
				<span>v0.1.0 • Made with 💜</span>
				<div className="flex items-center gap-4">
					<a href="#" className="hover:text-primary transition-colors">À propos</a>
					<a href="https://github.com/ValNyz/ldvelh" target="_blank" rel="noopener noreferrer" className="hover:text-primary transition-colors">GitHub</a>
				</div>
			</footer>
		</div>
	);
}

function LoadingIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
		</svg>
	);
}
