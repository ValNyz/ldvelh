'use client';

import { useState, useCallback, useEffect } from 'react';
import EngineSelectionStep from './EngineSelectionStep';
import WorldConfigStep from './WorldConfigStep';
import CharacterCreationStep from './CharacterCreationStep';
import { useFormHistory } from '../../../hooks/useFormHistory';
import { worldApi } from '../../../lib/api';
import { D6_ATTRIBUTES, getD6Skills, getFateSkills } from '../../../lib/game/engineConfig';
import { d6SkillsForSubmit } from '../../../lib/game/d6.mjs';
import { TEXT_PAUSE_MS } from '../../../lib/game/formHistory.mjs';

const STEPS = ['engine', 'world', 'character'];
const STEP_LABELS = ['Moteur', 'Monde', 'Personnage'];

const INITIAL_FORM = {
	engine: 'none',
	worldConfig: {
		genre: 'sci_fi',
		difficulty: 'moderate',
		duration: 'medium',
		hardcore: false,
		lore: '',
	},
	characterData: {},
	manualEntities: {},
};

export default function WizardContainer({ onComplete, onCancel, loading, preferences }) {
	const [step, setStep] = useState(0);
	// One history for the whole form: undo / redo covers player and AI changes.
	const form = useFormHistory(INITIAL_FORM);
	const { engine, worldConfig, characterData, manualEntities } = form.state;
	const [enhancing, setEnhancing] = useState(null); // scope being enhanced
	const [enhanceError, setEnhanceError] = useState(null);

	const { set: setForm, seal: sealHistory } = form;
	// One entry per visit of a field (sealed when it loses focus); the long texts
	// (lore, description) are also cut at pauses, like a text editor.
	const setSlice = useCallback(
		(slice) => (value) => setForm(f => ({ ...f, [slice]: value }), {
			meta: step,
			pauseMs: document.activeElement?.tagName === 'TEXTAREA' ? TEXT_PAUSE_MS : null,
		}),
		[setForm, step],
	);
	const setEngine = setSlice('engine');
	const setWorldConfig = setSlice('worldConfig');
	const setCharacterData = setSlice('characterData');
	const setManualEntities = setSlice('manualEntities');

	const handleUndo = useCallback(() => {
		if (!form.canUndo || enhancing) return;
		if (form.undoMeta !== null) setStep(form.undoMeta);
		form.undo();
	}, [form, enhancing]);

	const handleRedo = useCallback(() => {
		if (!form.canRedo || enhancing) return;
		if (form.redoMeta !== null) setStep(form.redoMeta);
		form.redo();
	}, [form, enhancing]);

	// Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Y. Also inside fields: their native
	// undo does not know about the form history (and the AI fills).
	useEffect(() => {
		const onKeyDown = (e) => {
			if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
			const key = e.key.toLowerCase();
			if (key === 'z' && !e.shiftKey) {
				e.preventDefault();
				handleUndo();
			} else if ((key === 'z' && e.shiftKey) || key === 'y') {
				e.preventDefault();
				handleRedo();
			}
		};
		document.addEventListener('keydown', onKeyDown);
		return () => document.removeEventListener('keydown', onKeyDown);
	}, [handleUndo, handleRedo]);

	const handleEnhance = useCallback(async (scope) => {
		setEnhancing(scope);
		setEnhanceError(null);
		try {
			const result = await worldApi.enhance({
				scope,
				engine,
				provider: preferences?.activeProvider || 'anthropic',
				model: preferences?.activeModel || null,
				current: {
					world_config: worldConfig,
					character_data: characterData,
					manual_entities: manualEntities,
				},
			});
			const patch = scope === 'world'
				? { worldConfig: result.world_config, manualEntities: result.manual_entities }
				: { characterData: result.character_data };
			setForm(f => ({ ...f, ...patch }), { key: null, meta: step });
		} catch (e) {
			setEnhanceError(e.message || 'Erreur inconnue');
		} finally {
			setEnhancing(null);
		}
	}, [engine, worldConfig, characterData, manualEntities, preferences, setForm, step]);

	const enhanceProps = (scope) => ({
		onEnhance: () => handleEnhance(scope),
		enhancing: enhancing === scope,
		enhanceError: enhancing ? null : enhanceError,
	});

	const goToStep = (next) => {
		setEnhanceError(null);
		setStep(next);
	};

	const canProceed = useCallback(() => {
		if (step === 0) return !!engine;
		if (step === 1) return !!worldConfig.genre;
		return true;
	}, [step, engine, worldConfig]);

	const handleNext = () => {
		if (step < STEPS.length - 1) {
			goToStep(step + 1);
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
					duration: worldConfig.duration || 'medium',
					hardcore: worldConfig.hardcore,
					...(worldConfig.lore ? { lore: worldConfig.lore } : {}),
				},
				// Name, gender, occupation and description apply to every engine, free mode included.
				characterData: Object.keys(characterData).length
					? characterForSubmit(engine, worldConfig.genre, characterData)
					: null,
				manualEntities: hasEntities ? filteredEntities : null,
			});
		}
	};

	const handleBack = () => {
		if (step > 0) goToStep(step - 1);
		else onCancel();
	};

	return (
		<div className="min-h-screen bg-surface flex flex-col items-center justify-center p-4 md:p-8">
			<div className="max-w-xl w-full">
				{/* Step indicator */}
				<div className="flex items-center justify-center gap-2 mb-8">
					{STEPS.map((_, i) => (
						<div key={i} className="flex items-center gap-2">
							<div
								className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
									i === step
										? 'bg-primary text-white'
										: i < step
											? 'bg-primary/20 text-primary'
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
								<div className={`w-8 h-px ${i < step ? 'bg-primary' : 'bg-gray-700'}`} />
							)}
						</div>
					))}
				</div>

				{/* Step content */}
				<div className="relative bg-gray-850 rounded-xl p-6">
					{/* Undo / redo: every change, by the player or the AI */}
					<div className="absolute top-4 right-4 flex gap-1">
						<HistoryButton label="Défaire (Ctrl+Z)" disabled={!form.canUndo || !!enhancing} onClick={handleUndo}>
							<path d="M9 14 4 9l5-5" /><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" />
						</HistoryButton>
						<HistoryButton label="Refaire (Ctrl+Maj+Z)" disabled={!form.canRedo || !!enhancing} onClick={handleRedo}>
							<path d="m15 14 5-5-5-5" /><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13" />
						</HistoryButton>
					</div>
					{/* Disabled while the AI fills the step, so its result does not overwrite new edits */}
					<fieldset disabled={!!enhancing} onBlur={(e) => isTextField(e.target) && sealHistory()} className="space-y-6 min-w-0">
						{step === 0 && (
							<EngineSelectionStep value={engine} onChange={setEngine} />
						)}
						{step === 1 && (
							<WorldConfigStep
								config={worldConfig}
								onChange={setWorldConfig}
								manualEntities={manualEntities}
								onManualEntitiesChange={setManualEntities}
								{...enhanceProps('world')}
							/>
						)}
						{step === 2 && (
							<CharacterCreationStep
								engine={engine}
								genre={worldConfig.genre}
								data={characterData}
								onChange={setCharacterData}
								{...enhanceProps('character')}
							/>
						)}
					</fieldset>
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
						disabled={!canProceed() || loading || !!enhancing}
						className="px-6 py-2 bg-primary hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
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

/**
 * Engine stats as the backend stores them. Skills of another genre (genre
 * changed after allocating) are dropped.
 * - d6: every attribute (2D when untouched), skills as [{attribute, name, dice_value}]
 * - fate_core: the pyramid restricted to the genre's skills
 */
function characterForSubmit(engine, genre, data) {
	if (engine === 'd6') {
		const attributes = Object.fromEntries(D6_ATTRIBUTES.map(a => [a, data.attributes?.[a] || '2D']));
		const skills = data.skills && !Array.isArray(data.skills) ? data.skills : {};
		return { ...data, attributes, skills: d6SkillsForSubmit(skills, attributes, getD6Skills(genre)) };
	}
	if (engine === 'fate_core' && data.skills) {
		const allowed = new Set(getFateSkills(genre));
		return { ...data, skills: Object.fromEntries(Object.entries(data.skills).filter(([name]) => allowed.has(name))) };
	}
	return data;
}

// Typing fields: leaving one ends its entry. Buttons do not ("−" then "+" on one skill merges).
function isTextField(el) {
	return el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && !['button', 'checkbox', 'radio'].includes(el.type));
}

function HistoryButton({ label, disabled, onClick, children }) {
	return (
		<button
			type="button"
			onClick={onClick}
			disabled={disabled}
			title={label}
			aria-label={label}
			className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-gray-400 disabled:cursor-not-allowed transition-colors"
		>
			<svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
				{children}
			</svg>
		</button>
	);
}
