'use client';

import { useState } from 'react';
import Button, { IconButton, DangerButton } from '../ui/Button';
import StatsBar from './StatsBar';

export default function GameHeader({
	partieName,
	gameState,
	showStats = true,
	onRename,
	onShowSettings,
	onShowState,
	onQuit
}) {
	const [isRenaming, setIsRenaming] = useState(false);
	const [newName, setNewName] = useState('');

	const handleRename = () => {
		if (newName.trim()) {
			onRename?.(newName.trim());
			setIsRenaming(false);
			setNewName('');
		}
	};

	return (
		<header className="bg-gray-800 border-b border-gray-700">
			{/* Ligne titre + actions */}
			<div className="px-4 py-3 flex items-center justify-between">
				{/* Titre */}
				<div className="flex items-center gap-2">
					{isRenaming ? (
						<div className="flex items-center gap-2">
							<input
								type="text"
								value={newName}
								onChange={(e) => setNewName(e.target.value)}
								onKeyDown={(e) => e.key === 'Enter' && handleRename()}
								placeholder={partieName}
								autoFocus
								className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
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
							<h1 className="text-lg font-semibold text-blue-400">{partieName}</h1>
							<IconButton
								onClick={() => { setIsRenaming(true); setNewName(partieName); }}
								title="Renommer"
							>
								<EditIcon className="w-3.5 h-3.5" />
							</IconButton>
						</>
					)}
				</div>

				{/* Actions */}
				<div className="flex items-center gap-2">
					<IconButton onClick={onShowSettings} title="Paramètres">
						<SettingsIcon className="w-5 h-5" />
					</IconButton>
					<Button variant="secondary" size="sm" onClick={onShowState}>
						État
					</Button>
					<DangerButton size="sm" onClick={onQuit}>
						Quitter
					</DangerButton>
				</div>
			</div>

			{/* Stats bar */}
			{showStats && gameState?.valentin && (
				<div className="px-4 pb-3">
					<StatsBar gameState={gameState} />
				</div>
			)}
		</header>
	);
}

// Icons
function EditIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
		</svg>
	);
}

function SettingsIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
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
