'use client';

import { useState, useRef, useEffect } from 'react';

/**
 * Tooltip minimaliste pour entités du KG
 * Apparition au hover avec délai 200ms
 */
export default function EntityTooltip({ children, data, className = '' }) {
	const [isVisible, setIsVisible] = useState(false);
	const [position, setPosition] = useState({ top: 0, left: 0 });
	const triggerRef = useRef(null);
	const tooltipRef = useRef(null);
	const timeoutRef = useRef(null);

	const showTooltip = () => {
		timeoutRef.current = setTimeout(() => {
			if (triggerRef.current) {
				const rect = triggerRef.current.getBoundingClientRect();
				setPosition({
					top: rect.bottom + 8,
					left: rect.left + rect.width / 2
				});
			}
			setIsVisible(true);
		}, 200);
	};

	const hideTooltip = () => {
		if (timeoutRef.current) {
			clearTimeout(timeoutRef.current);
		}
		setIsVisible(false);
	};

	useEffect(() => {
		return () => {
			if (timeoutRef.current) clearTimeout(timeoutRef.current);
		};
	}, []);

	if (!data) {
		return <span className={className}>{children}</span>;
	}

	const { icon, nom, infos, relation } = data;

	return (
		<>
			<span
				ref={triggerRef}
				onMouseEnter={showTooltip}
				onMouseLeave={hideTooltip}
				className={`cursor-help border-b border-dotted border-blue-400/50 ${className}`}
			>
				{children}
			</span>

			{isVisible && (
				<div
					ref={tooltipRef}
					className="fixed z-50 pointer-events-none"
					style={{
						top: position.top,
						left: position.left,
						transform: 'translateX(-50%)'
					}}
				>
					<div className="bg-gray-900/95 border border-gray-700 rounded-lg px-3 py-2 shadow-xl max-w-xs">
						{/* Header : icône + nom */}
						<div className="flex items-center gap-2 text-sm font-medium text-white">
							<span>{icon}</span>
							<span>{nom}</span>
						</div>

						{/* Relation avec Valentin */}
						{relation && (
							<div className="text-xs text-blue-400 mt-1">
								{relation}
							</div>
						)}

						{/* Infos (max 3 lignes) */}
						{infos?.length > 0 && (
							<div className="mt-1.5 text-xs text-gray-400 space-y-0.5">
								{infos.map((info, i) => (
									<div key={i}>• {info}</div>
								))}
							</div>
						)}
					</div>

					{/* Flèche */}
					<div
						className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-gray-900/95 border-l border-t border-gray-700 rotate-45"
					/>
				</div>
			)}
		</>
	);
}

/**
 * HOC pour wrapper le texte en gras avec tooltips
 */
export function withEntityTooltips(text, tooltipMap) {
	if (!tooltipMap || tooltipMap.size === 0) {
		return text;
	}

	// Le parsing est fait dans le composant MarkdownContent
	return text;
}
