'use client';

import { useState, useEffect, useCallback } from 'react';
import { tooltipsApi } from '../lib/api';

/**
 * Hook pour charger les données tooltip d'une partie
 * Retourne un objet nom/alias → données formatées pour tooltip
 */
export function useTooltips(partieId) {
	const [tooltipMap, setTooltipMap] = useState({});
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState(null);

	const fetchTooltips = useCallback(async () => {
		if (!partieId) return;

		setIsLoading(true);
		setError(null);

		try {
			const data = await tooltipsApi.get(partieId);
			// L'API retourne { tooltips: { nom: {...}, ... } }
			setTooltipMap(data.tooltips || {});
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
	const [tooltipMap, setTooltipMap] = useState({});

	useEffect(() => {
		if (!tooltipsData) {
			setTooltipMap({});
			return;
		}

		// Si c'est déjà un objet indexé
		if (!Array.isArray(tooltipsData)) {
			setTooltipMap(tooltipsData);
			return;
		}

		// Si c'est un tableau, construire l'index
		const map = {};

		for (const entity of tooltipsData) {
			// Clé principale : nom
			map[entity.entite_nom.toLowerCase()] = entity;

			// Clés secondaires : alias
			if (entity.alias?.length > 0) {
				for (const alias of entity.alias) {
					map[alias.toLowerCase()] = entity;
				}
			}
		}

		setTooltipMap(map);
	}, [tooltipsData]);

	return tooltipMap;
}
