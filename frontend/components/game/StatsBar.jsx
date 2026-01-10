'use client';

import { useState, useMemo } from 'react';

// ============================================================================
// CONSTANTES
// ============================================================================

const LABELS_LOCALISATION = {
	'sur_soi': { label: 'Sur soi', icon: '📍' },
	'sac_a_dos': { label: 'Sac à dos', icon: '🎒' },
	'sac': { label: 'Sac', icon: '🎒' },
	'valise': { label: 'Valise', icon: '🧳' },
	'appartement': { label: 'Appartement', icon: '🏠' },
	'bureau': { label: 'Bureau', icon: '💼' },
	'stockage': { label: 'Stockage', icon: '📦' },
	'prete': { label: 'Prêté', icon: '🤝' }
};

const ETATS_EMOJI = {
	'neuf': '',
	'bon': '',
	'use': '⚠️',
	'endommage': '🔧',
	'casse': '❌'
};

// ============================================================================
// COMPOSANTS UTILITAIRES
// ============================================================================

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

function StatItem({ label, value, max = 5, color }) {
	return (
		<div className="flex items-center gap-2">
			<span className="text-gray-400 text-xs uppercase tracking-wide">{label}</span>
			<StatDots value={value} max={max} color={color} />
		</div>
	);
}

// ============================================================================
// INVENTAIRE PANEL
// ============================================================================

function InventairePanel({ inventaire, isOpen, onClose }) {
	// Grouper par localisation
	const parLocalisation = useMemo(() => {
		if (!inventaire?.length) return {};

		const grouped = {};
		for (const item of inventaire) {
			const loc = item.localisation || 'sur_soi';
			if (!grouped[loc]) grouped[loc] = [];
			grouped[loc].push(item);
		}

		// Trier par ordre de priorité
		const ordre = ['sur_soi', 'sac_a_dos', 'sac', 'valise', 'appartement', 'bureau', 'stockage', 'prete'];
		const sorted = {};
		for (const loc of ordre) {
			if (grouped[loc]) sorted[loc] = grouped[loc];
		}
		// Ajouter les localisations inconnues
		for (const loc of Object.keys(grouped)) {
			if (!sorted[loc]) sorted[loc] = grouped[loc];
		}
		return sorted;
	}, [inventaire]);

	// Calculer valeur totale
	const valeurTotale = useMemo(() => {
		if (!inventaire?.length) return 0;
		return inventaire.reduce((sum, item) => {
			return sum + (item.valeur_neuve || 0) * (item.quantite || 1);
		}, 0);
	}, [inventaire]);

	if (!isOpen) return null;

	return (
		<div className="absolute top-full left-0 right-0 bg-gray-800 border-t border-gray-700 shadow-lg z-50 max-h-80 overflow-y-auto">
			<div className="p-4">
				<div className="flex justify-between items-center mb-3">
					<h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
						<BackpackIcon className="w-4 h-4" />
						Inventaire
					</h3>
					<button onClick={onClose} className="text-gray-500 hover:text-gray-300">
						<XIcon className="w-4 h-4" />
					</button>
				</div>

				{Object.keys(parLocalisation).length === 0 ? (
					<p className="text-gray-500 text-sm italic">Inventaire vide</p>
				) : (
					<div className="space-y-4">
						{Object.entries(parLocalisation).map(([loc, items]) => {
							const locInfo = LABELS_LOCALISATION[loc] || { label: loc, icon: '📌' };
							return (
								<div key={loc}>
									<h4 className="text-xs font-medium text-gray-400 mb-1 flex items-center gap-1">
										<span>{locInfo.icon}</span>
										{locInfo.label}
									</h4>
									<div className="space-y-1 pl-4">
										{items.map((item, idx) => (
											<InventaireItem key={item.id || idx} item={item} />
										))}
									</div>
								</div>
							);
						})}
					</div>
				)}

				{valeurTotale > 0 && (
					<div className="mt-3 pt-3 border-t border-gray-700 text-xs text-gray-500">
						💰 Valeur estimée: ~{valeurTotale} cr
					</div>
				)}
			</div>
		</div>
	);
}

function InventaireItem({ item }) {
	const etatEmoji = ETATS_EMOJI[item.etat] || '';
	const showEtat = item.etat && !['neuf', 'bon'].includes(item.etat);

	return (
		<div className="text-sm text-gray-300 flex items-center gap-2">
			<span className="text-gray-500">•</span>
			<span>{item.nom}</span>
			{item.quantite > 1 && (
				<span className="text-gray-500 text-xs">(x{item.quantite})</span>
			)}
			{showEtat && (
				<span className="text-xs text-yellow-500" title={item.etat}>
					{etatEmoji}{item.etat}
				</span>
			)}
			{item.prete_a && (
				<span className="text-xs text-purple-400">
					→ {item.prete_a}
				</span>
			)}
		</div>
	);
}

// ============================================================================
// INVENTAIRE RÉSUMÉ (COMPACT)
// ============================================================================

function InventaireSummary({ inventaire, onClick }) {
	const summary = useMemo(() => {
		if (!inventaire?.length) return null;

		// Compter les objets par localisation
		const surSoi = inventaire.filter(i => i.localisation === 'sur_soi');
		const ailleurs = inventaire.filter(i => i.localisation !== 'sur_soi');

		// Afficher jusqu'à 3 objets "sur soi"
		const preview = surSoi.slice(0, 3).map(i => i.nom);
		const reste = inventaire.length - preview.length;

		return { preview, reste, total: inventaire.length };
	}, [inventaire]);

	if (!summary) return null;

	return (
		<button
			onClick={onClick}
			className="text-gray-500 text-xs flex items-center gap-1 hover:text-gray-300 transition-colors cursor-pointer"
		>
			<BackpackIcon className="w-3.5 h-3.5" />
			{summary.preview.join(', ')}
			{summary.reste > 0 && (
				<span className="text-gray-600">+{summary.reste}</span>
			)}
			<ChevronDownIcon className="w-3 h-3 text-gray-600" />
		</button>
	);
}

// ============================================================================
// STATS BAR PRINCIPAL
// ============================================================================

export default function StatsBar({ gameState }) {
	const [showInventaire, setShowInventaire] = useState(false);

	const partie = gameState?.partie;
	const valentin = gameState?.valentin;

	if (!valentin) return null;

	// Normaliser l'inventaire (supporte ancien et nouveau format)
	const inventaire = useMemo(() => {
		if (!valentin.inventaire?.length) return [];
		// Si c'est un tableau de strings (ancien format)
		if (typeof valentin.inventaire[0] === 'string') {
			return valentin.inventaire.map(nom => ({
				nom,
				quantite: 1,
				localisation: 'sur_soi',
				categorie: 'autre',
				etat: 'bon'
			}));
		}
		return valentin.inventaire;
	}, [valentin.inventaire]);

	return (
		<div className="relative space-y-2 font-mono text-sm">
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

			{/* Ligne 4: Inventaire (cliquable) */}
			{inventaire.length > 0 && (
				<InventaireSummary
					inventaire={inventaire}
					onClick={() => setShowInventaire(!showInventaire)}
				/>
			)}

			{/* Panel inventaire détaillé */}
			<InventairePanel
				inventaire={inventaire}
				isOpen={showInventaire}
				onClose={() => setShowInventaire(false)}
			/>
		</div>
	);
}

// ============================================================================
// ICONS
// ============================================================================

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

function XIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
		</svg>
	);
}

function ChevronDownIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
		</svg>
	);
}
