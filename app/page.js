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
import WorldGenerationScreen from '../components/game/WorldGenerationScreen';
import { ConfirmModal } from '../components/ui/Modal';

// ============================================================================
// PHASES DU JEU
// ============================================================================
const GAME_PHASE = {
	LIST: 'list',                    // Liste des parties
	GENERATING_WORLD: 'generating',  // Génération du monde en cours
	WORLD_READY: 'world_ready',      // Monde créé, en attente de "Commencer"
	STARTING_ADVENTURE: 'starting',  // Premier narratif en cours
	PLAYING: 'playing'               // Jeu normal
};

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
		clearError, resetGame
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

	// Phase du jeu et données de génération
	const [gamePhase, setGamePhase] = useState(GAME_PHASE.LIST);
	const [worldGenProgress, setWorldGenProgress] = useState('');
	const [worldGenPhase, setWorldGenPhase] = useState('generating'); // 'generating' | 'populating'
	const [worldData, setWorldData] = useState(null);

	// Streaming avec callbacks
	const { startStream, cancel: cancelStream, rawJson } = useStreaming({
		onChunk: (display) => {
			// Mode LIGHT : afficher le narratif en streaming
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
		onProgress: (rawJson) => {
			// Mode INIT : mettre à jour la progression
			setWorldGenProgress(rawJson);
		},
		onPhase: (phase, message) => {
			// Changement de phase (ex: generating → populating)
			setWorldGenPhase(phase);
		},
		onDone: (displayText, state) => {
			setLoading(false);
			setSaving(true);

			// Mode INIT : monde créé
			if (state?.monde_cree) {
				setWorldData(state);
				setGamePhase(GAME_PHASE.WORLD_READY);
				// Mettre à jour le gameState avec les infos de base
				if (state.evenement_arrivee) {
					setGameState({
						partie: {
							cycle_actuel: state.evenement_arrivee.cycle || 1,
							jour: state.evenement_arrivee.jour,
							date_jeu: state.evenement_arrivee.date_jeu,
							heure: state.evenement_arrivee.heure,
							lieu_actuel: state.evenement_arrivee.lieu_actuel || state.lieu_depart,
							pnjs_presents: []
						},
						valentin: { credits: state.credits },
						ia: state.ia_nom ? { nom: state.ia_nom } : null
					});
				}
				return;
			}

			// Mode LIGHT : afficher le narratif final
			if (displayText) {
				setMessages(prev => {
					const newMsgs = [...prev];
					if (newMsgs.length > 0 && newMsgs[newMsgs.length - 1].streaming) {
						newMsgs[newMsgs.length - 1] = { role: 'assistant', content: displayText };
					} else if (displayText) {
						newMsgs.push({ role: 'assistant', content: displayText });
					}
					return newMsgs;
				});
			}

			if (state) {
				setGameState(state);
			}

			// Passer en mode jeu si on était en train de démarrer
			if (gamePhase === GAME_PHASE.STARTING_ADVENTURE) {
				setGamePhase(GAME_PHASE.PLAYING);
			}
		},
		onSaved: () => setSaving(false),
		onError: (msg, details) => {
			setLoading(false);
			setError({ message: msg, details, recoverable: true });
		}
	});

	// Charger les parties au démarrage
	useEffect(() => {
		loadParties();
	}, [loadParties]);

	// Rafraîchir tooltips après un message assistant
	useEffect(() => {
		const lastMsg = messages[messages.length - 1];
		if (lastMsg?.role === 'assistant' && !lastMsg.streaming && !loading && !saving) {
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

			// Si pas de messages, vérifier si le monde est déjà créé
			if (!data.messages?.length && data.state?.partie?.lieu_actuel) {
				// Monde créé mais pas encore commencé
				setWorldData({ monde_cree: true, lieu_depart: data.state.partie.lieu_actuel });
				setGamePhase(GAME_PHASE.WORLD_READY);
			} else if (data.messages?.length > 0) {
				setGamePhase(GAME_PHASE.PLAYING);
			} else {
				// Partie vide, lancer la génération
				setGamePhase(GAME_PHASE.GENERATING_WORLD);
				generateWorld(id);
			}
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoadingGame(false);
		}
	}, [loadPartie, setPartieId, replaceGameState, setPartieName, setMessages, setError]);

	const handleNewPartie = useCallback(async () => {
		setLoadingGame(true);
		setError(null);
		try {
			const id = await createPartie();
			setPartieId(id);
			setPartieName('Nouvelle partie');
			replaceGameState(null);
			setMessages([]);
			setWorldGenProgress('');
			setWorldData(null);
			loadParties();

			// Lancer directement la génération du monde
			setGamePhase(GAME_PHASE.GENERATING_WORLD);
			setLoadingGame(false);
			generateWorld(id);
		} catch (e) {
			setError({ message: e.message });
			setLoadingGame(false);
		}
	}, [createPartie, setPartieId, setPartieName, replaceGameState, setMessages, setError, loadParties]);

	// Génération du monde (mode INIT)
	const generateWorld = useCallback(async (id) => {
		setLoading(true);
		setError(null);
		setWorldGenProgress('');

		await startStream('/api/chat', {
			message: null,
			partieId: id,
			gameState: null // Pas de gameState = mode INIT
		});
	}, [startStream, setLoading, setError]);

	// Commencer l'aventure (premier LIGHT)
	const handleStartAdventure = useCallback(async () => {
		setGamePhase(GAME_PHASE.STARTING_ADVENTURE);
		setLoading(true);
		setError(null);

		// Ajouter un message système pour le premier narratif
		setMessages([]);

		await startStream('/api/chat', {
			message: '__ARRIVEE__',
			partieId,
			gameState // Le gameState contient maintenant les infos du monde
		});
	}, [partieId, gameState, startStream, setLoading, setError, setMessages]);

	const handleDeletePartie = useCallback(async (id) => {
		try {
			await deletePartie(id || partieId);
			if (id === partieId || !id) {
				resetGame();
				setShowSettings(false);
				setGamePhase(GAME_PHASE.LIST);
				setWorldData(null);
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
		setGamePhase(GAME_PHASE.LIST);
		setWorldData(null);
		setWorldGenProgress('');
		loadParties();
	}, [resetGame, loadParties]);

	// ============================================================
	// ACTIONS MESSAGES
	// ============================================================

	const sendMessage = useCallback(async (userMessage, previousMessages, currentGameState) => {
		setLoading(true);
		setError(null);

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

		let lastUserIdx = messages.length - 1;
		while (lastUserIdx >= 0 && messages[lastUserIdx].role !== 'user') lastUserIdx--;
		if (lastUserIdx < 0) return;

		const userMsg = messages[lastUserIdx].content;
		const prevMsgs = messages.slice(0, lastUserIdx);

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
	if (gamePhase === GAME_PHASE.LIST || !partieId) {
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

	// Chargement initial
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

	// Écran de génération du monde
	if (gamePhase === GAME_PHASE.GENERATING_WORLD || gamePhase === GAME_PHASE.WORLD_READY) {
		return (
			<WorldGenerationScreen
				isGenerating={gamePhase === GAME_PHASE.GENERATING_WORLD}
				partialJson={worldGenProgress}
				worldData={worldData}
				onStartAdventure={handleStartAdventure}
				error={error?.message}
			/>
		);
	}

	// Écran de démarrage de l'aventure (premier narratif en cours)
	if (gamePhase === GAME_PHASE.STARTING_ADVENTURE && messages.length === 0) {
		return (
			<div className="min-h-screen bg-gray-900 flex items-center justify-center">
				<div className="text-center space-y-4">
					<div className="relative">
						<div className="w-16 h-16 border-4 border-gray-700 rounded-full mx-auto" />
						<div className="absolute top-0 left-1/2 -translate-x-1/2 w-16 h-16 border-4 border-purple-500 rounded-full border-t-transparent animate-spin" />
					</div>
					<p className="text-gray-400">Début de l'aventure...</p>
				</div>
			</div>
		);
	}

	// Page de jeu normale
	return (
		<div className="h-screen flex flex-col bg-gray-900 text-white">
			<GameHeader
				partieName={partieName}
				gameState={gameState}
				onRename={handleRenamePartie}
				onShowSettings={() => setShowSettings(!showSettings)}
				onShowState={() => setShowState(!showState)}
				onQuit={handleQuit}
			/>

			<SettingsPanel
				isOpen={showSettings}
				fontSize={fontSize}
				onFontSizeChange={(delta) => delta > 0 ? increaseFontSize() : decreaseFontSize()}
				onDelete={() => setConfirmDeleteModal(true)}
				onClose={() => setShowSettings(false)}
			/>
			<DebugStatePanel isOpen={showState} gameState={gameState} />

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

			<InputArea
				onSend={handleSend}
				disabled={loading || saving}
				fontSize={fontSize}
			/>

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
