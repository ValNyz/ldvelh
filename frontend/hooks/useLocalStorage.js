import { useState, useEffect, useCallback } from 'react';

/**
 * Hook pour la persistance localStorage avec SSR safety
 */
export function useLocalStorage(key, defaultValue) {
	const [isClient, setIsClient] = useState(false);
	const [value, setValue] = useState(defaultValue);

	// Hydratation côté client
	useEffect(() => {
		setIsClient(true);
		try {
			const stored = localStorage.getItem(key);
			if (stored !== null) {
				setValue(JSON.parse(stored));
			}
		} catch (e) {
			console.warn(`Erreur lecture localStorage[${key}]:`, e);
		}
	}, [key]);

	// Setter avec persistance
	const setStoredValue = useCallback((newValue) => {
		setValue(newValue);
		if (typeof window !== 'undefined') {
			try {
				localStorage.setItem(key, JSON.stringify(newValue));
			} catch (e) {
				console.warn(`Erreur écriture localStorage[${key}]:`, e);
			}
		}
	}, [key]);

	return [value, setStoredValue, isClient];
}

/**
 * Hook spécialisé pour les préférences du jeu
 */
export function useGamePreferences() {
	const [fontSize, setFontSize] = useLocalStorage('ldvelh-fontsize', 14);
	const [showDebug, setShowDebug] = useLocalStorage('ldvelh-debug', false);

	const increaseFontSize = useCallback(() => {
		setFontSize(prev => Math.min(24, prev + 2));
	}, [setFontSize]);

	const decreaseFontSize = useCallback(() => {
		setFontSize(prev => Math.max(10, prev - 2));
	}, [setFontSize]);

	return {
		fontSize,
		setFontSize,
		increaseFontSize,
		decreaseFontSize,
		showDebug,
		setShowDebug
	};
}
