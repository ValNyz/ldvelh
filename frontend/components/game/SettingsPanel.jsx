'use client';

import Button, { DangerButton } from '../ui/Button';

export default function SettingsPanel({
	isOpen,
	fontSize,
	onFontSizeChange,
	onDelete,
	onClose
}) {
	if (!isOpen) return null;

	return (
		<div className="bg-gray-800 border-b border-gray-700 px-4 py-4">
			<div className="flex items-center justify-between mb-4">
				<h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide">
					Paramètres
				</h3>
				<button
					onClick={onClose}
					className="text-gray-500 hover:text-white transition-colors"
				>
					<XIcon className="w-5 h-5" />
				</button>
			</div>

			<div className="space-y-4">
				{/* Taille de police */}
				<div>
					<label className="block text-sm text-gray-400 mb-2">
						Taille de police
					</label>
					<div className="flex items-center gap-3">
						<Button
							variant="secondary"
							size="sm"
							onClick={() => onFontSizeChange(-2)}
							disabled={fontSize <= 10}
							className="w-10"
						>
							−
						</Button>
						<span className="text-white font-mono w-16 text-center">
							{fontSize}px
						</span>
						<Button
							variant="secondary"
							size="sm"
							onClick={() => onFontSizeChange(2)}
							disabled={fontSize >= 24}
							className="w-10"
						>
							+
						</Button>
					</div>
				</div>

				{/* Aperçu */}
				<div className="bg-gray-900 rounded p-3">
					<p className="text-gray-400 text-xs mb-1">Aperçu :</p>
					<p style={{ fontSize }} className="text-white">
						Vous entrez dans le **bar** faiblement éclairé. *L'IA murmure sarcastiquement.*
					</p>
				</div>

				{/* Zone danger */}
				<div className="pt-4 border-t border-gray-700">
					<DangerButton onClick={onDelete}>
						<TrashIcon className="w-4 h-4 mr-2" />
						Supprimer la partie
					</DangerButton>
				</div>
			</div>
		</div>
	);
}

/**
 * Debug State Panel
 */
export function DebugStatePanel({ isOpen, gameState }) {
	if (!isOpen || !gameState) return null;

	return (
		<div className="bg-gray-900 border-b border-gray-700 px-4 py-3 max-h-48 overflow-auto">
			<pre className="text-xs text-gray-400 font-mono">
				{JSON.stringify(gameState, null, 2)}
			</pre>
		</div>
	);
}

// Icons
function XIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
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
