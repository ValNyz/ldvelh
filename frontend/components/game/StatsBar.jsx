'use client';

// ============================================================================
// STATS BAR COMPACTE
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
	const partie = gameState?.partie;
	const valentin = gameState?.valentin;

	if (!valentin) return null;

	return (
		<div className="bg-gray-900/50 border-b border-gray-800/30 px-4 py-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono">
			{/* Date & Heure */}
			<span className="text-emerald-400 flex items-center gap-1">
				📅 {partie?.date_jeu || '-'}
				{partie?.heure && ` • ${partie.heure}`}
			</span>

			{/* Stats avec dots */}
			<div className="flex items-center gap-1">
				<span className="text-gray-500">⚡</span>
				<StatDots value={valentin.energie} color="text-yellow-400" />
			</div>
			<div className="flex items-center gap-1">
				<span className="text-gray-500">💭</span>
				<StatDots value={valentin.moral} color="text-blue-400" />
			</div>
			<div className="flex items-center gap-1">
				<span className="text-gray-500">❤️</span>
				<StatDots value={valentin.sante} color="text-red-400" />
			</div>

			{/* Crédits */}
			<span className="text-amber-400 flex items-center gap-1">
				💰 {(valentin.credits ?? 0).toLocaleString('fr-FR')} cr
			</span>

			{/* Lieu (si espace) */}
			{partie?.lieu_actuel && (
				<span className="text-blue-300 flex items-center gap-1 hidden sm:flex">
					📍 {partie.lieu_actuel}
				</span>
			)}

			{/* PNJs présents */}
			{partie?.pnjs_presents?.length > 0 && (
				<span className="text-purple-400 flex items-center gap-1 hidden md:flex">
					👥 {partie.pnjs_presents.join(', ')}
				</span>
			)}
		</div>
	);
}
