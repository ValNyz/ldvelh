import { useState, useCallback } from 'react';
import { normalizeGameState } from '../lib/game/gameState.js';
import { gamesApi, stateApi } from '../lib/api.js';

// ============================================================================
// HOOK PRINCIPAL
// ============================================================================

export function useGameState() {
	const [partieId, setPartieId] = useState(null);
	const [partieName, setPartieName] = useState('');
	const [gameState, setGameStateRaw] = useState(null);
	const [messages, setMessages] = useState([]);
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState(null);

	/**
	 * Met à jour le gameState avec fusion intelligente
	 * Utilisé après chaque réponse du serveur
	 */
	const updateGameState = useCallback((newState) => {
		const normalized = normalizeGameState(newState);
		if (!normalized) return;

		setGameStateRaw(prev => {
			if (!prev) return normalized;

			// Fusion intelligente
			return {
				partie: { ...prev.partie, ...normalized.partie },
				valentin: mergeValentin(prev.valentin, normalized.valentin),
				ia: normalized.ia?.nom ? { ...prev.ia, ...normalized.ia } : prev.ia,
				monde_cree: normalized.monde_cree ?? prev.monde_cree ?? false
			};
		});
	}, []);

	/**
	 * Remplace complètement le gameState (pour le chargement initial)
	 * Évite la fusion avec un ancien state
	 */
	const replaceGameState = useCallback((newState) => {
		const normalized = normalizeGameState(newState);
		setGameStateRaw(normalized);
	}, []);

	const clearError = useCallback(() => setError(null), []);

	const resetGame = useCallback(() => {
		setPartieId(null);
		setPartieName('');
		setGameStateRaw(null);
		setMessages([]);
		setError(null);
	}, []);

	return {
		// State
		partieId,
		partieName,
		gameState,
		messages,
		loading,
		saving,
		error,

		// Setters
		setPartieId,
		setPartieName,
		setGameState: updateGameState,
		replaceGameState,
		setMessages,
		setLoading,
		setSaving,
		setError,

		// Actions
		clearError,
		resetGame,
		normalizeGameState
	};
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Fusionne les données de Valentin de manière intelligente
 * L'inventaire est toujours remplacé (source de vérité = BDD)
 */
function mergeValentin(prev, next) {
	if (!prev) return next;
	if (!next) return prev;

	return {
		energie: next.energie ?? prev.energie,
		moral: next.moral ?? prev.moral,
		sante: next.sante ?? prev.sante,
		credits: next.credits ?? prev.credits,
		inventaire: next.inventaire !== undefined ? next.inventaire : (prev.inventaire || [])
	};
}

// ============================================================================
// HOOK PARTIES - Gestion des parties
// ============================================================================

export function useParties() {
	const [parties, setParties] = useState([]);
	const [loadingList, setLoadingList] = useState(false);

	/** Liste les parties */
	const loadParties = useCallback(async () => {
		setLoadingList(true);
		try {
			const data = await gamesApi.list();
			setParties(data.parties || []);
		} catch (e) {
			console.error('Erreur chargement parties:', e);
		} finally {
			setLoadingList(false);
		}
	}, []);

	/** Crée une nouvelle partie */
	const createPartie = useCallback(async () => {
		const data = await gamesApi.create();
		if (data.error) throw new Error(data.error);
		return data.gameId;
	}, []);

	/** Supprime une partie */
	const deletePartie = useCallback(async (id) => {
		await gamesApi.delete(id);
		return true;
	}, []);

	/** Renomme une partie */
	const renamePartie = useCallback(async (id, newName) => {
		await gamesApi.rename(id, newName);
	}, []);

	/** Charge une partie (state + messages + world_info) */
	const loadPartie = useCallback(async (id) => {
		const data = await stateApi.load(id);
		if (data.error) throw new Error(data.error);
		return data;
	}, []);

	return {
		parties,
		loadingList,
		loadParties,
		createPartie,
		deletePartie,
		renamePartie,
		loadPartie
	};
}
