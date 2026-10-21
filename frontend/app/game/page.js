'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';

// Hooks
import { useGameState, useGames } from '../../hooks/useGameState';
import { useGamePhase } from '../../hooks/useGamePhase';
import { useGameOrchestrator } from '../../hooks/useGameOrchestrator';
import { usePreferences } from '../../hooks/usePreferences';
import { useTooltips } from '../../hooks/useTooltips';
import { useWorldData } from '../../hooks/useWorldData';
import { useWizardSession } from '../../hooks/useWizardSession';
import { draftKey, localDraftStore } from '../../lib/game/draftStores.mjs';

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
import WorldPendingScreen from '../../components/game/WorldPendingScreen';
import WizardContainer from '../../components/game/wizard/WizardContainer';
import { InventorySidebar, WorldSidebar } from '../../components/game/Sidebars';
import CharacterSheet from '../../components/game/CharacterSheet';
import AspectInvocationModal from '../../components/game/AspectInvocationModal';
import BackToGamesButton from '../../components/game/BackToGamesButton';

// Auth guard only: the game screen and its hooks render once the player is signed in (#53).
export default function GamePage() {
	const { user, isAuthenticated, isLoading: authLoading, logout } = useAuthContext();
	const router = useRouter();

	useEffect(() => {
		if (!authLoading && !isAuthenticated) router.replace('/login/');
	}, [authLoading, isAuthenticated, router]);

	if (authLoading || !isAuthenticated) {
		return (
			<div className="min-h-screen bg-surface-container-lowest flex items-center justify-center">
				<div className="w-10 h-10 border-4 border-gray-700 rounded-full border-t-primary animate-spin" />
			</div>
		);
	}
	return <GameScreen user={user} logout={logout} />;
}

function GameScreen({ user, logout }) {
	// =========================================================================
	// HOOKS
	// =========================================================================

	const gs = useGameState();
	const gamesHook = useGames();
	const phaseHook = useGamePhase();
	const prefs = usePreferences(user);
	const { tooltipMap, spansByMessage, refresh: refreshTooltips } = useTooltips(gs.gameId);

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

	// World being created: draft kept in this browser, per user
	const draftStore = useMemo(
		() => localDraftStore(() => window.localStorage, draftKey(user.id)),
		[user.id],
	);
	const wizardSession = useWizardSession({
		store: draftStore,
		openWizard: orch.handleNewGame,
		closeWizard: orch.handleWizardCancel,
		completeWizard: orch.handleWizardComplete,
	});

	// =========================================================================
	// EFFECTS
	// =========================================================================

	// First list: also drops the drafts of games deleted elsewhere (#88).
	const { forget: forgetDraft, prune: pruneDrafts } = wizardSession;
	useEffect(() => {
		gamesHook.loadGames().then(list => { if (list) pruneDrafts(list); });
	}, [gamesHook.loadGames, pruneDrafts]);

	// The world exists: the wizard draft it was created from is done (#88).
	const worldExists = phaseHook.isWorldReady || phaseHook.isPlaying;
	useEffect(() => {
		if (gs.gameId && worldExists) forgetDraft(gs.gameId);
	}, [gs.gameId, worldExists, forgetDraft]);

	const deleteGame = useCallback(async (id) => {
		if (await orch.handleDeleteGame(id)) forgetDraft(id);
	}, [orch, forgetDraft]);

	// Refresh tooltips when entering a game (gameId set + phase is PLAYING)
	useEffect(() => {
		if (gs.gameId && phaseHook.isPlaying) {
			refreshTooltips();
		}
	}, [gs.gameId, phaseHook.isPlaying, refreshTooltips]);

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
				onDeleteGame={deleteGame}
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
				key={wizardSession.wizardKey}
				{...wizardSession.wizard}
				loading={gs.loading}
				preferences={prefs}
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
					onNew={wizardSession.startNew}
					draft={wizardSession.resumable}
					onResumeDraft={wizardSession.resume}
					onDiscardDraft={wizardSession.discard}
					onDelete={deleteGame}
					onSettings={openSettings}
					onLogout={async () => { await logout(); window.location.href = '/login/'; }}
				/>
			</>
		);
	}

	// World not created yet: retry with the saved parameters, or edit them (#88)
	// This browser's draft, else the server's parameters; without a draft the retry is a bare
	// __INIT__ and the server reuses its own set.
	const localParams = wizardSession.paramsFor(gs.gameId);
	const pendingParams = localParams || orch.storedInitParams;
	const retryWorld = () => orch.handleRetryWorld(localParams);
	const editWorld = pendingParams ? () => wizardSession.edit(gs.gameId, orch.storedInitParams) : null;
	if (phaseHook.isWorldPending) {
		return (
			<WorldPendingScreen
				params={pendingParams}
				error={gs.error?.message}
				onRetry={retryWorld}
				onEdit={editWorld}
				onBack={orch.handleQuit}
			/>
		);
	}

	// World generation screen
	if (phaseHook.isGenerating || phaseHook.isWorldReady) {
		return (
			<WorldGenerationScreen
				isGenerating={phaseHook.isGenerating && !gs.error}
				onRetry={retryWorld}
				onEdit={editWorld}
				onBack={orch.handleQuit}
				partialJson={phaseHook.worldGenProgress}
				worldData={phaseHook.worldData}
				directorStatus={phaseHook.directorStatus}
				directorLabel={phaseHook.directorLabel}
				onStartAdventure={orch.handleStartAdventure}
				error={gs.error?.message}
			/>
		);
	}

	// Adventure starting screen
	if (phaseHook.isStarting && gs.messages.length === 0) {
		return (
			<div className="min-h-screen bg-surface-container-lowest flex items-center justify-center">
				<div className="text-center space-y-4">
					<div className="relative">
						<div className="w-16 h-16 border-4 border-gray-700 rounded-full mx-auto" />
						<div className="absolute top-0 left-1/2 -translate-x-1/2 w-16 h-16 border-4 border-primary rounded-full border-t-transparent animate-spin" />
					</div>
					<p className="text-gray-400">Début de l'aventure...</p>
					{/* Leaving cuts nothing: the arrival goes on and is shown again on reopening (#143) */}
					<BackToGamesButton onBack={orch.handleQuit} />
				</div>
			</div>
		);
	}

	// =========================================================================
	// MAIN GAME SCREEN
	// =========================================================================
	return (
		<div className="h-screen flex flex-col bg-surface-container-lowest text-white overflow-hidden">
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
						warning={gs.warning}
						onClearWarning={gs.clearWarning}
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
						spansByMessage={spansByMessage}
						tooltipMap={tooltipMap}
						showDebug={prefs.showDebug}
						engine={gs.gameState?.game?.engine}
					/>

					<InputArea
						onSend={orch.handleSendMessage}
						disabled={Boolean(orch.invocationData)}
						disableInput={gs.loading}
						disableSend={gs.loading}
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
