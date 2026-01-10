'use client';

import { useState, useCallback, useEffect, useRef } from 'react';

// Hooks
import { useGameState, useParties } from '../hooks/useGameState';
import { useStreaming } from '../hooks/useStreaming';
import { useGamePreferences } from '../hooks/useLocalStorage';
import { useTooltips } from '../hooks/useTooltips';

// API
import { chatApi, gamesApi } from '../lib/api';

// Components
import PartiesList from '../components/game/PartiesList';
import GameHeader from '../components/game/GameHeader';
import MessageList from '../components/game/MessageList';
import InputArea from '../components/game/InputArea';
import SettingsPanel, { DebugStatePanel } from '../components/game/SettingsPanel';
import WorldGenerationScreen from '../components/game/WorldGenerationScreen';
import Modal from '../components/ui/Modal';

// ============================================================================
// PHASES DU JEU
// ============================================================================
const GAME_PHASE = {
	LIST: 'list',
	GENERATING_WORLD: 'generating',
	WORLD_READY: 'world_ready',
	STARTING_ADVENTURE: 'starting',
	PLAYING: 'playing'
};

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
	const { tooltipMap, refresh: refreshTooltips } = useTooltips(partieId);

	// UI State
	const [showSettings, setShowSettings] = useState(false);
	const [showState, setShowState] = useState(false);
	const [editingIndex, setEditingIndex] = useState(null);
	const [lastUserMessage, setLastUserMessage] = useState('');

	// Phase du jeu et données de génération
	const [gamePhase, setGamePhase] = useState(GAME_PHASE.LIST);
	const [worldGenProgress, setWorldGenProgress] = useState('');
	const [worldData, setWorldData] = useState(null);

	// État d'extraction (narratif affiché, KG en cours de mise à jour)
	const [isExtracting, setIsExtracting] = useState(false);

	// Streaming avec callbacks
	const { startStream, cancel, isStreaming, rawJson } = useStreaming({
		onChunk: (content) => {
			// Mode LIGHT : afficher le narratif en streaming
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant' && last.streaming) {
					return [...prev.slice(0, -1), { ...last, content: last.content + content }];
				}
				return [...prev, { role: 'assistant', content, streaming: true }];
			});
		},
		onProgress: (rawJson) => {
			// Mode INIT : mettre à jour la progression
			setWorldGenProgress(rawJson);
		},
		onExtracting: (displayText) => {
			// Narratif terminé, extraction en cours
			// Le joueur peut commencer à préparer sa réponse
			setIsExtracting(true);

			// Finaliser l'affichage du message
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return [...prev.slice(0, -1), {
						...last,
						content: displayText || last.content,
						streaming: false,
						extracting: true
					}];
				}
				return prev;
			});
		},
		onDone: (displayText, state) => {
			setLoading(false);
			setSaving(true);
			setIsExtracting(false);

			// Mode INIT : monde créé
			if (displayText === null && state?.monde_cree) {
				setWorldData(state);
				setGamePhase(GAME_PHASE.WORLD_READY);

				setGameState({
					partie: {
						cycle_actuel: state.evenement_arrivee?.cycle || 1,
						jour: state.evenement_arrivee?.jour || 1,
						date_jeu: state.evenement_arrivee?.date_jeu,
						heure: state.evenement_arrivee?.heure || "08h00",
						lieu_actuel: state.evenement_arrivee?.lieu_actuel || state.lieu_depart,
						pnjs_presents: []
					},
					valentin: {
						credits: state.credits,
						inventaire: state.inventaire || []
					},
					ia: state.ia_nom ? { nom: state.ia_nom } : null,
					monde_cree: true
				});
				return;
			}

			// Mode LIGHT : afficher le narratif final
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.role === 'assistant') {
					return [...prev.slice(0, -1), {
						...last,
						content: displayText || last.content,
						streaming: false,
						extracting: false
					}];
				}
				return prev;
			});

			if (state) setGameState(state);

			if (gamePhase === GAME_PHASE.STARTING_ADVENTURE) {
				setGamePhase(GAME_PHASE.PLAYING);
			}
		},
		onSaved: () => {
			setSaving(false);
			refreshTooltips();
		},
		onError: (err, details) => {
			setError({ message: err, details, recoverable: true });
			setLoading(false);
			setSaving(false);
			setIsExtracting(false);
		}
	});

	// =========================================================================
	// EFFECTS
	// =========================================================================

	useEffect(() => {
		loadParties();
	}, [loadParties]);

	// =========================================================================
	// GÉNÉRATION DU MONDE
	// =========================================================================

	const generateWorld = useCallback(async (id) => {
		setLoading(true);
		setError(null);
		setWorldGenProgress('');

		await startStream('/chat', {
			message: '__INIT__',
			gameId: id,
			gameState: null
		});
	}, [startStream, setLoading, setError]);

	const handleStartAdventure = useCallback(async () => {
		setGamePhase(GAME_PHASE.STARTING_ADVENTURE);
		setLoading(true);
		setError(null);
		setMessages([]);

		await startStream('/chat', {
			message: '__ARRIVEE__',
			gameId: partieId,
			gameState
		});
	}, [partieId, gameState, startStream, setLoading, setError, setMessages]);

	// =========================================================================
	// HANDLERS PARTIES
	// =========================================================================

	const handleNewGame = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const id = await createPartie();
			setPartieId(id);
			setPartieName('Nouvelle partie');
			setMessages([]);
			replaceGameState(null);
			setWorldGenProgress('');
			setWorldData(null);
			await loadParties();

			setGamePhase(GAME_PHASE.GENERATING_WORLD);
			setLoading(false);
			generateWorld(id);
		} catch (e) {
			setError({ message: e.message });
			setLoading(false);
		}
	}, [createPartie, setPartieId, setPartieName, replaceGameState, setMessages, setError, loadParties, generateWorld]);

	const handleLoadGame = useCallback(async (id) => {
		setLoading(true);
		setError(null);
		try {
			const data = await loadPartie(id);
			setPartieId(id);
			setPartieName(data.partie?.nom || data.name || 'Partie');

			if (data.state) {
				replaceGameState(data.state);
			}

			const loadedMessages = data.messages || [];
			setMessages(loadedMessages);

			if (loadedMessages.length > 0) {
				setGamePhase(GAME_PHASE.PLAYING);
			} else if (data.state?.monde_cree) {
				setWorldData({
					monde_cree: true,
					lieu_depart: data.state.partie.lieu_actuel,
					inventaire: data.state?.valentin?.inventaire || []
				});
				setGamePhase(GAME_PHASE.WORLD_READY);
			} else {
				setGamePhase(GAME_PHASE.GENERATING_WORLD);
				setLoading(false);
				generateWorld(id);
				return;
			}
		} catch (e) {
			setError({ message: e.message });
		} finally {
			setLoading(false);
		}
	}, [loadPartie, setPartieId, replaceGameState, setPartieName, setMessages, setError, generateWorld]);

	const handleDeleteGame = useCallback(async (id) => {
		try {
			await deletePartie(id);
			if (partieId === id) {
				resetGame();
				setGamePhase(GAME_PHASE.LIST);
				setWorldData(null);
			}
			await loadParties();
		} catch (e) {
			setError({ message: e.message });
		}
	}, [deletePartie, partieId, resetGame, loadParties, setError]);

	const handleRenameGame = useCallback(async (newName) => {
		if (!partieId) return;
		await renamePartie(partieId, newName);
		setPartieName(newName);
		await loadParties();
	}, [partieId, renamePartie, setPartieName, loadParties]);

	const handleQuit = useCallback(() => {
		resetGame();
		setGamePhase(GAME_PHASE.LIST);
		setWorldData(null);
		setWorldGenProgress('');
		loadParties();
	}, [resetGame, loadParties]);

	// =========================================================================
	// HANDLERS MESSAGES
	// =========================================================================

	const handleSendMessage = useCallback(async (content) => {
		if (!partieId || loading || isExtracting) return;

		setLastUserMessage(content);
		setMessages(prev => [...prev, { role: 'user', content }]);
		setLoading(true);
		setSaving(true);

		await startStream('/chat', {
			gameId: partieId,
			message: content,
			gameState
		});
	}, [partieId, loading, isExtracting, gameState, startStream, setMessages, setLoading, setSaving]);

	const handleCancel = useCallback(() => {
		if (cancel()) {
			setLoading(false);
			setSaving(false);
			setIsExtracting(false);
			setMessages(prev => {
				const last = prev[prev.length - 1];
				if (last?.streaming || last?.extracting) {
					return [...prev.slice(0, -1), {
						...last,
						streaming: false,
						extracting: false,
						content: last.content + '\n\n*(Annulé)*'
					}];
				}
				return prev;
			});
		}
	}, [cancel, setLoading, setSaving, setMessages]);

	const handleEdit = useCallback((index) => {
		setEditingIndex(index);
	}, []);

	const handleCancelEdit = useCallback(() => {
		setEditingIndex(null);
	}, []);

	const handleSubmitEdit = useCallback(async (content) => {
		if (editingIndex === null) return;

		try {
			// 1. Rollback backend AVANT d'envoyer
			await gamesApi.rollback(partieId, editingIndex);
		} catch (e) {
			console.error('Rollback failed:', e);
			setError({ message: 'Échec du rollback: ' + e.message });
			return;
		}

		// 2. Tronquer localement
		setMessages(prev => prev.slice(0, editingIndex));
		setEditingIndex(null);

		// 3. Envoyer le nouveau message
		await handleSendMessage(content);
	}, [editingIndex, partieId, setMessages, handleSendMessage, setError]);

	const handleRegenerate = useCallback(async () => {
		if (!lastUserMessage) return;

		const lastAssistantIndex = messages.length - 1;
		if (messages[lastAssistantIndex]?.role !== 'assistant') return;

		try {
			// 1. Rollback: supprimer le dernier échange (user + assistant)
			// On veut garder jusqu'à l'index du message USER qu'on va re-soumettre
			await gamesApi.rollback(partieId, messages.length - 2);
		} catch (e) {
			console.error('Rollback failed:', e);
			setError({ message: 'Échec du rollback: ' + e.message });
			return;
		}

		// 2. Supprimer les 2 derniers messages localement (user + assistant)
		setMessages(prev => prev.slice(0, -2));

		// 3. Renvoyer le message user
		await handleSendMessage(lastUserMessage);
	}, [lastUserMessage, messages, partieId, setMessages, handleSendMessage, setError]);

	const handleRetry = useCallback(() => {
		if (lastUserMessage) handleSendMessage(lastUserMessage);
	}, [lastUserMessage, handleSendMessage]);

	// =========================================================================
	// RENDER
	// =========================================================================

	// Écran de sélection de partie
	if (gamePhase === GAME_PHASE.LIST || !partieId) {
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

	// Écran de démarrage de l'aventure
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

	// Écran de jeu normal
	return (
		<div className="h-screen flex flex-col bg-gray-900 text-white">
			<GameHeader
				partieName={partieName}
				gameState={gameState}
				onRename={handleRenameGame}
				onShowSettings={() => setShowSettings(!showSettings)}
				onShowState={() => setShowState(!showState)}
				onQuit={handleQuit}
			/>

			<SettingsPanel
				isOpen={showSettings}
				fontSize={fontSize}
				onFontSizeChange={(delta) => setFontSize(prev => Math.min(24, Math.max(10, prev + delta)))}
				onDelete={() => handleDeleteGame(partieId)}
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
				onRetry={handleRetry}
				tooltipMap={tooltipMap}
			/>

			<InputArea
				onSend={handleSendMessage}
				disableInput={loading && !isExtracting}
				disableSend={loading || isExtracting}
				fontSize={fontSize}
			/>
		</div>
	);
}
