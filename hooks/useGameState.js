import { useState, useCallback } from 'react';
import { normalizeGameState } from '../lib/game/gameState'

/**
 * Hook principal pour la gestion de l'état du jeu
 */
export function useGameState() {
	const [partieId, setPartieId] = useState(null);
	const [partieName, setPartieName] = useState('');
	const [gameState, setGameState] = useState(null);
	const [messages, setMessages] = useState([]);
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState(null);

	const updateGameState = useCallback((newState) => {
		const normalized = normalizeGameState(newState);
		if (normalized) {
			setGameState(prev => {
				if (!prev) return normalized;
				return {
					...prev,
					partie: { ...prev.partie, ...normalized.partie },
					valentin: { ...prev.valentin, ...normalized.valentin },
					ia: normalized.ia?.nom ? { ...prev.ia, ...normalized.ia } : prev.ia
				};
			});
		}
	}, []);

	const clearError = useCallback(() => setError(null), []);

	const resetGame = useCallback(() => {
		setPartieId(null);
		setPartieName('');
		setGameState(null);
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

/**
 * Hook pour les opérations API des parties
 */
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
