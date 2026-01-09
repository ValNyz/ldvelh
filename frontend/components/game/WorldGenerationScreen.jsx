'use client';

import { useMemo } from 'react';

// Étapes de génération alignées avec le schéma WorldGeneration (Python)
// Ordre basé sur l'ordre de génération dans WorldPopulator.populate()
const GENERATION_STEPS = [
	{ key: 'generation_seed_words', label: 'Initialisation', weight: 0 },
	{ key: 'tone_notes', label: 'Ton narratif', weight: 5 },
	{ key: 'world', label: 'Création du monde', weight: 10 },
	{ key: 'protagonist', label: 'Protagoniste', weight: 10 },
	{ key: 'personal_ai', label: 'IA personnelle', weight: 5 },
	{ key: 'organizations', label: 'Organisations', weight: 10 },
	{ key: 'locations', label: 'Lieux', weight: 15 },
	{ key: 'characters', label: 'Personnages', weight: 15 },
	{ key: 'inventory', label: 'Inventaire', weight: 10 },
	{ key: 'initial_relations', label: 'Relations', weight: 5 },
	{ key: 'narrative_arcs', label: 'Arcs narratifs', weight: 5 },
	{ key: 'arrival_event', label: 'Événement d\'arrivée', weight: 5 }
];

/**
 * Calcule la progression basée sur le JSON partiel reçu
 */
function calculateProgress(partialJson) {
	if (!partialJson) return 0;

	let progress = 0;

	for (const step of GENERATION_STEPS) {
		// Cherche si la clé existe dans le JSON (même partiellement)
		const keyPattern = new RegExp(`"${step.key}"\\s*:`);
		if (keyPattern.test(partialJson)) {
			progress += step.weight;
		}
	}

	return Math.min(progress, 100);
}

/**
 * Détermine l'étape actuelle
 */
function getCurrentStep(partialJson) {
	if (!partialJson) return GENERATION_STEPS[0];

	let lastFound = GENERATION_STEPS[0];

	for (const step of GENERATION_STEPS) {
		const keyPattern = new RegExp(`"${step.key}"\\s*:`);
		if (keyPattern.test(partialJson)) {
			lastFound = step;
		}
	}

	return lastFound;
}

/**
 * Écran de génération du monde
 */
export default function WorldGenerationScreen({
	isGenerating,
	partialJson,
	worldData,
	onStartAdventure,
	error
}) {
	const progress = useMemo(() => calculateProgress(partialJson), [partialJson]);
	const currentStep = useMemo(() => getCurrentStep(partialJson), [partialJson]);
	const isComplete = !isGenerating && worldData?.monde_cree;

	// Extraire les données du nouveau schéma
	const worldName = worldData?.world?.name;
	const worldType = worldData?.world?.station_type;
	const worldAtmosphere = worldData?.world?.atmosphere;
	const worldPopulation = worldData?.world?.population;
	const aiName = worldData?.personal_ai?.name;
	const arrivalLocation = worldData?.arrival_event?.arrival_location_ref;
	const protagonistName = worldData?.protagonist?.name;
	const characterCount = worldData?.characters?.length || 0;
	const locationCount = worldData?.locations?.length || 0;

	return (
		<div className="min-h-screen bg-gray-900 flex flex-col items-center justify-center p-8">
			<div className="max-w-md w-full space-y-8">
				{/* Titre */}
				<div className="text-center">
					<h1 className="text-3xl font-bold text-white mb-2">
						{isComplete ? '✨ Monde créé' : 'Création du monde...'}
					</h1>
					{worldName && (
						<p className="text-xl text-purple-400">{worldName}</p>
					)}
				</div>

				{/* Barre de progression */}
				{isGenerating && (
					<div className="space-y-3">
						<div className="h-3 bg-gray-700 rounded-full overflow-hidden">
							<div
								className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all duration-300 ease-out"
								style={{ width: `${progress}%` }}
							/>
						</div>
						<div className="flex justify-between text-sm">
							<span className="text-gray-400">{currentStep.label}...</span>
							<span className="text-gray-500">{progress}%</span>
						</div>
					</div>
				)}

				{/* Infos du monde généré */}
				{isComplete && worldData && (
					<div className="bg-gray-800 rounded-lg p-6 space-y-4">
						{worldType && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">🛸</span>
								<div>
									<p className="text-gray-400 text-sm">Type</p>
									<p className="text-white">{worldType}</p>
								</div>
							</div>
						)}
						{worldAtmosphere && (
							<div className="flex items-start gap-3">
								<span className="text-2xl">🌌</span>
								<div>
									<p className="text-gray-400 text-sm">Ambiance</p>
									<p className="text-white text-sm">{worldAtmosphere}</p>
								</div>
							</div>
						)}
						{worldPopulation && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">👥</span>
								<div>
									<p className="text-gray-400 text-sm">Population</p>
									<p className="text-white">{worldPopulation.toLocaleString()} habitants</p>
								</div>
							</div>
						)}
						{aiName && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">🤖</span>
								<div>
									<p className="text-gray-400 text-sm">IA personnelle</p>
									<p className="text-white">{aiName}</p>
								</div>
							</div>
						)}
						{arrivalLocation && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">📍</span>
								<div>
									<p className="text-gray-400 text-sm">Point d'arrivée</p>
									<p className="text-white">{arrivalLocation}</p>
								</div>
							</div>
						)}
						{/* Stats de génération */}
						<div className="pt-4 border-t border-gray-700 flex justify-around text-center">
							<div>
								<p className="text-2xl font-bold text-purple-400">{characterCount}</p>
								<p className="text-xs text-gray-500">Personnages</p>
							</div>
							<div>
								<p className="text-2xl font-bold text-pink-400">{locationCount}</p>
								<p className="text-xs text-gray-500">Lieux</p>
							</div>
							<div>
								<p className="text-2xl font-bold text-blue-400">
									{worldData?.inventory?.length || 0}
								</p>
								<p className="text-xs text-gray-500">Objets</p>
							</div>
						</div>
					</div>
				)}

				{/* Spinner pendant génération */}
				{isGenerating && (
					<div className="flex justify-center">
						<div className="relative">
							<div className="w-16 h-16 border-4 border-gray-700 rounded-full" />
							<div className="absolute top-0 left-0 w-16 h-16 border-4 border-purple-500 rounded-full border-t-transparent animate-spin" />
						</div>
					</div>
				)}

				{/* Erreur */}
				{error && (
					<div className="bg-red-900/50 border border-red-700 rounded-lg p-4">
						<p className="text-red-400">{error}</p>
					</div>
				)}

				{/* Bouton Commencer */}
				{isComplete && (
					<button
						onClick={onStartAdventure}
						className="w-full py-4 px-6 bg-gradient-to-r from-purple-600 to-pink-600 
						         hover:from-purple-500 hover:to-pink-500 
						         text-white font-semibold text-lg rounded-lg
						         transform transition-all duration-200 
						         hover:scale-[1.02] active:scale-[0.98]
						         shadow-lg shadow-purple-500/25"
					>
						🚀 Commencer l'aventure
					</button>
				)}

				{/* Texte d'attente */}
				{isGenerating && (
					<p className="text-center text-gray-500 text-sm">
						Génération du monde en cours, veuillez patienter...
						<br />
						Cette étape peut prendre plusieurs minutes...
					</p>
				)}
			</div>
		</div>
	);
}
