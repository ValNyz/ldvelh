'use client';

import { useState } from 'react';
import { IconButton } from '../ui/Button';

export default function GameHeader({
	partieName,
	gameState,
	onRename,
	onToggleInventory,
	onToggleWorld,
	onShowSettings,
	onQuit,
	activeSidebar,
	showSettings
}) {
	const [isRenaming, setIsRenaming] = useState(false);
	const [newName, setNewName] = useState('');

	const partie = gameState?.partie;

	const handleRename = () => {
		if (newName.trim()) {
			onRename?.(newName.trim());
			setIsRenaming(false);
			setNewName('');
		}
	};

	return (
		<header className="bg-gray-900/80 border-b border-gray-800/50 px-4 py-3 flex items-center justify-between backdrop-blur-sm">
			{/* Gauche: Retour + Titre */}
			<div className="flex items-center gap-3">
				<button
					onClick={onQuit}
					className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
					title="Retour à la liste"
				>
					<ChevronLeftIcon className="w-5 h-5" />
				</button>

				<div className="w-px h-8 bg-gray-700" />

				<div>
					{isRenaming ? (
						<div className="flex items-center gap-2">
							<input
								type="text"
								value={newName}
								onChange={(e) => setNewName(e.target.value)}
								onKeyDown={(e) => e.key === 'Enter' && handleRename()}
								placeholder={partieName}
								autoFocus
								className="px-2 py-1 bg-gray-800 border border-gray-600 rounded text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 w-48"
							/>
							<IconButton onClick={handleRename} title="Valider">
								<CheckIcon className="w-4 h-4 text-green-400" />
							</IconButton>
							<IconButton onClick={() => { setIsRenaming(false); setNewName(''); }} title="Annuler">
								<XIcon className="w-4 h-4 text-red-400" />
							</IconButton>
						</div>
					) : (
						<>
							<div className="flex items-center gap-2">
								<h1 className="text-white font-medium">{partieName}</h1>
								<button
									onClick={() => { setIsRenaming(true); setNewName(partieName); }}
									className="text-gray-500 hover:text-gray-300 transition-colors"
									title="Renommer"
								>
									<EditIcon className="w-3.5 h-3.5" />
								</button>
							</div>
							<p className="text-xs text-gray-500">
								Cycle {partie?.cycle_actuel || 1}
								{partie?.lieu_actuel && ` • ${partie.lieu_actuel}`}
							</p>
						</>
					)}
				</div>
			</div>

			{/* Droite: Sidebars + Settings */}
			<div className="flex items-center gap-1">
				<button
					onClick={onToggleInventory}
					className={`p-2 rounded-lg transition-colors ${activeSidebar === 'inventory'
							? 'bg-purple-600 text-white'
							: 'text-gray-400 hover:text-white hover:bg-gray-800'
						}`}
					title="Inventaire"
				>
					🎒
				</button>
				<button
					onClick={onToggleWorld}
					className={`p-2 rounded-lg transition-colors ${activeSidebar === 'world'
							? 'bg-purple-600 text-white'
							: 'text-gray-400 hover:text-white hover:bg-gray-800'
						}`}
					title="Monde"
				>
					🌍
				</button>

				<div className="w-px h-6 bg-gray-700 mx-2" />

				<button
					onClick={onShowSettings}
					className={`p-2 rounded-lg transition-colors ${showSettings
							? 'bg-gray-700 text-white'
							: 'text-gray-400 hover:text-white hover:bg-gray-800'
						}`}
					title="Paramètres"
				>
					⚙️
				</button>
			</div>
		</header>
	);
}

// Icons
function ChevronLeftIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
		</svg>
	);
}

function EditIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
		</svg>
	);
}

function CheckIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
		</svg>
	);
}

function XIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
		</svg>
	);
}
