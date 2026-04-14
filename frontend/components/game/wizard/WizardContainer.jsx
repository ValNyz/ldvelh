'use client';

import { useState, useCallback } from 'react';
import EngineSelectionStep from './EngineSelectionStep';
import WorldConfigStep from './WorldConfigStep';
import CharacterCreationStep from './CharacterCreationStep';

const STEPS = ['engine', 'world', 'character'];
const STEP_LABELS = ['Moteur', 'Monde', 'Personnage'];

export default function WizardContainer({ onComplete, onCancel, loading }) {
	const [step, setStep] = useState(0);
	const [engine, setEngine] = useState('none');
	const [worldConfig, setWorldConfig] = useState({
		genre: 'sci_fi',
		difficulty: 'moderate',
		hardcore: false,
		lore: '',
	});
	const [characterData, setCharacterData] = useState({});
	const [manualEntities, setManualEntities] = useState({});

	const canProceed = useCallback(() => {
		if (step === 0) return !!engine;
		if (step === 1) return !!worldConfig.genre;
		return true;
	}, [step, engine, worldConfig]);

	const handleNext = () => {
		if (step < STEPS.length - 1) {
			setStep(step + 1);
		} else {
			// Final step — create game
			// Filter out empty manual entities
			const filteredEntities = {};
			if (manualEntities.npcs?.length) {
				filteredEntities.npcs = manualEntities.npcs.filter(e => e.name.trim());
			}
			if (manualEntities.locations?.length) {
				filteredEntities.locations = manualEntities.locations.filter(e => e.name.trim());
			}
			if (manualEntities.organizations?.length) {
				filteredEntities.organizations = manualEntities.organizations.filter(e => e.name.trim());
			}
			const hasEntities = Object.keys(filteredEntities).length > 0;

			onComplete({
				engine,
				worldConfig: {
					genre: worldConfig.genre,
					difficulty: worldConfig.difficulty,
					hardcore: worldConfig.hardcore,
					...(worldConfig.lore ? { lore: worldConfig.lore } : {}),
				},
				characterData: engine !== 'none' ? characterData : null,
				manualEntities: hasEntities ? filteredEntities : null,
			});
		}
	};

	const handleBack = () => {
		if (step > 0) setStep(step - 1);
		else onCancel();
	};

	return (
		<div className="min-h-screen bg-gray-900 flex flex-col items-center justify-center p-4 md:p-8">
			<div className="max-w-xl w-full">
				{/* Step indicator */}
				<div className="flex items-center justify-center gap-2 mb-8">
					{STEPS.map((_, i) => (
						<div key={i} className="flex items-center gap-2">
							<div
								className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
									i === step
										? 'bg-purple-600 text-white'
										: i < step
											? 'bg-purple-900 text-purple-300'
											: 'bg-gray-800 text-gray-500'
								}`}
							>
								{i < step ? '✓' : i + 1}
							</div>
							<span className={`text-xs hidden sm:inline ${
								i === step ? 'text-white' : 'text-gray-500'
							}`}>
								{STEP_LABELS[i]}
							</span>
							{i < STEPS.length - 1 && (
								<div className={`w-8 h-px ${i < step ? 'bg-purple-600' : 'bg-gray-700'}`} />
							)}
						</div>
					))}
				</div>

				{/* Step content */}
				<div className="bg-gray-850 rounded-xl p-6 space-y-6">
					{step === 0 && (
						<EngineSelectionStep value={engine} onChange={setEngine} />
					)}
					{step === 1 && (
						<WorldConfigStep
							config={worldConfig}
							onChange={setWorldConfig}
							manualEntities={manualEntities}
							onManualEntitiesChange={setManualEntities}
						/>
					)}
					{step === 2 && (
						<CharacterCreationStep
							engine={engine}
							genre={worldConfig.genre}
							data={characterData}
							onChange={setCharacterData}
						/>
					)}
				</div>

				{/* Navigation */}
				<div className="flex justify-between mt-6">
					<button
						onClick={handleBack}
						className="px-4 py-2 text-gray-400 hover:text-white transition-colors text-sm"
					>
						{step === 0 ? 'Annuler' : 'Retour'}
					</button>
					<button
						onClick={handleNext}
						disabled={!canProceed() || loading}
						className="px-6 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
					>
						{loading ? (
							<span className="flex items-center gap-2">
								<svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
									<circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
									<path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
								</svg>
								Création...
							</span>
						) : (
							step < STEPS.length - 1 ? 'Suivant' : 'Créer le monde'
						)}
					</button>
				</div>
			</div>
		</div>
	);
}
