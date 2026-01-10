'use client';

import { useState, useRef, useEffect, useCallback } from 'react';

// ============================================================================
// CONFIGURATION
// ============================================================================

const ENTITY_COLORS = {
	personnage: { bg: 'bg-purple-500/20', border: 'border-purple-500/50', text: 'text-purple-300' },
	lieu: { bg: 'bg-blue-500/20', border: 'border-blue-500/50', text: 'text-blue-300' },
	organisation: { bg: 'bg-amber-500/20', border: 'border-amber-500/50', text: 'text-amber-300' },
	objet: { bg: 'bg-emerald-500/20', border: 'border-emerald-500/50', text: 'text-emerald-300' },
	ia: { bg: 'bg-cyan-500/20', border: 'border-cyan-500/50', text: 'text-cyan-300' },
	default: { bg: 'bg-gray-500/20', border: 'border-gray-500/50', text: 'text-gray-300' }
};

const INFO_ICONS = {
	// Personnages
	metier: '💼',
	physique: '👤',
	apparence: '👤',
	espece: '🧬',
	age: '🎂',
	domicile: '🏠',
	hobby: '🎮',
	traits: '✨',
	voix: '🗣️',
	occupation: '💼',

	// Lieux
	type_lieu: '📍',
	ambiance: '🎭',
	horaires: '🕐',
	caracteristiques: '📝',
	population: '👥',

	// Organisations
	domaine: '🏢',
	type_org: '🏛️',

	// Défaut
	default: '•'
};

const TYPE_LABELS = {
	personnage: 'Personnage',
	lieu: 'Lieu',
	organisation: 'Organisation',
	objet: 'Objet',
	ia: 'IA'
};

// ============================================================================
// COMPOSANT PRINCIPAL
// ============================================================================

export default function EntityTooltip({ children, data, className = '' }) {
	const [isVisible, setIsVisible] = useState(false);
	const [position, setPosition] = useState({ top: 0, left: 0, placement: 'bottom' });
	const triggerRef = useRef(null);
	const tooltipRef = useRef(null);
	const showTimeoutRef = useRef(null);
	const hideTimeoutRef = useRef(null);

	// Calculer la position optimale du tooltip
	const calculatePosition = useCallback(() => {
		if (!triggerRef.current || !tooltipRef.current) return;

		const triggerRect = triggerRef.current.getBoundingClientRect();
		const tooltipRect = tooltipRef.current.getBoundingClientRect();
		const padding = 12;
		const arrowSize = 8;

		const viewportWidth = window.innerWidth;
		const viewportHeight = window.innerHeight;

		let top, left, placement = 'bottom';

		// Position verticale : préférer en bas, sinon en haut
		const spaceBelow = viewportHeight - triggerRect.bottom;
		const spaceAbove = triggerRect.top;

		if (spaceBelow >= tooltipRect.height + padding + arrowSize) {
			top = triggerRect.bottom + arrowSize;
			placement = 'bottom';
		} else if (spaceAbove >= tooltipRect.height + padding + arrowSize) {
			top = triggerRect.top - tooltipRect.height - arrowSize;
			placement = 'top';
		} else {
			top = Math.max(padding, (viewportHeight - tooltipRect.height) / 2);
			placement = 'center';
		}

		// Position horizontale : centrer, mais rester dans l'écran
		left = triggerRect.left + (triggerRect.width / 2) - (tooltipRect.width / 2);

		if (left < padding) {
			left = padding;
		}
		if (left + tooltipRect.width > viewportWidth - padding) {
			left = viewportWidth - tooltipRect.width - padding;
		}

		setPosition({ top, left, placement });
	}, []);

	// Annuler le timer de fermeture
	const cancelHide = useCallback(() => {
		if (hideTimeoutRef.current) {
			clearTimeout(hideTimeoutRef.current);
			hideTimeoutRef.current = null;
		}
	}, []);

	// Afficher avec délai
	const showTooltip = useCallback(() => {
		cancelHide();
		showTimeoutRef.current = setTimeout(() => {
			setIsVisible(true);
		}, 200);
	}, [cancelHide]);

	// Masquer avec délai (permet de bouger la souris vers le tooltip)
	const hideTooltip = useCallback(() => {
		if (showTimeoutRef.current) {
			clearTimeout(showTimeoutRef.current);
			showTimeoutRef.current = null;
		}
		hideTimeoutRef.current = setTimeout(() => {
			setIsVisible(false);
		}, 300); // Délai pour permettre le déplacement vers le tooltip
	}, []);

	// Quand la souris entre sur le tooltip, annuler la fermeture
	const handleTooltipMouseEnter = useCallback(() => {
		cancelHide();
	}, [cancelHide]);

	// Quand la souris quitte le tooltip, fermer
	const handleTooltipMouseLeave = useCallback(() => {
		hideTooltip();
	}, [hideTooltip]);

	// Recalculer la position après le rendu
	useEffect(() => {
		if (isVisible) {
			// Attendre que le tooltip soit rendu
			requestAnimationFrame(calculatePosition);
		}
	}, [isVisible, calculatePosition]);

	// Recalculer au scroll/resize
	useEffect(() => {
		if (!isVisible) return;

		const handleUpdate = () => calculatePosition();
		window.addEventListener('scroll', handleUpdate, true);
		window.addEventListener('resize', handleUpdate);

		return () => {
			window.removeEventListener('scroll', handleUpdate, true);
			window.removeEventListener('resize', handleUpdate);
		};
	}, [isVisible, calculatePosition]);

	useEffect(() => {
		return () => {
			if (showTimeoutRef.current) clearTimeout(showTimeoutRef.current);
			if (hideTimeoutRef.current) clearTimeout(hideTimeoutRef.current);
		};
	}, []);

	if (!data) {
		return <span className={className}>{children}</span>;
	}

	// Extraire les données formatées
	const formatted = data.formatted || data;
	const { icon, nom, type, infos, relation } = formatted;

	if (!nom && !infos?.length) {
		return <span className={className}>{children}</span>;
	}

	const colors = ENTITY_COLORS[type] || ENTITY_COLORS.default;
	const typeLabel = TYPE_LABELS[type] || type;

	return (
		<>
			<span
				ref={triggerRef}
				onMouseEnter={showTooltip}
				onMouseLeave={hideTooltip}
				className={`cursor-help border-b border-dotted border-blue-400/50 hover:border-blue-400 transition-colors ${className}`}
			>
				{children}
			</span>

			{isVisible && (
				<div
					ref={tooltipRef}
					onMouseEnter={handleTooltipMouseEnter}
					onMouseLeave={handleTooltipMouseLeave}
					className="fixed z-50 animate-in fade-in duration-150"
					style={{
						top: position.top,
						left: position.left,
					}}
				>
					<div className={`bg-gray-900/98 backdrop-blur-sm border ${colors.border} rounded-xl shadow-2xl min-w-[200px] max-w-[320px] overflow-hidden`}>

						{/* Header avec couleur selon type */}
						<div className={`${colors.bg} px-3 py-2 border-b ${colors.border}`}>
							<div className="flex items-center gap-2">
								<span className="text-lg">{icon}</span>
								<div className="flex-1 min-w-0">
									<div className="font-semibold text-white truncate">{nom}</div>
									<div className={`text-xs ${colors.text} opacity-80`}>{typeLabel}</div>
								</div>
							</div>
						</div>

						{/* Contenu */}
						<div className="px-3 py-2 space-y-2">

							{/* Relation avec Valentin */}
							{relation && (
								<div className="flex items-center gap-2 text-sm">
									<span className="text-blue-400">🤝</span>
									<span className="text-blue-300">{relation}</span>
								</div>
							)}

							{/* Infos groupées */}
							{infos?.length > 0 && (
								<div className="space-y-1.5 max-h-[200px] overflow-y-auto pr-1 custom-scrollbar">
									{infos.map((info, i) => (
										<InfoLine key={i} info={info} />
									))}
								</div>
							)}

							{/* Message si pas d'infos */}
							{(!infos || infos.length === 0) && !relation && (
								<div className="text-xs text-gray-500 italic py-1">
									Aucune information connue
								</div>
							)}
						</div>
					</div>

					{/* Flèche (seulement si placement haut/bas) */}
					{position.placement === 'bottom' && (
						<div
							className={`absolute -top-[5px] w-2.5 h-2.5 bg-gray-900/98 border-l border-t ${colors.border} rotate-45`}
							style={{ left: 'calc(50% - 5px)' }}
						/>
					)}
					{position.placement === 'top' && (
						<div
							className={`absolute -bottom-[5px] w-2.5 h-2.5 bg-gray-900/98 border-r border-b ${colors.border} rotate-45`}
							style={{ left: 'calc(50% - 5px)' }}
						/>
					)}
				</div>
			)}
		</>
	);
}

// ============================================================================
// COMPOSANT INFO LINE
// ============================================================================

function InfoLine({ info }) {
	// Parser "Label: valeur" pour extraire la clé
	const colonIndex = info.indexOf(':');
	if (colonIndex === -1) {
		return (
			<div className="text-sm text-gray-300 leading-snug">
				<span className="text-gray-500 mr-1.5">•</span>
				{info}
			</div>
		);
	}

	const label = info.slice(0, colonIndex).trim();
	const value = info.slice(colonIndex + 1).trim();

	// Trouver l'icône correspondante
	const labelLower = label.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
	const icon = INFO_ICONS[labelLower] || INFO_ICONS.default;

	return (
		<div className="text-sm leading-snug">
			<div className="flex items-start gap-1.5">
				<span className="text-base leading-none mt-0.5 flex-shrink-0">{icon}</span>
				<div className="flex-1 min-w-0">
					<span className="text-gray-500 text-xs uppercase tracking-wide">{label}</span>
					<div className="text-gray-200 break-words">{value}</div>
				</div>
			</div>
		</div>
	);
}

// ============================================================================
// EXPORT HELPER
// ============================================================================

export function withEntityTooltips(text, tooltipMap) {
	if (!tooltipMap || tooltipMap.size === 0) {
		return text;
	}
	return text;
}
