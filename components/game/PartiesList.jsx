'use client';

import { useState } from 'react';
import Button, { DangerButton } from '../ui/Button';

/**
 * Page de sélection des parties
 */
export default function PartiesList({
	parties,
	loading,
	error,
	onSelect,
	onNew,
	onDelete
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

	const handleDelete = (id) => {
		onDelete(id);
		setConfirmDelete(null);
	};

	return (
		<div className="min-h-screen bg-gray-900 text-white p-6">
			<div className="max-w-xl mx-auto">
				{/* Header */}
				<div className="mb-8">
					<h1 className="text-3xl font-bold text-blue-400 mb-2">LDVELH</h1>
					<p className="text-gray-400">Chroniques de l'Exil Stellaire</p>
				</div>

				{/* Nouvelle partie */}
				<Button
					onClick={onNew}
					disabled={loading}
					loading={loading}
					className="w-full mb-6"
					size="lg"
				>
					+ Nouvelle partie
				</Button>

				{/* Erreur */}
				{error && (
					<div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-6 text-red-400">
						{error}
					</div>
				)}

				{/* Liste des parties */}
				<h2 className="text-lg font-medium text-gray-300 mb-4">
					Parties existantes
				</h2>

				{parties.length === 0 ? (
					<div className="text-center py-12 text-gray-500">
						<GamepadIcon className="w-12 h-12 mx-auto mb-3 opacity-50" />
						<p>Aucune partie sauvegardée</p>
						<p className="text-sm mt-1">Crée une nouvelle partie pour commencer</p>
					</div>
				) : (
					<div className="space-y-3">
						{parties.map((partie) => (
							<div
								key={partie.id}
								className="bg-gray-800 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
							>
								<div className="flex items-center p-4">
									{/* Infos partie (cliquable) */}
									<div
										className="flex-1 cursor-pointer"
										onClick={() => onSelect(partie.id)}
									>
										<h3 className="font-medium text-white mb-1">
											{partie.nom}
										</h3>
										<div className="flex items-center gap-3 text-sm text-gray-400">
											<span className="flex items-center gap-1">
												<CycleIcon className="w-4 h-4" />
												Cycle {partie.cycle_actuel || 1}
											</span>
											<span>•</span>
											<span>{formatDate(partie.updated_at)}</span>
										</div>
									</div>

									{/* Bouton supprimer */}
									{confirmDelete === partie.id ? (
										<div className="flex items-center gap-2">
											<Button
												variant="danger"
												size="sm"
												onClick={() => handleDelete(partie.id)}
											>
												Confirmer
											</Button>
											<Button
												variant="secondary"
												size="sm"
												onClick={() => setConfirmDelete(null)}
											>
												Annuler
											</Button>
										</div>
									) : (
										<button
											onClick={(e) => {
												e.stopPropagation();
												setConfirmDelete(partie.id);
											}}
											className="p-2 text-gray-500 hover:text-red-400 hover:bg-gray-700 rounded transition-colors"
											title="Supprimer"
										>
											<TrashIcon className="w-4 h-4" />
										</button>
									)}
								</div>
							</div>
						))}
					</div>
				)}
			</div>
		</div>
	);
}

// Icons
function GamepadIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
		</svg>
	);
}

function CycleIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
		</svg>
	);
}

function TrashIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
		</svg>
	);
}
