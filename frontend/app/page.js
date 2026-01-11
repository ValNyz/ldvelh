'use client';

import { useState, useCallback, useEffect } from 'react';

// Hooks
import { useGameState, useParties } from '../hooks/useGameState';
import { useStreaming } from '../hooks/useStreaming';
import { useGamePreferences } from '../hooks/useLocalStorage';
import { useTooltips } from '../hooks/useTooltips';
import { useWorldData } from '../hooks/useWorldData';

// API
import { stateApi } from '../lib/api';

// Components
import PartiesList from '../components/game/PartiesList';
import GameHeader from '../components/game/GameHeader';
import StatsBar from '../components/game/StatsBar';
import MessageList from '../components/game/MessageList';
import InputArea from '../components/game/InputArea';
import SettingsPanel, { DebugStatePanel } from '../components/game/SettingsPanel';
import WorldGenerationScreen from '../components/game/WorldGenerationScreen';
import { InventorySidebar, WorldSidebar } from '../components/game/Sidebars';

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

	// Sidebars
	const [activeSidebar, setActiveSidebar] = useState(null); // null | 'inventory' | 'world'

	// Hook pour les données du monde (PNJs, lieux, quêtes)
	const isPlaying = gamePhase === GAME_PHASE.PLAYING;
	const {
		worldData: sidebarWorldData,
		loading: worldLoading,
		refresh: refreshWorld
	} = useWorldData(partieId, isPlaying);

	// Streaming avec callbacks
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
		onProgress: (rawJson) => {
			setWorldGenProgress(rawJson);
		},
		onExtracting: (displayText) => {
			setIsExtracting(true);
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

				if (state.monde?.nom) {
					setPartieName(state.monde.nom);
				}

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
			refreshWorld(); // Rafraîchir les données du monde après extraction
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
	// SIDEBAR HANDLER
	// =========================================================================

	const toggleSidebar = useCallback((sidebar) => {
		setActiveSidebar(prev => prev === sidebar ? null : sidebar);
	}, []);

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
			setActiveSidebar(null);
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
		setActiveSidebar(null);
		try {
			const data = await loadPartie(id);
			setPartieId(id);
			setPartieName(data.state?.partie?.nom || 'Nouvelle partie');

			if (data.state) {
				replaceGameState(data.state);
			}

			const loadedMessages = data.messages || [];
			setMessages(loadedMessages);

			if (loadedMessages.length > 0) {
				setGamePhase(GAME_PHASE.PLAYING);
			} else if (data.state?.monde_cree) {
				if (data.world_info) {
					setWorldData(data.world_info);
				} else {
					setWorldData({
						monde_cree: true,
						lieu_depart: data.state.partie?.lieu_actuel,
						inventaire: data.state?.valentin?.inventaire || []
					});
				}
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
				setActiveSidebar(null);
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
		setActiveSidebar(null);
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
			await stateApi.rollback(partieId, editingIndex);
		} catch (e) {
			console.error('Rollback failed:', e);
			setError({ message: 'Échec du rollback: ' + e.message });
			return;
		}

		setMessages(prev => prev.slice(0, editingIndex));
		setEditingIndex(null);

		await handleSendMessage(content);
	}, [editingIndex, partieId, setMessages, handleSendMessage, setError]);

	const handleRegenerate = useCallback(async () => {
		if (!lastUserMessage) return;

		const lastAssistantIndex = messages.length - 1;
		if (messages[lastAssistantIndex]?.role !== 'assistant') return;

		try {
			await stateApi.rollback(partieId, messages.length - 2);
		} catch (e) {
			console.error('Rollback failed:', e);
			setError({ message: 'Échec du rollback: ' + e.message });
			return;
		}

		setMessages(prev => prev.slice(0, -2));

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
			<div className="min-h-screen bg-gray-950 flex items-center justify-center">
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

	// =========================================================================
	// ÉCRAN DE JEU PRINCIPAL
	// =========================================================================
	return (
		<div className="h-screen flex flex-col bg-gray-950 text-white overflow-hidden">
			<div className="flex-1 flex overflow-hidden">

				{/* Sidebar Inventaire (gauche) */}
				<InventorySidebar
					isOpen={activeSidebar === 'inventory'}
					onClose={() => setActiveSidebar(null)}
					inventaire={gameState?.valentin?.inventaire}
				/>

				{/* Zone principale */}
				<div className="flex-1 flex flex-col min-w-0">
					<GameHeader
						partieName={partieName}
						gameState={gameState}
						onRename={handleRenameGame}
						onToggleInventory={() => toggleSidebar('inventory')}
						onToggleWorld={() => toggleSidebar('world')}
						onShowSettings={() => setShowSettings(!showSettings)}
						onQuit={handleQuit}
						activeSidebar={activeSidebar}
						showSettings={showSettings}
					/>

					<SettingsPanel
						isOpen={showSettings}
						fontSize={fontSize}
						onFontSizeChange={(delta) => setFontSize(prev => Math.min(24, Math.max(10, prev + delta)))}
						onDelete={() => handleDeleteGame(partieId)}
						onClose={() => setShowSettings(false)}
					/>

					<DebugStatePanel isOpen={showState} gameState={gameState} />

					<StatsBar gameState={gameState} />

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

				{/* Sidebar Monde (droite) */}
				<WorldSidebar
					isOpen={activeSidebar === 'world'}
					onClose={() => setActiveSidebar(null)}
					worldData={sidebarWorldData}
					loading={worldLoading}
				/>
			</div>
		</div>
	);
}
