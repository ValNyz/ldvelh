'use client';

import EngineStats from './EngineStats';

// ============================================================================
// COMPACT STATS BAR
// ============================================================================

export default function StatsBar({ gameState }) {
	const game = gameState?.game;
	const player = gameState?.player;

	if (!game && !player) return null;

	return (
		<div className="bg-gray-900/50 border-b border-gray-800/30 px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono">
			{/* Date & Time */}
			<span className="text-emerald-400 flex items-center gap-1">
				📅 {game?.game_date || '-'}
				{game?.time && ` • ${game.time}`}
			</span>

			{/* Engine-specific stats */}
			<EngineStats engine={game?.engine} engineStats={player?.engine_stats} />

			{/* Credits */}
			<span className="text-amber-400 flex items-center gap-1">
				💰 {(player?.credits ?? 0).toLocaleString('fr-FR')} cr
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
