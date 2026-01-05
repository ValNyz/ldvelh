'use client';

/**
 * Affichage d'une jauge avec dots (●◐○)
 * Supporte les demi-points (ex: 2.5 affiche ●●◐○○)
 */
function StatDots({ value, max = 5, color = 'text-white' }) {
	const safeValue = Math.min(Math.max(value || 0, 0), max);
	const filled = Math.floor(safeValue);
	const hasHalf = safeValue % 1 >= 0.5;
	const empty = max - filled - (hasHalf ? 1 : 0);

	return (
		<span className={`font-mono ${color}`}>
			{'●'.repeat(filled)}
			{hasHalf && '◐'}
			<span className="text-gray-600">{'○'.repeat(Math.max(0, empty))}</span>
		</span>
	);
}

/**
 * Label + Dots pour une stat
 */
function StatItem({ label, value, max = 5, color }) {
	return (
		<div className="flex items-center gap-2">
			<span className="text-gray-400 text-xs uppercase tracking-wide">{label}</span>
			<StatDots value={value} max={max} color={color} />
		</div>
	);
}

/**
 * Barre de stats complète
 */
export default function StatsBar({ gameState }) {
	const partie = gameState?.partie;
	const valentin = gameState?.valentin;

	if (!valentin) return null;

	return (
		<div className="space-y-2 font-mono text-sm">
			{/* Ligne 1: Cycle, Date, Heure */}
			<div className="flex items-center gap-4 text-emerald-400">
				<span>Cycle {partie?.cycle_actuel || 1}</span>
				<span className="text-gray-500">|</span>
				<span>{partie?.jour || '-'} {partie?.date_jeu || ''}</span>
				{partie?.heure && (
					<>
						<span className="text-gray-500">|</span>
						<span className="flex items-center gap-1">
							<ClockIcon className="w-3.5 h-3.5" />
							{partie.heure}
						</span>
					</>
				)}
			</div>

			{/* Ligne 2: Stats Valentin */}
			<div className="flex flex-wrap items-center gap-x-6 gap-y-1">
				<StatItem label="Énergie" value={valentin.energie} color="text-yellow-400" />
				<StatItem label="Moral" value={valentin.moral} color="text-blue-400" />
				<StatItem label="Santé" value={valentin.sante} color="text-red-400" />
			</div>

			{/* Ligne 3: Crédits, Lieu, PNJ */}
			<div className="flex flex-wrap items-center gap-x-4 gap-y-1">
				<span className="text-amber-400 flex items-center gap-1">
					<CoinIcon className="w-3.5 h-3.5" />
					{valentin.credits ?? 1400} cr
				</span>

				{partie?.lieu_actuel && (
					<span className="text-blue-300 flex items-center gap-1">
						<LocationIcon className="w-3.5 h-3.5" />
						{partie.lieu_actuel}
					</span>
				)}

				{partie?.pnjs_presents?.length > 0 && (
					<span className="text-purple-400 flex items-center gap-1">
						<UsersIcon className="w-3.5 h-3.5" />
						{partie.pnjs_presents.join(', ')}
					</span>
				)}
			</div>

			{/* Ligne 4: Inventaire (si présent) */}
			{valentin.inventaire?.length > 0 && (
				<div className="text-gray-500 text-xs flex items-center gap-1">
					<BackpackIcon className="w-3.5 h-3.5" />
					{valentin.inventaire.join(', ')}
				</div>
			)}
		</div>
	);
}

// Mini icons (inline SVG pour éviter dépendances)
function ClockIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
		</svg>
	);
}

function CoinIcon({ className }) {
	return (
		<svg className={className} fill="currentColor" viewBox="0 0 20 20">
			<path d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.736 6.979C9.208 6.193 9.696 6 10 6c.304 0 .792.193 1.264.979a1 1 0 001.715-1.029C12.279 4.784 11.232 4 10 4s-2.279.784-2.979 1.95c-.285.475-.507 1-.67 1.55H6a1 1 0 000 2h.013a9.358 9.358 0 000 1H6a1 1 0 100 2h.351c.163.55.385 1.075.67 1.55C7.721 15.216 8.768 16 10 16s2.279-.784 2.979-1.95a1 1 0 10-1.715-1.029c-.472.786-.96.979-1.264.979-.304 0-.792-.193-1.264-.979a4.265 4.265 0 01-.264-.521H10a1 1 0 100-2H8.017a7.36 7.36 0 010-1H10a1 1 0 100-2H8.472a4.265 4.265 0 01.264-.521z" />
		</svg>
	);
}

function LocationIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
		</svg>
	);
}

function UsersIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
		</svg>
	);
}

function BackpackIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
		</svg>
	);
}
