'use client';

import { useState, useCallback, useMemo } from 'react';

// ============================================================================
// GAME PHASES
// ============================================================================

export const GAME_PHASE = {
	LIST: 'list',
	WIZARD: 'wizard',
	GENERATING_WORLD: 'generating',
	WORLD_READY: 'world_ready',
	STARTING_ADVENTURE: 'starting',
	PLAYING: 'playing',
	SETTINGS: 'settings',
};

// ============================================================================
// HOOK
// ============================================================================

export function useGamePhase() {
	const [gamePhase, setGamePhase] = useState(GAME_PHASE.LIST);
	const [worldGenProgress, setWorldGenProgress] = useState('');
	const [worldData, setWorldData] = useState(null);

	const resetPhase = useCallback(() => {
		setGamePhase(GAME_PHASE.LIST);
		setWorldGenProgress('');
		setWorldData(null);
	}, []);

	const derived = useMemo(() => ({
		isWizard: gamePhase === GAME_PHASE.WIZARD,
		isPlaying: gamePhase === GAME_PHASE.PLAYING,
		isGenerating: gamePhase === GAME_PHASE.GENERATING_WORLD,
		isWorldReady: gamePhase === GAME_PHASE.WORLD_READY,
		isStarting: gamePhase === GAME_PHASE.STARTING_ADVENTURE,
		isSettings: gamePhase === GAME_PHASE.SETTINGS,
	}), [gamePhase]);

	return {
		gamePhase,
		setGamePhase,
		worldGenProgress,
		setWorldGenProgress,
		worldData,
		setWorldData,
		resetPhase,
		...derived,
		GAME_PHASE,
	};
}
