'use client';

import { useMemo } from 'react';

// ============================================================================
// CONSTANTS
// ============================================================================

const LOCATION_LABELS = {
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
// INVENTORY SIDEBAR
// ============================================================================

export function InventorySidebar({ isOpen, onClose, inventory }) {
	// Normalize and group by location
	const byLocation = useMemo(() => {
		if (!inventory?.length) return {};

		// Normalize legacy format (strings)
		const items = typeof inventory[0] === 'string'
			? inventory.map(name => ({ name, quantity: 1, location: 'sur_soi', category: 'misc' }))
			: inventory;

		const grouped = {};
		for (const item of items) {
			const loc = item.location || 'sur_soi';
			if (!grouped[loc]) grouped[loc] = [];
			grouped[loc].push(item);
		}

		// Sort by priority order
		const order = ['sur_soi', 'sac_a_dos', 'sac', 'valise', 'appartement', 'stockage'];
		const sorted = {};
		for (const loc of order) {
			if (grouped[loc]) sorted[loc] = grouped[loc];
		}
		return sorted;
	}, [inventory]);

	return (
		<SidebarWrapper
			isOpen={isOpen}
			position="left"
			title="Inventaire"
			icon="🎒"
			onClose={onClose}
		>
			{Object.keys(byLocation).length === 0 ? (
				<p className="text-gray-500 text-sm italic text-center py-4">Inventaire vide</p>
			) : (
				<div className="space-y-4">
					{Object.entries(byLocation).map(([loc, items]) => {
						const locInfo = LOCATION_LABELS[loc] || { label: loc, icon: '📌' };
						return (
							<div key={loc}>
								<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1">
									{locInfo.icon} {locInfo.label}
								</h4>
								<div className="space-y-1">
									{items.map((item, idx) => (
										<div key={idx} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
											<div className="flex justify-between items-center">
												<span className="text-gray-200 text-sm">{item.name}</span>
												{item.quantity > 1 && (
													<span className="text-primary text-xs">x{item.quantity}</span>
												)}
											</div>
											<span className="text-xs text-gray-500">{item.category}</span>
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
// WORLD SIDEBAR
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
					<div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
				</div>
			) : (
				<div className="space-y-5">
					{/* NPCs */}
					{npcs.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">👥 Personnages ({npcs.length})</h4>
							<div className="space-y-1">
								{npcs.map((npc) => (
									<div key={npc.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{npc.name}</span>
									</div>
								))}
							</div>
						</div>
					)}

					{/* Locations */}
					{locations.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">📍 Lieux ({locations.length})</h4>
							<div className="space-y-1">
								{locations.map((loc) => (
									<div key={loc.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{loc.name}</span>
										{loc.sector && <p className="text-xs text-gray-500">{loc.sector}</p>}
									</div>
								))}
							</div>
						</div>
					)}

					{/* Quests */}
					{quests.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">📜 Quêtes ({quests.length})</h4>
							<div className="space-y-1">
								{quests.map((q) => (
									<div key={q.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<div className="flex justify-between items-center">
											<span className="text-gray-200 text-sm">{q.name}</span>
											<span className={`text-xs px-1.5 py-0.5 rounded ${q.priority === 'high' ? 'bg-orange-900/50 text-orange-400' : 'bg-primary/20 text-primary'
												}`}>
												{q.status}
											</span>
										</div>
										{q.progress > 0 && (
											<div className="mt-1 h-1 bg-gray-700 rounded-full overflow-hidden">
												<div className="h-full bg-primary rounded-full" style={{ width: `${q.progress}%` }} />
											</div>
										)}
									</div>
								))}
							</div>
						</div>
					)}

					{/* Organizations */}
					{organizations.length > 0 && (
						<div>
							<h4 className="text-xs text-gray-500 uppercase tracking-wide mb-2">🏛️ Organisations ({organizations.length})</h4>
							<div className="space-y-1">
								{organizations.map((org) => (
									<div key={org.id} className="bg-gray-800/50 rounded-lg px-3 py-2 border border-gray-700/30">
										<span className="text-gray-200 text-sm">{org.name}</span>
										{org.domain && <p className="text-xs text-gray-500">{org.domain}</p>}
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
