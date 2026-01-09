import { useState, useCallback } from 'react';
import { normalizeGameState } from '../lib/js/game/gameState.js';

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
				ia: normalized.ia?.nom ? { ...prev.ia, ...normalized.ia } : prev.ia
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
		// FIX: L'inventaire vient de la BDD, utilise le nouveau s'il est défini (même si vide)
		// Avant: next.inventaire?.length ? next.inventaire : prev.inventaire
		inventaire: next.inventaire !== undefined ? next.inventaire : (prev.inventaire || [])
	};
}

// ============================================================================
// HOOK PARTIES
// ============================================================================

export function useParties() {
	const [parties, setParties] = useState([]);
	const [loadingList, setLoadingList] = useState(false);

	const loadParties = useCallback(async () => {
		setLoadingList(true);
		try {
			const res = await fetch('/api/chat?action=list');
			const data = await res.json();
			setParties(data.parties || []);
		} catch (e) {
			console.error('Erreur chargement parties:', e);
		} finally {
			setLoadingList(false);
		}
	}, []);

	const createPartie = useCallback(async () => {
		const res = await fetch('/api/chat?action=new');
		const data = await res.json();
		if (data.error) throw new Error(data.error);
		return data.partieId;
	}, []);

	const deletePartie = useCallback(async (id) => {
		const res = await fetch(`/api/chat?action=delete&partieId=${id}`);
		const data = await res.json();
		if (data.error) throw new Error(data.error);
		return true;
	}, []);

	const renamePartie = useCallback(async (id, newName) => {
		await fetch(`/api/chat?action=rename&partieId=${id}&name=${encodeURIComponent(newName)}`);
	}, []);

	const loadPartie = useCallback(async (id) => {
		const res = await fetch(`/api/chat?action=load&partieId=${id}`);
		const data = await res.json();
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
