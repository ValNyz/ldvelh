'use client';

import { useMemo } from 'react';

// ============================================================================
// CONSTANTES
// ============================================================================

const LABELS_LOCALISATION = {
	'sur_soi': { label: 'Sur soi', icon: '📍' },
	'sac_a_dos': { label: 'Sac à dos', icon: '🎒' },
	'sac': { label: 'Sac', icon: '🎒' },
	'valise': { label: 'Valise', icon: '🧳' },
	'appartement': { label: 'Appartement', icon: '🏠' },
	'stockage': { label: 'Stockage', icon: '📦' }
};

// ============================================================================
// SIDEBAR WRAPPER
// ============================================================================

function SidebarWrapper({ isOpen, position, title, icon, onClose, children }) {
	const positionClasses = position === 'left'
		? 'border-r'
		: 'border-l';

	return (
		<div className={`${isOpen ? 'w-72' : 'w-0'} transition-all duration-300 overflow-hidden ${positionClasses} border-gray-800/50 bg-gray-900/30`}>
			<div className="w-72 h-full flex flex-col">
				<div className="p-4 border-b border-gray-800/50 flex items-center justify-between">
					<h3 className="text-white font-medium flex items-center gap-2">
						{icon} {title}
					</h3>
					<button
						onClick={onClose}
						className="text-gray-500 hover:text-white transition-colors"
					>
						✕
					</button>
				</div>
				<div className="flex-1 overflow-auto p-4">
					{children}
				</div>
			</div>
		</div>
	);
}

// ============================================================================
// INVENTAIRE SIDEBAR
// ============================================================================

export function InventorySidebar({ isOpen, onClose, inventaire }) {
	// Normaliser et grouper par localisation
	const parLocalisation = useMemo(() => {
		if (!inventaire?.length) return {};

		// Normaliser si ancien format (strings)
		const items = typeof inventaire[0] === 'string'
			? inventaire.map(nom => ({ nom, quantite: 1, localisation: 'sur_soi', categorie: 'autre' }))
			: inventaire;

		const grouped = {};
		for (const item of items) {
			const loc = item.localisation || 'sur_soi';
			if (!grouped[loc]) grouped[loc] = [];
			grouped[loc].push(item);
		}

		// Trier par ordre de priorité
		const ordre = ['sur_soi', 'sac_a_dos', 'sac', 'valise', 'appartement', 'stockage'];
		const sorted = {};
		for (const loc of ordre) {
			if (grouped[loc]) sorted[loc] = grouped[loc];
		}
		return sorted;
	}, [inventaire]);

	return (
		<SidebarWrapper
			isOpen={isOpen}
			position="left"
			title="Inventaire"
			icon="🎒"
			onClose={onClose}
		>
			{Object.keys(parLocalisation).length === 0 ? (
				<p className="text-gray-500 text-sm italic text-center py-4">Inventaire vide</p>
			) : (
				<div className="space-y-4">
					{Object.entries(parLocalisation).map(([loc, items]) => {
						const locInfo = LABELS_LOCALISATION[loc] || { label: loc, icon: '📌' };
						return (
							<div key={loc}>
								<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1">
									{locInfo.icon} {locInfo.label}
								</h4>
								<div className="space-y-1">
									{items.map((item, idx) => (
										<div key={idx} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
											<div className="flex justify-between items-center">
												<span className="text-gray-200 text-sm">{item.nom}</span>
												{item.quantite > 1 && (
													<span className="text-purple-400 text-xs">x{item.quantite}</span>
												)}
											</div>
											<span className="text-xs text-gray-500">{item.categorie}</span>
										</div>
									))}
								</div>
							</div>
						);
					})}
				</div>
			)}
		</SidebarWrapper>
	);
}

// ============================================================================
// MONDE SIDEBAR
// ============================================================================

export function WorldSidebar({ isOpen, onClose, worldData, loading }) {
	const { npcs = [], locations = [], quests = [], organizations = [] } = worldData || {};

	return (
		<SidebarWrapper
			isOpen={isOpen}
			position="right"
			title="Monde"
			icon="🌍"
			onClose={onClose}
		>
			{loading ? (
				<div className="flex items-center justify-center py-8">
					<div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
				</div>
			) : (
				<div className="space-y-5">
					{/* PNJs */}
					{npcs.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">👥 Personnages ({npcs.length})</h4>
							<div className="space-y-1">
								{npcs.map((npc) => (
									<div key={npc.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{npc.nom}</span>
									</div>
								))}
							</div>
						</div>
					)}

					{/* Lieux */}
					{locations.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">📍 Lieux ({locations.length})</h4>
							<div className="space-y-1">
								{locations.map((loc) => (
									<div key={loc.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{loc.nom}</span>
										{loc.secteur && <p className="text-xs text-gray-500">{loc.secteur}</p>}
									</div>
								))}
							</div>
						</div>
					)}

					{/* Quêtes */}
					{quests.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">📜 Quêtes ({quests.length})</h4>
							<div className="space-y-1">
								{quests.map((q) => (
									<div key={q.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<div className="flex justify-between items-center">
											<span className="text-gray-200 text-sm">{q.nom}</span>
											<span className={`text-xs px-1.5 py-0.5 rounded ${q.priorite === 'haute' ? 'bg-orange-900/50 text-orange-400' : 'bg-purple-900/50 text-purple-400'
												}`}>
												{q.statut}
											</span>
										</div>
										{q.progression > 0 && (
											<div className="mt-1 h-1 bg-gray-700 rounded-full overflow-hidden">
												<div className="h-full bg-purple-500 rounded-full" style={{ width: `${q.progression}%` }} />
											</div>
										)}
									</div>
								))}
							</div>
						</div>
					)}

					{/* Organisations */}
					{organizations.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">🏛️ Organisations ({organizations.length})</h4>
							<div className="space-y-1">
								{organizations.map((org) => (
									<div key={org.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{org.nom}</span>
										{org.domaine && <p className="text-xs text-gray-500">{org.domaine}</p>}
									</div>
								))}
							</div>
						</div>
					)}

					{npcs.length === 0 && locations.length === 0 && quests.length === 0 && organizations.length === 0 && (
						<p className="text-gray-500 text-sm italic text-center py-4">Aucune donnée</p>
					)}
				</div>
			)}
		</SidebarWrapper>
	);
}
