'use client';

import { useState, useCallback, useEffect } from 'react';
import { preferencesApi } from '../lib/api';

const DEFAULTS = {
	fontSize: 14,
	showDebug: false,
	extractionInterval: 24,
	apiKeys: {},
	activeProvider: null,
	activeModel: null,
};

/**
 * Hook for DB-backed user preferences.
 * Loads from user object (returned at login), syncs to backend.
 */
export function usePreferences(user) {
	const [preferences, setPreferences] = useState(DEFAULTS);
	const [loading, setLoading] = useState(false);

	// Initialize from user object (contains masked preferences)
	useEffect(() => {
		if (user?.preferences) {
			const prefs = user.preferences;
			setPreferences(prev => ({
				...prev,
				fontSize: prefs.font_size ?? prev.fontSize,
				showDebug: prefs.show_debug ?? prev.showDebug,
				extractionInterval: prefs.extraction_interval_hours ?? prev.extractionInterval,
				apiKeys: prefs.api_keys ?? prev.apiKeys,
				activeProvider: prefs.active_provider ?? prev.activeProvider,
				activeModel: prefs.active_model ?? prev.activeModel,
			}));
		}
	}, [user]);

	const updatePreference = useCallback(async (key, value) => {
		setPreferences(prev => ({ ...prev, [key]: value }));

		// Map frontend key names to backend key names
		const keyMap = {
			fontSize: 'font_size',
			showDebug: 'show_debug',
			extractionInterval: 'extraction_interval_hours',
			activeProvider: 'active_provider',
			activeModel: 'active_model',
		};
		const backendKey = keyMap[key] || key;

		try {
			await preferencesApi.update({ [backendKey]: value });
		} catch (e) {
			console.error('Failed to save preference:', e);
		}
	}, []);

	const setApiKey = useCallback(async (provider, key) => {
		setLoading(true);
		try {
			const result = await preferencesApi.update({
				api_keys: { [provider]: key || null },
			});
			if (result.preferences) {
				setPreferences(prev => ({
					...prev,
					apiKeys: result.preferences.api_keys || {},
				}));
			}
		} catch (e) {
			console.error('Failed to save API key:', e);
			throw e;
		} finally {
			setLoading(false);
		}
	}, []);

	const setActiveProvider = useCallback(async (provider) => {
		setPreferences(prev => ({ ...prev, activeProvider: provider, activeModel: null }));
		try {
			await preferencesApi.update({ active_provider: provider, active_model: null });
		} catch (e) {
			console.error('Failed to save active provider:', e);
		}
	}, []);

	const setActiveModel = useCallback(async (model) => {
		setPreferences(prev => ({ ...prev, activeModel: model }));
		try {
			await preferencesApi.update({ active_model: model });
		} catch (e) {
			console.error('Failed to save active model:', e);
		}
	}, []);

	return {
		...preferences,
		loading,
		updatePreference,
		setApiKey,
		setActiveProvider,
		setActiveModel,
	};
}
