'use client';

/**
 * Debug State Panel (optional, toggled in settings)
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
