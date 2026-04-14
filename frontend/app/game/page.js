'use client';

import { useState, useCallback, useEffect, Suspense } from 'react';

// Hooks
import { useGameState, useGames } from '../../hooks/useGameState';
import { useGamePhase } from '../../hooks/useGamePhase';
import { useGameOrchestrator } from '../../hooks/useGameOrchestrator';
import { usePreferences } from '../../hooks/usePreferences';
import { useTooltips } from '../../hooks/useTooltips';
import { useWorldData } from '../../hooks/useWorldData';

// Auth
import { useAuthContext } from '../../lib/AuthContext';

// Components
import GamesList from '../../components/game/GamesList';
import GameHeader from '../../components/game/GameHeader';
import StatsBar from '../../components/game/StatsBar';
import MessageList from '../../components/game/MessageList';
import InputArea from '../../components/game/InputArea';
import { DebugStatePanel } from '../../components/game/SettingsPanel';
import SettingsPage from '../../components/game/SettingsPage';
import WorldGenerationScreen from '../../components/game/WorldGenerationScreen';
import WizardContainer from '../../components/game/wizard/WizardContainer';
import { InventorySidebar, WorldSidebar } from '../../components/game/Sidebars';
import CharacterSheet from '../../components/game/CharacterSheet';
import AspectInvocationModal from '../../components/game/AspectInvocationModal';

export default function Home() {
	// =========================================================================
	// AUTH GUARD
	// =========================================================================

	const { user, isAuthenticated, isLoading: authLoading, logout } = useAuthContext();

	if (authLoading) {
		return (
			<div className="min-h-screen bg-gray-950 flex items-center justify-center">
				<div className="w-10 h-10 border-4 border-gray-700 rounded-full border-t-purple-500 animate-spin" />
			</div>
		);
	}

	if (!isAuthenticated) {
		if (typeof window !== 'undefined') window.location.href = '/login/';
		return null;
	}

	// =========================================================================
	// HOOKS
	// =========================================================================

	const gs = useGameState();
	const gamesHook = useGames();
	const phaseHook = useGamePhase();
	const prefs = usePreferences(user);
	const { tooltipMap, refresh: refreshTooltips } = useTooltips(gs.gameId);

	// UI State
	const [showState, setShowState] = useState(false);
	const [activeSidebar, setActiveSidebar] = useState(null);

	// World sidebar data
	const {
		worldData: sidebarWorldData,
		loading: worldLoading,
		refresh: refreshWorld
	} = useWorldData(gs.gameId, phaseHook.isPlaying);

	// Orchestrator
	const orch = useGameOrchestrator({
		gameState: gs,
		games: gamesHook,
		phase: phaseHook,
		tooltips: { refresh: refreshTooltips },
		world: { refresh: refreshWorld },
		preferences: prefs,
	});

	// =========================================================================
	// EFFECTS
	// =========================================================================

	useEffect(() => {
		gamesHook.loadGames();
	}, [gamesHook.loadGames]);

	// =========================================================================
	// SETTINGS NAVIGATION
	// =========================================================================

	const openSettings = useCallback(() => {
		phaseHook.setGamePhase(phaseHook.GAME_PHASE.SETTINGS);
	}, [phaseHook]);

	const closeSettings = useCallback(() => {
		if (gs.gameId) {
			phaseHook.setGamePhase(phaseHook.GAME_PHASE.PLAYING);
		} else {
			phaseHook.setGamePhase(phaseHook.GAME_PHASE.LIST);
		}
	}, [gs.gameId, phaseHook]);

	// =========================================================================
	// SIDEBAR HANDLER
	// =========================================================================

	const toggleSidebar = useCallback((sidebar) => {
		setActiveSidebar(prev => prev === sidebar ? null : sidebar);
	}, []);

	// =========================================================================
	// RENDER
	// =========================================================================

	// Settings page (full screen)
	if (phaseHook.isSettings) {
		return (
			<SettingsPage
				onBack={closeSettings}
				preferences={prefs}
				onDeleteGame={orch.handleDeleteGame}
				gameId={gs.gameId}
				user={user}
			/>
		);
	}

	// Wizard screen (engine + world config + character creation)
	// Must be checked before LIST because gameId is still null during wizard
	if (phaseHook.isWizard) {
		return (
			<WizardContainer
				onComplete={orch.handleWizardComplete}
				onCancel={orch.handleWizardCancel}
				loading={gs.loading}
			/>
		);
	}

	// Game list screen
	if ((phaseHook.gamePhase === phaseHook.GAME_PHASE.LIST || !gs.gameId) && !phaseHook.isWizard) {
		return (
			<>
				{user && !user.email_verified && <EmailVerificationBanner />}
				<GamesList
					parties={gamesHook.games}
					loading={gamesHook.loadingList}
					error={gs.error?.message}
					onSelect={orch.handleLoadGame}
					onNew={orch.handleNewGame}
					onDelete={orch.handleDeleteGame}
					onSettings={openSettings}
					onLogout={() => { logout(); window.location.href = '/login/'; }}
				/>
			</>
		);
	}

	// World generation screen
	if (phaseHook.isGenerating || phaseHook.isWorldReady) {
		return (
			<WorldGenerationScreen
				isGenerating={phaseHook.isGenerating}
				partialJson={phaseHook.worldGenProgress}
				worldData={phaseHook.worldData}
				onStartAdventure={orch.handleStartAdventure}
				error={gs.error?.message}
			/>
		);
	}

	// Adventure starting screen
	if (phaseHook.isStarting && gs.messages.length === 0) {
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
	// MAIN GAME SCREEN
	// =========================================================================
	return (
		<div className="h-screen flex flex-col bg-gray-950 text-white overflow-hidden">
			<div className="flex-1 flex overflow-hidden">

				{/* Character Sheet Sidebar (left) */}
				<CharacterSheet
					isOpen={activeSidebar === 'character'}
					onClose={() => setActiveSidebar(null)}
					gameState={gs.gameState}
				/>

				{/* Inventory Sidebar (left) */}
				<InventorySidebar
					isOpen={activeSidebar === 'inventory'}
					onClose={() => setActiveSidebar(null)}
					inventory={gs.gameState?.player?.inventory}
				/>

				{/* Main area */}
				<div className="flex-1 flex flex-col min-w-0">
					<GameHeader
						partieName={gs.gameName}
						gameState={gs.gameState}
						onRename={orch.handleRenameGame}
						onToggleCharacterSheet={() => toggleSidebar('character')}
						onToggleInventory={() => toggleSidebar('inventory')}
						onToggleWorld={() => toggleSidebar('world')}
						onShowSettings={openSettings}
						onQuit={orch.handleQuit}
						activeSidebar={activeSidebar}
					/>

					<DebugStatePanel isOpen={showState} gameState={gs.gameState} />

					<StatsBar gameState={gs.gameState} />

					<MessageList
						messages={gs.messages}
						loading={gs.loading}
						saving={gs.saving}
						error={gs.error}
						fontSize={prefs.fontSize}
						editingIndex={orch.editingIndex}
						onEdit={orch.handleEdit}
						onCancelEdit={orch.handleCancelEdit}
						onSubmitEdit={orch.handleSubmitEdit}
						onResend={orch.handleResend}
						onRegenerate={orch.handleRegenerate}
						onCancel={orch.handleCancel}
						onClearError={gs.clearError}
						onRetry={orch.handleRetry}
						tooltipMap={tooltipMap}
						showDebug={prefs.showDebug}
						engine={gs.gameState?.game?.engine}
					/>

					<InputArea
						onSend={orch.handleSendMessage}
						disableInput={gs.loading && !orch.isExtracting}
						disableSend={gs.loading || orch.isExtracting}
						fontSize={prefs.fontSize}
					/>
				</div>

				{/* World Sidebar (right) */}
				<WorldSidebar
					isOpen={activeSidebar === 'world'}
					onClose={() => setActiveSidebar(null)}
					worldData={sidebarWorldData}
					loading={worldLoading}
				/>
			</div>

			{/* Fate Core Aspect Invocation Modal */}
			{orch.invocationData && (
				<AspectInvocationModal
					invocationData={orch.invocationData}
					onInvoke={orch.handleInvoke}
					onSkip={orch.handleSkipInvocation}
				/>
			)}
		</div>
	);
}


function EmailVerificationBanner() {
	const [sending, setSending] = useState(false);
	const [sent, setSent] = useState(false);

	const handleResend = async () => {
		setSending(true);
		try {
			const { api } = await import('../../lib/api');
			await api.post('/auth/resend-verification');
			setSent(true);
		} catch {
			// Ignore
		} finally {
			setSending(false);
		}
	};

	return (
		<div className="bg-yellow-900/30 border-b border-yellow-700/50 px-4 py-2.5 text-center text-sm text-yellow-300">
			Votre email n'est pas vérifié.{' '}
			{sent ? (
				<span className="text-green-400">Email envoyé !</span>
			) : (
				<button
					onClick={handleResend}
					disabled={sending}
					className="underline hover:text-yellow-200 transition-colors disabled:opacity-50"
				>
					{sending ? 'Envoi...' : 'Renvoyer le lien de vérification'}
				</button>
			)}
		</div>
	);
}
