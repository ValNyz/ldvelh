'use client';

import { useState, useEffect, useCallback } from 'react';

/**
 * Hook pour charger les données tooltip d'une partie
 * Retourne une Map nom/alias → données formatées pour tooltip
 */
export function useTooltips(partieId) {
	const [tooltipMap, setTooltipMap] = useState(new Map());
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState(null);

	const fetchTooltips = useCallback(async () => {
		if (!partieId) return;

		setIsLoading(true);
		setError(null);

		try {
			const response = await fetch(`/api/tooltips?partieId=${partieId}`);

			if (!response.ok) {
				throw new Error('Erreur chargement tooltips');
			}

			const data = await response.json();

			// Reconstruire la Map depuis le JSON
			const map = new Map();
			for (const [key, value] of Object.entries(data.tooltips || {})) {
				map.set(key, value);
			}

			setTooltipMap(map);
		} catch (err) {
			console.error('[useTooltips] Erreur:', err);
			setError(err.message);
		} finally {
			setIsLoading(false);
		}
	}, [partieId]);

	// Charger au mount et quand partieId change
	useEffect(() => {
		fetchTooltips();
	}, [fetchTooltips]);

	// Fonction pour rafraîchir manuellement
	const refresh = useCallback(() => {
		fetchTooltips();
	}, [fetchTooltips]);

	return { tooltipMap, isLoading, error, refresh };
}

/**
 * Hook simplifié si les données sont déjà côté serveur
 * Utilise les données passées en props plutôt qu'un fetch
 */
export function useTooltipsFromData(tooltipsData) {
	const [tooltipMap, setTooltipMap] = useState(new Map());

	useEffect(() => {
		if (!tooltipsData) {
			setTooltipMap(new Map());
			return;
		}

		const map = new Map();

		for (const entity of tooltipsData) {
			// Clé principale : nom
			map.set(entity.entite_nom.toLowerCase(), entity);

			// Clés secondaires : alias
			if (entity.alias?.length > 0) {
				for (const alias of entity.alias) {
					map.set(alias.toLowerCase(), entity);
				}
			}
		}

		setTooltipMap(map);
	}, [tooltipsData]);

	return tooltipMap;
}
