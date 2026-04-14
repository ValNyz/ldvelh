'use client';

import { useMemo } from 'react';
import {
	calculateProgress,
	getCurrentStep,
	extractWorldName,
	GENERATION_STEPS
} from '../../lib/game/progressUtils';

export default function WorldGenerationScreen({
	isGenerating,
	partialJson,
	worldData,
	onStartAdventure,
	error
}) {
	const isStreamComplete = !isGenerating;

	const progress = useMemo(
		() => calculateProgress(partialJson, isStreamComplete),
		[partialJson, isStreamComplete]
	);

	const currentStep = useMemo(
		() => getCurrentStep(partialJson),
		[partialJson]
	);

	const worldName = useMemo(
		() => extractWorldName(partialJson),
		[partialJson]
	);

	const isComplete = isStreamComplete && worldData != null;

	return (
		<div className="min-h-screen bg-surface flex flex-col items-center justify-center p-4 md:p-8">
			<div className="max-w-xl w-full space-y-6">
				{/* Title */}
				<div className="text-center">
					<h1 className="text-3xl font-bold text-white mb-2">
						{isComplete ? '✨ Monde créé' : 'Création du monde...'}
					</h1>
					{(worldData?.world?.name || worldName) && (
						<p className="text-2xl text-primary font-semibold">
							{worldData?.world?.name || worldName}
						</p>
					)}
					{worldData?.world?.type && (
						<p className="text-gray-400 mt-1">{worldData.world.type}</p>
					)}
				</div>

				{/* Progress bar */}
				{isGenerating && (
					<div className="space-y-3">
						<div className="h-3 bg-gray-700 rounded-full overflow-hidden">
							<div
								className="h-full bg-primary transition-all duration-500 ease-out"
								style={{ width: `${progress}%` }}
							/>
						</div>
						<div className="flex justify-between text-sm">
							<span className="text-gray-400">
								{currentStep.label}
								<span className="animate-pulse">...</span>
							</span>
							<span className="text-gray-500">{progress}%</span>
						</div>

						{/* Step indicators */}
						<div className="flex gap-1 justify-center flex-wrap mt-2">
							{GENERATION_STEPS.map((step) => {
								const stepStarted = new RegExp(`"${step.key}"\\s*:`).test(partialJson || '');
								const stepDone = stepStarted && partialJson &&
									new RegExp(`"${step.key}"\\s*:\\s*[\\[{]`).test(partialJson);

								return (
									<div
										key={step.key}
										className={`w-2 h-2 rounded-full transition-colors ${step.key === currentStep.key
											? 'bg-primary animate-pulse'
											: stepDone
												? 'bg-green-500'
												: 'bg-gray-600'
											}`}
										title={step.label}
									/>
								);
							})}
						</div>
					</div>
				)}

				{/* Generated content */}
				{isComplete && worldData && (
					<div className="space-y-4">
						<div className="grid grid-cols-4 gap-3">
							<div className="bg-gray-800 rounded-lg p-3 text-center">
								<p className="text-2xl font-bold text-primary">
									{worldData.npc_count || 0}
								</p>
								<p className="text-xs text-gray-400">PNJs</p>
							</div>
							<div className="bg-gray-800 rounded-lg p-3 text-center">
								<p className="text-2xl font-bold text-blue-400">
									{worldData.location_count || 0}
								</p>
								<p className="text-xs text-gray-400">Lieux</p>
							</div>
							<div className="bg-gray-800 rounded-lg p-3 text-center">
								<p className="text-2xl font-bold text-green-400">
									{worldData.org_count || 0}
								</p>
								<p className="text-xs text-gray-400">Orgs</p>
							</div>
							<div className="bg-gray-800 rounded-lg p-3 text-center">
								<p className="text-2xl font-bold text-yellow-400">
									{worldData.protagonist?.credits || 0}
								</p>
								<p className="text-xs text-gray-400">Crédits</p>
							</div>
						</div>

						{worldData.world?.atmosphere && (
							<div className="bg-primary/10 rounded-lg p-4 border border-primary/30">
								<p className="text-gray-300 italic">"{worldData.world.atmosphere}"</p>
								{worldData.world?.population && (
									<p className="text-gray-500 text-sm mt-2">
										Population : {worldData.world.population.toLocaleString()} habitants
									</p>
								)}
							</div>
						)}

						{worldData.ai && (
							<div className="bg-gray-800 rounded-lg p-4">
								<div className="flex items-center gap-3 mb-2">
									<span className="text-2xl">🤖</span>
									<div>
										<p className="text-white font-medium">{worldData.ai.name}</p>
										<p className="text-gray-400 text-sm">Votre IA personnelle</p>
									</div>
								</div>
								{worldData.ai.personality?.length > 0 && (
									<div className="flex flex-wrap gap-1 mt-2">
										{worldData.ai.personality.map((trait, i) => (
											<span key={i} className="px-2 py-1 bg-gray-700 rounded text-xs text-gray-300">
												{trait}
											</span>
										))}
									</div>
								)}
							</div>
						)}

						{worldData.arrival && (
							<div className="bg-gray-800 rounded-lg p-4 border-l-4 border-primary">
								<p className="text-gray-400 text-sm mb-1">Votre aventure commence...</p>
								<p className="text-white">📍 {worldData.arrival.location}</p>
								<p className="text-gray-400 text-sm">{worldData.arrival.date}</p>
							</div>
						)}

						{worldData.generation_cost && (
							<p className="text-gray-600 text-xs text-right">
								{worldData.generation_cost.provider && `[${worldData.generation_cost.provider}] `}
								{worldData.generation_cost.model && `${worldData.generation_cost.model} · `}
								${worldData.generation_cost.cost_usd?.toFixed(4)}
								{' · '}{worldData.generation_cost.input_tokens}in · {worldData.generation_cost.output_tokens}out
							</p>
						)}
					</div>
				)}

				{/* Spinner */}
				{isGenerating && (
					<div className="flex justify-center">
						<div className="relative">
							<div className="w-16 h-16 border-4 border-gray-700 rounded-full" />
							<div className="absolute top-0 left-0 w-16 h-16 border-4 border-primary rounded-full border-t-transparent animate-spin" />
						</div>
					</div>
				)}

				{error && (
					<div className="bg-red-900/50 border border-red-700 rounded-lg p-4">
						<p className="text-red-400">{error}</p>
					</div>
				)}

				{isComplete && (
					<button
						onClick={onStartAdventure}
						className="w-full py-4 px-6 bg-primary hover:brightness-110
                     text-white font-semibold text-lg rounded-lg
                     transform transition-all duration-200
                     hover:scale-[1.02] active:scale-[0.98]
                     shadow-lg shadow-primary/25"
					>
						🚀 Commencer l'aventure
					</button>
				)}

				{isGenerating && (
					<p className="text-center text-gray-500 text-sm">
						Génération du monde en cours...
						<br />
						Cette étape peut prendre plusieurs minutes...
					</p>
				)}
			</div>
		</div>
	);
}
