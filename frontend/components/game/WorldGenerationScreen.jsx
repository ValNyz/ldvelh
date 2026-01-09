'use client';

import { useMemo } from 'react';

// Étapes de génération avec poids pour la barre de progression
const GENERATION_STEPS = [
	{ key: 'monde', label: 'Création du monde', weight: 15 },
	{ key: 'employeur', label: 'Employeur', weight: 10 },
	{ key: 'valentin', label: 'Personnage', weight: 10 },
	{ key: 'ia', label: 'IA personnelle', weight: 5 },
	{ key: 'pnj_initiaux', label: 'Personnages', weight: 20 },
	{ key: 'lieux_initiaux', label: 'Lieux', weight: 15 },
	{ key: 'inventaire_initial', label: 'Inventaire', weight: 10 },
	{ key: 'evenement_arrivee', label: 'Événement d\'arrivée', weight: 10 },
	{ key: 'arcs_potentiels', label: 'Arcs narratifs', weight: 5 }
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

	return (
		<div className="min-h-screen bg-gray-900 flex flex-col items-center justify-center p-8">
			<div className="max-w-md w-full space-y-8">
				{/* Titre */}
				<div className="text-center">
					<h1 className="text-3xl font-bold text-white mb-2">
						{isComplete ? '✨ Monde créé' : 'Création du monde...'}
					</h1>
					{worldData?.monde?.nom && (
						<p className="text-xl text-purple-400">{worldData.monde.nom}</p>
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
						{worldData.monde?.type && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">🛸</span>
								<div>
									<p className="text-gray-400 text-sm">Type</p>
									<p className="text-white">{worldData.monde.type}</p>
								</div>
							</div>
						)}
						{worldData.monde?.ambiance && (
							<div className="flex items-start gap-3">
								<span className="text-2xl">🌌</span>
								<div>
									<p className="text-gray-400 text-sm">Ambiance</p>
									<p className="text-white text-sm">{worldData.monde.ambiance}</p>
								</div>
							</div>
						)}
						{worldData.ia_nom && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">🤖</span>
								<div>
									<p className="text-gray-400 text-sm">IA personnelle</p>
									<p className="text-white">{worldData.ia_nom}</p>
								</div>
							</div>
						)}
						{worldData.lieu_depart && (
							<div className="flex items-center gap-3">
								<span className="text-2xl">📍</span>
								<div>
									<p className="text-gray-400 text-sm">Point de départ</p>
									<p className="text-white">{worldData.lieu_depart}</p>
								</div>
							</div>
						)}
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
					</p>
				)}
			</div>
		</div>
	);
}
