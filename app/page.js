'use client';

import { useState, useEffect, useCallback } from 'react';

// Hooks
import { useGameState, useParties } from '../hooks/useGameState';
import { useStreaming } from '../hooks/useStreaming';
import { useGamePreferences } from '../hooks/useLocalStorage';
import { useTooltips } from '../hooks/useTooltips';

// Components
import PartiesList from '../components/game/PartiesList';
import GameHeader from '../components/game/GameHeader';
import SettingsPanel, { DebugStatePanel } from '../components/game/SettingsPanel';
import MessageList from '../components/game/MessageList';
import InputArea from '../components/game/InputArea';
import { ConfirmModal } from '../components/ui/Modal';

export default function Home() {
	// État du jeu
	const {
		partieId, setPartieId,
		partieName, setPartieName,
		gameState, setGameState,
		replaceGameState,
		messages, setMessages,
		loading, setLoading,
		saving, setSaving,
		error, setError,
		clearError, resetGame,
		normalizeGameState
	} = useGameState();

	// Gestion des parties
	const {
		parties, loadParties, createPartie, deletePartie, renamePartie, loadPartie
	} = useParties();

	// Préférences
	const { fontSize, increaseFontSize, decreaseFontSize } = useGamePreferences();

	// Tooltips
	const { tooltipMap, refresh: refreshTooltips } = useTooltips(partieId);

	// UI State
	const [showSettings, setShowSettings] = useState(false);
	const [showState, setShowState] = useState(false);
	const [editingIndex, setEditingIndex] = useState(null);
	const [loadingGame, setLoadingGame] = useState(false);
	const [confirmDeleteModal, setConfirmDeleteModal] = useState(false);

	// Streaming
	const { startStream, cancel: cancelStream } = useStreaming({
		onChunk: (display) => {
			setMessages(prev => {
				const newMsgs = [...prev];
				if (newMsgs.length > 0 && newMsgs[newMsgs.length - 1].streaming) {
					newMsgs[newMsgs.length - 1] = { role: 'assistant', content: display, streaming: true };
				} else {
					newMsgs.push({ role: 'assistant', content: display, streaming: true });
				}
				return newMsgs;
			});
		},
		onDone: (displayText, state) => {
			setLoading(false);
			setSaving(true);
			setMessages(prev => {
				const newMsgs = [...prev];
				if (newMsgs.length > 0) {
					newMsgs[newMsgs.length - 1] = { role: 'assistant', content: displayText };
				}
				return newMsgs;
			});
			if (state) {
				setGameState(state);
			}
		},
		onSaved: () => setSaving(false),
		onError: (msg, details) => setError({ message: msg, details, recoverable: true })
	});

	// Charger les parties au démarrage
	useEffect(() => {
		loadParties();
	}, [loadParties]);

	// Rafraîchir tooltips après un message assistant
	useEffect(() => {
		const lastMsg = messages[messages.length - 1];
		if (lastMsg?.role === 'assistant' && !lastMsg.streaming && !loading && !saving) {
			// Délai pour laisser le temps à l'extraction Haiku
			const timer = setTimeout(refreshTooltips, 1500);
			return () => clearTimeout(timer);
		}
	}, [messages, loading, saving, refreshTooltips]);

	// ============================================================
	// ACTIONS PARTIES
	// ============================================================

	const handleSelectPartie = useCallback(async (id) => {
		setLoadingGame(true);
		setError(null);
		try {
			const data = await loadPartie(id);
			setPartieId(id);
			if (data.state) {
				replaceGameState(data.state);
				setPartieName(data.state.partie?.nom || 'Partie sans nom');
			}
			setMessages(data.messages?.map(m => ({ role: m.role, content: m.content })) || []);
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoadingGame(false);
		}
	}, [loadPartie, setPartieId, setGameState, setPartieName, setMessages, setError]);

	const handleNewPartie = useCallback(async () => {
		setLoadingGame(true);
		setError(null);
		try {
			const id = await createPartie();
			setPartieId(id);
			setPartieName('Nouvelle partie');
			replaceGameState(null);
			setMessages([]);
			loadParties();
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoadingGame(false);
		}
	}, [createPartie, setPartieId, setPartieName, setGameState, setMessages, setError, loadParties]);

	const handleDeletePartie = useCallback(async (id) => {
		try {
			await deletePartie(id || partieId);
			if (id === partieId || !id) {
				resetGame();
				setShowSettings(false);
			}
			loadParties();
			setConfirmDeleteModal(false);
		} catch (e) {
			setError({ message: e.message });
		}
	}, [deletePartie, partieId, resetGame, loadParties, setError]);

	const handleRenamePartie = useCallback(async (newName) => {
		await renamePartie(partieId, newName);
		setPartieName(newName);
	}, [partieId, renamePartie, setPartieName]);

	const handleQuit = useCallback(() => {
		resetGame();
		loadParties();
	}, [resetGame, loadParties]);

	// ============================================================
	// ACTIONS MESSAGES
	// ============================================================

	const sendMessage = useCallback(async (userMessage, previousMessages, currentGameState) => {
		setLoading(true);
		setError(null);

		// Ajouter le message user
		setMessages([...previousMessages, { role: 'user', content: userMessage }]);

		await startStream('/api/chat', {
			message: userMessage,
			partieId,
			gameState: currentGameState
		});
	}, [partieId, setLoading, setError, setMessages, startStream]);

	const handleSend = useCallback((msg) => {
		if (loading || saving) return;
		sendMessage(msg, messages, gameState);
	}, [loading, saving, messages, gameState, sendMessage]);

	const handleEdit = useCallback((index) => {
		if (messages[index].role !== 'user') return;
		setEditingIndex(index);
	}, [messages]);

	const handleCancelEdit = useCallback(() => {
		setEditingIndex(null);
	}, []);

	const handleSubmitEdit = useCallback(async (content) => {
		const idx = editingIndex;
		const prevMsgs = messages.slice(0, idx);
		setEditingIndex(null);

		// Rollback côté serveur
		if (partieId) {
			try {
				const res = await fetch('/api/chat', {
					method: 'DELETE',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ partieId, fromIndex: idx })
				});
				const data = await res.json();
				if (data.state) {
					setGameState(data.state);
				}
			} catch (e) {
				console.error('Erreur rollback:', e);
			}
		}

		sendMessage(content, prevMsgs, gameState);
	}, [editingIndex, messages, partieId, gameState, setGameState, sendMessage]);

	const handleRegenerate = useCallback(async () => {
		if (loading || messages.length < 2) return;

		// Trouver le dernier message user
		let lastUserIdx = messages.length - 1;
		while (lastUserIdx >= 0 && messages[lastUserIdx].role !== 'user') lastUserIdx--;
		if (lastUserIdx < 0) return;

		const userMsg = messages[lastUserIdx].content;
		const prevMsgs = messages.slice(0, lastUserIdx);

		// Rollback
		if (partieId) {
			try {
				const res = await fetch('/api/chat', {
					method: 'DELETE',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ partieId, fromIndex: lastUserIdx })
				});
				const data = await res.json();
				if (data.state) {
					setGameState(data.state);
				}
			} catch (e) {
				console.error('Erreur rollback:', e);
			}
		}

		sendMessage(userMsg, prevMsgs, gameState);
	}, [loading, messages, partieId, gameState, setGameState, sendMessage]);

	const handleCancel = useCallback(() => {
		if (cancelStream()) {
			setLoading(false);
			setMessages(prev => {
				const newMsgs = [...prev];
				if (newMsgs.length > 0 && newMsgs[newMsgs.length - 1].streaming) {
					newMsgs[newMsgs.length - 1] = {
						...newMsgs[newMsgs.length - 1],
						streaming: false,
						content: newMsgs[newMsgs.length - 1].content + '\n\n*(Annulé)*'
					};
				}
				return newMsgs;
			});
		}
	}, [cancelStream, setLoading, setMessages]);

	// ============================================================
	// RENDU
	// ============================================================

	// Page sélection des parties
	if (!partieId) {
		return (
			<PartiesList
				parties={parties}
				loading={loadingGame}
				error={error?.message}
				onSelect={handleSelectPartie}
				onNew={handleNewPartie}
				onDelete={handleDeletePartie}
			/>
		);
	}

	// Chargement
	if (loadingGame) {
		return (
			<div className="min-h-screen bg-gray-900 flex items-center justify-center">
				<div className="text-gray-400 flex items-center gap-3">
					<svg className="animate-spin h-6 w-6" fill="none" viewBox="0 0 24 24">
						<circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
						<path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
					</svg>
					Chargement...
				</div>
			</div>
		);
	}

	// Page de jeu
	return (
		<div className="h-screen flex flex-col bg-gray-900 text-white">
			{/* Header */}
			<GameHeader
				partieName={partieName}
				gameState={gameState}
				onRename={handleRenamePartie}
				onShowSettings={() => setShowSettings(!showSettings)}
				onShowState={() => setShowState(!showState)}
				onQuit={handleQuit}
			/>

			{/* Panels */}
			<SettingsPanel
				isOpen={showSettings}
				fontSize={fontSize}
				onFontSizeChange={(delta) => delta > 0 ? increaseFontSize() : decreaseFontSize()}
				onDelete={() => setConfirmDeleteModal(true)}
				onClose={() => setShowSettings(false)}
			/>
			<DebugStatePanel isOpen={showState} gameState={gameState} />

			{/* Messages */}
			<MessageList
				messages={messages}
				loading={loading}
				saving={saving}
				error={error}
				fontSize={fontSize}
				editingIndex={editingIndex}
				onEdit={handleEdit}
				onCancelEdit={handleCancelEdit}
				onSubmitEdit={handleSubmitEdit}
				onRegenerate={handleRegenerate}
				onCancel={handleCancel}
				onClearError={clearError}
				onRetry={handleRegenerate}
				tooltipMap={tooltipMap}
			/>

			{/* Input */}
			<InputArea
				onSend={handleSend}
				disabled={loading || saving}
				fontSize={fontSize}
			/>

			{/* Modal confirmation suppression */}
			<ConfirmModal
				isOpen={confirmDeleteModal}
				onClose={() => setConfirmDeleteModal(false)}
				onConfirm={() => handleDeletePartie()}
				title="Supprimer la partie"
				message="Es-tu sûr de vouloir supprimer cette partie ? Cette action est irréversible."
				confirmText="Supprimer"
			/>
		</div>
	);
}
