'use client';

import { FATE_LADDER } from '../../lib/game/engineConfig';

// ============================================================================
// CHARACTER SHEET SIDEBAR
// ============================================================================

export default function CharacterSheet({ isOpen, onClose, gameState }) {
	if (!isOpen) return null;

	const engine = gameState?.game?.engine || 'none';
	const player = gameState?.player;
	const stats = player?.engine_stats;

	return (
		<div className="w-80 bg-surface border-l border-gray-800 flex flex-col overflow-hidden">
			{/* Header */}
			<div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
				<h2 className="text-white font-medium">Fiche personnage</h2>
				<button
					onClick={onClose}
					className="text-gray-500 hover:text-white transition-colors"
				>
					✕
				</button>
			</div>

			{/* Content */}
			<div className="flex-1 overflow-y-auto p-4 space-y-4">
				{/* Credits (universal) */}
				<Section title="Crédits">
					<p className="text-amber-400 font-mono text-lg">
						{(player?.credits ?? 0).toLocaleString('fr-FR')} cr
					</p>
				</Section>

				{/* Engine-specific stats */}
				{engine === 'none' && <NoneSheet />}
				{engine === 'narrative' && <NarrativeSheet stats={stats} />}
				{engine === 'fate_core' && <FateCoreSheet stats={stats} />}
				{engine === 'd6' && <D6Sheet stats={stats} />}

				{/* Inventory */}
				{player?.inventory?.length > 0 && (
					<Section title="Inventaire">
						<div className="space-y-1">
							{player.inventory.map((item, i) => (
								<div key={i} className="flex items-center gap-2 text-sm">
									<span className="text-gray-300">{item.name || item}</span>
									{item.quantity > 1 && (
										<span className="text-gray-500 text-xs">x{item.quantity}</span>
									)}
								</div>
							))}
						</div>
					</Section>
				)}
			</div>
		</div>
	);
}

// ============================================================================
// HELPERS
// ============================================================================

function Section({ title, children }) {
	return (
		<div>
			<h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2">{title}</h3>
			{children}
		</div>
	);
}

// ============================================================================
// NONE
// ============================================================================

function NoneSheet() {
	return (
		<div className="text-center py-6 text-gray-500 text-sm">
			Mode libre — pas de statistiques mécaniques
		</div>
	);
}

// ============================================================================
// NARRATIVE
// ============================================================================

function NarrativeSheet({ stats }) {
	const traits = stats?.traits || [];
	if (traits.length === 0) return null;

	return (
		<Section title="Traits">
			<div className="space-y-2">
				{traits.map((t, i) => (
					<div
						key={i}
						className={`p-2 rounded border ${
							t.active !== false
								? 'bg-emerald-900/20 border-emerald-700/50'
								: 'bg-gray-800/50 border-gray-700/50 opacity-60'
						}`}
					>
						<p className="text-emerald-300 text-sm font-medium">{t.name}</p>
						{t.description && (
							<p className="text-gray-400 text-xs mt-0.5">{t.description}</p>
						)}
						{t.active === false && (
							<span className="text-xs text-gray-500 italic">inactif</span>
						)}
					</div>
				))}
			</div>
		</Section>
	);
}

// ============================================================================
// FATE CORE
// ============================================================================

function FateCoreSheet({ stats }) {
	if (!stats) return null;

	const aspects = stats.aspects || [];
	const stressPhys = stats.stress_physical || [];
	const stressMent = stats.stress_mental || [];
	const consequences = stats.consequences || {};
	const skills = stats.skills || [];

	return (
		<>
			{/* Fate Points */}
			<Section title="Points de Destin">
				<div className="flex items-center gap-2">
					<span className="text-primary font-mono text-lg">
						{stats.fate_points ?? 0}
					</span>
					<span className="text-gray-500 text-sm">/ {stats.refresh ?? 3} refresh</span>
				</div>
			</Section>

			{/* Aspects */}
			{aspects.length > 0 && (
				<Section title="Aspects">
					<div className="space-y-1.5">
						{aspects.map((a, i) => (
							<div key={i} className="p-2 bg-primary/10 border border-primary/30 rounded">
								<span className="text-xs text-primary uppercase">{a.type || 'aspect'}</span>
								<p className="text-gray-200 text-sm">{a.name}</p>
							</div>
						))}
					</div>
				</Section>
			)}

			{/* Stress Tracks */}
			<Section title="Stress">
				<div className="space-y-2">
					<StressTrack label="Physique" boxes={stressPhys} />
					<StressTrack label="Mental" boxes={stressMent} />
				</div>
			</Section>

			{/* Consequences */}
			{Object.values(consequences).some(Boolean) && (
				<Section title="Conséquences">
					<div className="space-y-1">
						{Object.entries(consequences).map(([level, val]) => val && (
							<div key={level} className="text-sm">
								<span className="text-orange-400 capitalize">{level}: </span>
								<span className="text-gray-300">{val}</span>
							</div>
						))}
					</div>
				</Section>
			)}

			{/* Skills */}
			{skills.length > 0 && (
				<Section title="Compétences">
					<div className="space-y-0.5">
						{[...skills].sort((a, b) => (b.level || 0) - (a.level || 0)).map((s, i) => (
							<div key={i} className="flex justify-between text-sm">
								<span className="text-gray-300">{s.name}</span>
								<span className="text-primary font-mono">
									+{s.level} {FATE_LADDER[s.level] || ''}
								</span>
							</div>
						))}
					</div>
				</Section>
			)}
		</>
	);
}

function StressTrack({ label, boxes }) {
	if (!boxes || !Array.isArray(boxes)) return null;
	return (
		<div className="flex items-center gap-2">
			<span className="text-gray-400 text-xs w-16">{label}</span>
			<div className="flex gap-1">
				{boxes.map((filled, i) => (
					<span
						key={i}
						className={`w-5 h-5 rounded border flex items-center justify-center text-xs ${
							filled
								? 'bg-red-800 border-red-600 text-red-200'
								: 'bg-gray-800 border-gray-600 text-gray-500'
						}`}
					>
						{filled ? '■' : '□'}
					</span>
				))}
			</div>
		</div>
	);
}

// ============================================================================
// D6 SYSTEM
// ============================================================================

function D6Sheet({ stats }) {
	if (!stats) return null;

	const attributes = stats.attributes || {};
	const wounds = stats.wounds || {};
	const skills = stats.skills || [];
	const woundLevels = [
		{ key: 'stunned', label: 'Étourdi' },
		{ key: 'wounded', label: 'Blessé' },
		{ key: 'severely_wounded', label: 'Gravement blessé' },
		{ key: 'incapacitated', label: 'Incapacité' },
		{ key: 'mortally_wounded', label: 'Mortellement blessé' },
	];

	return (
		<>
			{/* Force Points */}
			<Section title="Points de Force">
				<span className="text-blue-400 font-mono text-lg">
					{stats.force_points ?? 0} PF
				</span>
			</Section>

			{/* Wound Track */}
			<Section title="Blessures">
				<div className="space-y-1">
					{woundLevels.map(({ key, label }) => (
						<div key={key} className="flex items-center gap-2 text-sm">
							<span className={`w-3 h-3 rounded-full ${
								wounds[key] ? 'bg-red-500' : 'bg-gray-700'
							}`} />
							<span className={wounds[key] ? 'text-red-300' : 'text-gray-400'}>
								{label}
							</span>
						</div>
					))}
				</div>
			</Section>

			{/* Attributes */}
			<Section title="Attributs">
				<div className="space-y-1">
					{Object.entries(attributes).map(([name, val]) => (
						<div key={name} className="flex justify-between text-sm">
							<span className="text-gray-300">{name}</span>
							<span className="text-blue-400 font-mono">{val}</span>
						</div>
					))}
				</div>
			</Section>

			{/* Skills */}
			{skills.length > 0 && (
				<Section title="Compétences">
					<div className="space-y-0.5">
						{skills.map((s, i) => (
							<div key={i} className="flex justify-between text-sm">
								<span className="text-gray-300">{s.name}</span>
								<span className="text-blue-400 font-mono text-xs">{s.dice_value}</span>
							</div>
						))}
					</div>
				</Section>
			)}
		</>
	);
}
