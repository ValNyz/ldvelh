'use client';

import Button from '../ui/Button';

export default function SettingsPanel({
	isOpen,
	fontSize,
	onFontSizeChange,
	onDelete,
	onClose
}) {
	if (!isOpen) return null;

	return (
		<div className="bg-gray-900/90 border-b border-gray-800/50 px-4 py-3 flex items-center justify-between">
			<div className="flex items-center gap-6">
				{/* Taille de police */}
				<div className="flex items-center gap-2">
					<span className="text-gray-400 text-xs">Police</span>
					<button
						onClick={() => onFontSizeChange(-2)}
						disabled={fontSize <= 10}
						className="px-2 py-1 bg-gray-800 rounded text-gray-300 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
					>
						−
					</button>
					<span className="text-white text-sm w-12 text-center font-mono">{fontSize}px</span>
					<button
						onClick={() => onFontSizeChange(2)}
						disabled={fontSize >= 24}
						className="px-2 py-1 bg-gray-800 rounded text-gray-300 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
					>
						+
					</button>
				</div>

				{/* Supprimer */}
				<button
					onClick={onDelete}
					className="text-red-400 text-xs hover:text-red-300 flex items-center gap-1 transition-colors"
				>
					🗑️ Supprimer partie
				</button>
			</div>

			{/* Fermer */}
			<button
				onClick={onClose}
				className="text-gray-500 hover:text-white transition-colors"
			>
				✕
			</button>
		</div>
	);
}

/**
 * Debug State Panel (optionnel)
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
