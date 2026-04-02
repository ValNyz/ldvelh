'use client';

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

	// Setter avec persistance (supports function updaters)
	const setStoredValue = useCallback((newValue) => {
		setValue(prev => {
			const resolved = typeof newValue === 'function' ? newValue(prev) : newValue;
			if (typeof window !== 'undefined') {
				try {
					localStorage.setItem(key, JSON.stringify(resolved));
				} catch (e) {
					console.warn(`Erreur écriture localStorage[${key}]:`, e);
				}
			}
			return resolved;
		});
	}, [key]);

	return [value, setStoredValue, isClient];
}

