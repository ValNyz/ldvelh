'use client';

// ============================================================================
// COMPACT STATS BAR
// ============================================================================

function StatDots({ value, max = 5, color = 'text-white' }) {
	const safeValue = Math.min(Math.max(value || 0, 0), max);
	const filled = Math.floor(safeValue);

	return (
		<span className={`font-mono text-xs ${color}`}>
			{'●'.repeat(filled)}
			<span className="text-gray-600">{'○'.repeat(Math.max(0, max - filled))}</span>
		</span>
	);
}

export default function StatsBar({ gameState }) {
	const game = gameState?.game;
	const player = gameState?.player;

	if (!player) return null;

	return (
		<div className="bg-gray-900/50 border-b border-gray-800/30 px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono">
			{/* Date & Time */}
			<span className="text-emerald-400 flex items-center gap-1">
				📅 {game?.game_date || '-'}
				{game?.time && ` • ${game.time}`}
			</span>

			{/* Stats with dots */}
			<div className="flex items-center gap-1">
				<span className="text-gray-500">⚡</span>
				<StatDots value={player.energy} color="text-yellow-400" />
			</div>
			<div className="flex items-center gap-1">
				<span className="text-gray-500">💭</span>
				<StatDots value={player.morale} color="text-blue-400" />
			</div>
			<div className="flex items-center gap-1">
				<span className="text-gray-500">❤️</span>
				<StatDots value={player.health} color="text-red-400" />
			</div>

			{/* Credits */}
			<span className="text-amber-400 flex items-center gap-1">
				💰 {(player.credits ?? 0).toLocaleString('fr-FR')} cr
			</span>

			{/* Location */}
			{game?.current_location && (
				<span className="text-blue-300 flex items-center gap-1 hidden sm:flex">
					📍 {game.current_location}
				</span>
			)}

			{/* NPCs present */}
			{game?.npcs_present?.length > 0 && (
				<span className="text-purple-400 flex items-center gap-1 hidden md:flex">
					👥 {game.npcs_present.join(', ')}
				</span>
			)}
		</div>
	);
}
