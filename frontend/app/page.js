'use client';

import { useState, useCallback, useEffect } from 'react';

// Hooks
import { useGameState, useParties } from '../hooks/useGameState';
import { useStreaming } from '../hooks/useStreaming';
import { useGamePreferences } from '../hooks/useLocalStorage';
import { useTooltips } from '../hooks/useTooltips';

// API
import { chatApi } from '../lib/api';

// Components
import PartiesList from '../components/game/PartiesList';
import GameHeader from '../components/game/GameHeader';
import MessageList from '../components/game/MessageList';
import InputArea from '../components/game/InputArea';
import SettingsPanel, { DebugStatePanel } from '../components/game/SettingsPanel';
import Modal from '../components/ui/Modal';

export default function Home() {
	// =========================================================================
	// STATE & HOOKS
	// =========================================================================

	const {
		partieId, setPartieId,
		partieName, setPartieName,
		gameState, setGameState, replaceGameState,
		messages, setMessages,
		loading, setLoading,
		saving, setSaving,
		error, setError, clearError,
		resetGame
	} = useGameState();

	const {
		parties, loadingList,
		loadParties, createPartie, deletePartie, renamePartie, loadPartie
	} = useParties();

	const { fontSize, setFontSize } = useGamePreferences();

	// Tooltips
	const { tooltipMap, refresh: refreshTooltips } = useTooltips(partieId);

	// UI State
	const [showSettings, setShowSettings] = useState(false);
	const [showState, setShowState] = useState(false);
	const [editingIndex, setEditingIndex] = useState(null);
	const [lastUserMessage, setLastUserMessage] = useState('');

	// Streaming
	const { startStream, cancel, isStreaming } = useStreaming({
		onChunk: (content) => {
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant' && last.streaming) {
					return [...prev.slice(0, -1), { ...last, content: last.content + content }];
				}
				return [...prev, { role: 'assistant', content, streaming: true }];
			});
		},
		onDone: (displayText, state) => {
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return [...prev.slice(0, -1), { ...last, content: displayText || last.content, streaming: false }];
				}
				return prev;
			});
			if (state) setGameState(state);
			setLoading(false);
		},
		onSaved: () => {
			setSaving(false);
			refreshTooltips(); // Rafraîchir les tooltips après sauvegarde
		},
		onError: (err, details) => {
			setError({ message: err, details, recoverable: true });
			setLoading(false);
			setSaving(false);
		}
	});

	// =========================================================================
	// EFFECTS
	// =========================================================================

	// Charger la liste des parties au mount
	useEffect(() => {
		loadParties();
	}, [loadParties]);

	// =========================================================================
	// HANDLERS
	// =========================================================================

	const handleNewGame = async () => {
		setLoading(true);
		try {
			const id = await createPartie();
			setPartieId(id);
			setPartieName('Nouvelle partie');
			setMessages([]);
			replaceGameState(null);
			await loadParties();
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoading(false);
		}
	};

	const handleLoadGame = async (id) => {
		setLoading(true);
		try {
			const data = await loadPartie(id);
			setPartieId(id);
			setPartieName(data.partie?.nom || data.name || 'Partie');
			setMessages(data.messages || []);
			replaceGameState(data.state || data);
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoading(false);
		}
	};

	const handleDeleteGame = async (id) => {
		try {
			await deletePartie(id);
			if (partieId === id) resetGame();
			await loadParties();
		} catch (e) {
			setError({ message: e.message });
		}
	};

	const handleRenameGame = async (newName) => {
		if (!partieId) return;
		await renamePartie(partieId, newName);
		setPartieName(newName);
		await loadParties();
	};

	const handleSendMessage = useCallback(async (content) => {
		if (!partieId || loading) return;

		setLastUserMessage(content);
		setMessages(prev => [...prev, { role: 'user', content }]);
		setLoading(true);
		setSaving(true);

		await startStream('/chat', {
			gameId: partieId,
			message: content
		});
	}, [partieId, loading, startStream, setMessages, setLoading, setSaving]);

	const handleCancel = useCallback(() => {
		if (cancel()) {
			setLoading(false);
			setSaving(false);
		}
	}, [cancel, setLoading, setSaving]);

	const handleEdit = useCallback((index) => {
		setEditingIndex(index);
	}, []);

	const handleCancelEdit = useCallback(() => {
		setEditingIndex(null);
	}, []);

	const handleSubmitEdit = useCallback(async (content) => {
		if (editingIndex === null) return;
		// Rollback puis renvoyer
		setMessages(prev => prev.slice(0, editingIndex));
		setEditingIndex(null);
		await handleSendMessage(content);
	}, [editingIndex, setMessages, handleSendMessage]);

	const handleRegenerate = useCallback(async () => {
		if (!lastUserMessage) return;
		// Supprimer la dernière réponse
		setMessages(prev => {
			const last = prev[prev.length - 1];
			return last?.role === 'assistant' ? prev.slice(0, -1) : prev;
		});
		await handleSendMessage(lastUserMessage);
	}, [lastUserMessage, setMessages, handleSendMessage]);

	const handleQuit = useCallback(() => {
		resetGame();
	}, [resetGame]);

	const handleRetry = useCallback(() => {
		if (lastUserMessage) {
			handleSendMessage(lastUserMessage);
		}
	}, [lastUserMessage, handleSendMessage]);

	// =========================================================================
	// RENDER
	// =========================================================================

	// Écran de sélection de partie
	if (!partieId) {
		return (
			<PartiesList
				parties={parties}
				loading={loadingList}
				error={error?.message}
				onSelect={handleLoadGame}
				onNew={handleNewGame}
				onDelete={handleDeleteGame}
			/>
		);
	}

	// Écran de jeu
	return (
		<div className="h-screen flex flex-col bg-gray-900 text-white">
			{/* Header */}
			<GameHeader
				partieName={partieName}
				gameState={gameState}
				onRename={handleRenameGame}
				onShowSettings={() => setShowSettings(!showSettings)}
				onShowState={() => setShowState(!showState)}
				onQuit={handleQuit}
			/>

			{/* Settings Panel */}
			<SettingsPanel
				isOpen={showSettings}
				fontSize={fontSize}
				onFontSizeChange={(delta) => setFontSize(prev => Math.min(24, Math.max(10, prev + delta)))}
				onDelete={() => handleDeleteGame(partieId)}
				onClose={() => setShowSettings(false)}
			/>

			{/* Debug State Panel */}
			<DebugStatePanel
				isOpen={showState}
				gameState={gameState}
			/>

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
				onRetry={handleRetry}
				tooltipMap={tooltipMap}
			/>

			{/* Input */}
			<InputArea
				onSend={handleSendMessage}
				disabled={loading}
				fontSize={fontSize}
			/>
		</div>
	);
}
