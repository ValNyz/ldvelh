'use client';

// ============================================================================
// ENGINE-POLYMORPHIC STATS (compact inline for StatsBar)
// ============================================================================

function StressTrack({ label, icon, boxes }) {
	if (!boxes || !Array.isArray(boxes)) return null;
	return (
		<div className="flex items-center gap-1">
			<span className="text-gray-500">{icon}</span>
			<span className="font-mono text-xs">
				{boxes.map((filled, i) => (
					<span key={i} className={filled ? 'text-red-400' : 'text-gray-600'}>
						{filled ? '■' : '□'}
					</span>
				))}
			</span>
			<span className="text-gray-600 text-[10px]">{label}</span>
		</div>
	);
}

function FateCoreStats({ stats }) {
	if (!stats) return null;

	const consequences = stats.consequences || {};
	const activeConsequences = Object.values(consequences).filter(Boolean).length;

	return (
		<>
			<StressTrack label="phys" icon="💪" boxes={stats.stress_physical} />
			<StressTrack label="ment" icon="🧠" boxes={stats.stress_mental} />

			{activeConsequences > 0 && (
				<span className="text-orange-400 text-xs">
					⚠ {activeConsequences} cons.
				</span>
			)}

			<span className="text-purple-400 flex items-center gap-1 text-xs">
				✦ {stats.fate_points ?? 0}/{stats.refresh ?? 3} PD
			</span>
		</>
	);
}

function D6Stats({ stats }) {
	if (!stats) return null;

	const wounds = stats.wounds || {};
	const woundLevels = ['stunned', 'wounded', 'incapacitated', 'mortally_wounded'];
	const activeWounds = woundLevels.filter(w => wounds[w]).length;

	return (
		<>
			{activeWounds > 0 ? (
				<span className="text-red-400 text-xs">
					🩹 {activeWounds} bless.
				</span>
			) : (
				<span className="text-green-400 text-xs">
					🩹 indemne
				</span>
			)}

			<span className="text-blue-400 flex items-center gap-1 text-xs">
				⚡ {stats.force_points ?? 0} PF
			</span>
		</>
	);
}

function NarrativeStats({ stats }) {
	if (!stats) return null;

	const traits = stats.traits || [];
	const activeTraits = traits.filter(t => t.active !== false).length;

	if (activeTraits === 0) return null;

	return (
		<span className="text-emerald-400 text-xs">
			🏷 {activeTraits} trait{activeTraits > 1 ? 's' : ''}
		</span>
	);
}

export default function EngineStats({ engine, engineStats }) {
	if (!engine || engine === 'none') return null;

	switch (engine) {
		case 'fate_core':
			return <FateCoreStats stats={engineStats} />;
		case 'd6':
			return <D6Stats stats={engineStats} />;
		case 'narrative':
			return <NarrativeStats stats={engineStats} />;
		default:
			return null;
	}
}
