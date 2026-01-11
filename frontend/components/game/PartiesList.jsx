'use client';

import { useState } from 'react';
import Button from '../ui/Button';

export default function PartiesList({
	parties,
	loading,
	error,
	onSelect,
	onNew,
	onDelete,
	onSettings
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
		<div className="min-h-screen bg-gray-950 text-white flex flex-col">
			{/* Header */}
			<header className="bg-gray-900/80 border-b border-gray-800/50 px-6 py-4 flex items-center justify-between">
				<div className="flex items-center gap-3">
					<span className="text-2xl">🚀</span>
					<div>
						<h1 className="text-lg font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
							LDVELH
						</h1>
						<p className="text-xs text-gray-500">Chroniques de l'Exil Stellaire</p>
					</div>
				</div>
				{onSettings && (
					<button
						onClick={onSettings}
						className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
					>
						⚙️
					</button>
				)}
			</header>

			{/* Contenu */}
			<div className="flex-1 overflow-auto">
				<div className="max-w-2xl mx-auto p-6">
					{/* Nouvelle partie */}
					<button
						onClick={onNew}
						disabled={loading}
						className="w-full mb-6 px-6 py-4 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 rounded-xl text-white font-medium transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-purple-500/25 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
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

					{/* Erreur */}
					{error && (
						<div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-6 text-red-400">
							{error}
						</div>
					)}

					{/* Liste des parties */}
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
							{parties.map((partie) => (
								<div
									key={partie.id}
									onClick={() => onSelect(partie.id)}
									className="group bg-gray-900/80 border border-gray-800 rounded-xl p-4 hover:border-purple-500/50 hover:bg-gray-900 transition-all cursor-pointer"
								>
									<div className="flex justify-between items-start">
										<div>
											<h3 className="text-white font-medium group-hover:text-purple-400 transition-colors">
												{partie.nom}
											</h3>
											<div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
												<span className="flex items-center gap-1">
													🔄 Cycle {partie.cycle_actuel || 1}
												</span>
												{partie.lieu_actuel && (
													<span className="flex items-center gap-1">
														📍 {partie.lieu_actuel}
													</span>
												)}
												<span>{formatDate(partie.updated_at)}</span>
											</div>
										</div>

										{/* Bouton supprimer */}
										{confirmDelete === partie.id ? (
											<div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
												<button
													onClick={(e) => handleDelete(e, partie.id)}
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
												onClick={(e) => { e.stopPropagation(); setConfirmDelete(partie.id); }}
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
			<footer className="bg-gray-900/80 border-t border-gray-800/50 px-6 py-3 flex items-center justify-between text-xs text-gray-500">
				<span>v0.1.0 • Made with 💜</span>
				<div className="flex items-center gap-4">
					<a href="#" className="hover:text-purple-400 transition-colors">À propos</a>
					<a href="https://github.com/ValNyz/ldvelh" target="_blank" rel="noopener noreferrer" className="hover:text-purple-400 transition-colors">GitHub</a>
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
