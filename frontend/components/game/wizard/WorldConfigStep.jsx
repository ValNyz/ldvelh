'use client';

import { useState, useEffect } from 'react';
import { api } from '../../../lib/api';
import { DIFFICULTIES } from '../../../lib/game/engineConfig';

const GENRE_ICONS = {
	sci_fi: '🚀',
	dark_fantasy: '🗡️',
	cosmic_horror: '🐙',
	cyberpunk: '💾',
};

export default function WorldConfigStep({ config, onChange, manualEntities, onManualEntitiesChange }) {
	const update = (key, val) => onChange({ ...config, [key]: val });
	const [showEntities, setShowEntities] = useState(
		() => !!(manualEntities?.npcs?.length || manualEntities?.locations?.length || manualEntities?.organizations?.length)
	);
	const [genres, setGenres] = useState([]);

	// Load genres from API
	useEffect(() => {
		api.get('/genres').then(data => {
			setGenres(data?.genres || []);
			// Auto-select first genre if none selected
			if (!config.genre && data?.genres?.length > 0) {
				update('genre', data.genres[0].slug);
			}
		}).catch(() => {});
	}, []);

	return (
		<div className="space-y-6">
			<h2 className="text-xl font-semibold text-white">Configuration du monde</h2>

			{/* Genre */}
			<div>
				<label className="block text-sm text-gray-300 mb-2">Genre</label>
				<div className="flex flex-wrap gap-2">
					{genres.map((g) => (
						<button
							key={g.slug}
							onClick={() => update('genre', g.slug)}
							className={`px-3 py-2 rounded-lg text-sm transition-colors ${
								config.genre === g.slug
									? 'bg-primary text-white'
									: 'bg-gray-800 text-gray-300 hover:bg-gray-700'
							}`}
						>
							{GENRE_ICONS[g.slug] || '🎮'} {g.label}
						</button>
					))}
				</div>
			</div>

			{/* Difficulty */}
			<div>
				<label className="block text-sm text-gray-300 mb-2">Difficulté</label>
				<div className="grid grid-cols-2 gap-2">
					{DIFFICULTIES.map((d) => (
						<button
							key={d.id}
							onClick={() => update('difficulty', d.id)}
							className={`p-3 rounded-lg text-left transition-colors ${
								config.difficulty === d.id
									? 'bg-primary/15 border border-primary text-white'
									: 'bg-gray-800 border border-gray-700 text-gray-300 hover:bg-gray-700'
							}`}
						>
							<span className="font-medium text-sm">{d.name}</span>
							<p className="text-xs text-gray-400 mt-0.5">{d.description}</p>
						</button>
					))}
				</div>
			</div>

			{/* Lore (optional) */}
			<div>
				<label className="block text-sm text-gray-300 mb-2">
					Contexte libre <span className="text-gray-500">(optionnel)</span>
				</label>
				<textarea
					value={config.lore || ''}
					onChange={(e) => update('lore', e.target.value)}
					placeholder="Décris l'ambiance, le contexte historique, des détails particuliers..."
					className="w-full h-24 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary/50 resize-y"
				/>
			</div>

			{/* Hardcore toggle */}
			<label className="flex items-center gap-3 cursor-pointer group">
				<div className="relative">
					<input
						type="checkbox"
						checked={config.hardcore || false}
						onChange={(e) => update('hardcore', e.target.checked)}
						className="sr-only peer"
					/>
					<div className="w-10 h-5 bg-gray-700 rounded-full peer-checked:bg-red-600 transition-colors" />
					<div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-5" />
				</div>
				<div>
					<span className="text-sm text-gray-300 group-hover:text-white transition-colors">Mode Hardcore</span>
					<p className="text-xs text-gray-500">Mort permanente, pas de retour en arrière</p>
				</div>
			</label>

			{/* Manual entities toggle */}
			<div>
				<button
					onClick={() => setShowEntities(!showEntities)}
					className="text-sm text-primary hover:brightness-110 transition-colors flex items-center gap-1"
				>
					<span className={`transition-transform ${showEntities ? 'rotate-90' : ''}`}>&#9654;</span>
					Personnaliser les entités du monde
					<span className="text-gray-500">(optionnel)</span>
				</button>

				{showEntities && (
					<div className="mt-3 space-y-4">
						<EntityList
							label="PNJs"
							placeholder="Nom du PNJ"
							descPlaceholder="Description (rôle, personnalité...)"
							items={manualEntities?.npcs || []}
							onChange={(npcs) => onManualEntitiesChange({ ...manualEntities, npcs })}
						/>
						<EntityList
							label="Lieux"
							placeholder="Nom du lieu"
							descPlaceholder="Description (ambiance, fonction...)"
							items={manualEntities?.locations || []}
							onChange={(locations) => onManualEntitiesChange({ ...manualEntities, locations })}
						/>
						<EntityList
							label="Organisations"
							placeholder="Nom de l'organisation"
							descPlaceholder="Description (type, influence...)"
							items={manualEntities?.organizations || []}
							onChange={(organizations) => onManualEntitiesChange({ ...manualEntities, organizations })}
						/>
					</div>
				)}
			</div>
		</div>
	);
}

// ============================================================================
// ENTITY LIST EDITOR
// ============================================================================

function EntityList({ label, placeholder, descPlaceholder, items, onChange }) {
	const addItem = () => onChange([...items, { name: '', description: '' }]);

	const updateItem = (idx, field, val) => {
		const next = items.map((item, i) => (i === idx ? { ...item, [field]: val } : item));
		onChange(next);
	};

	const removeItem = (idx) => onChange(items.filter((_, i) => i !== idx));

	return (
		<div>
			<div className="flex items-center justify-between mb-1.5">
				<span className="text-xs text-gray-400 uppercase tracking-wider">{label}</span>
				<button
					onClick={addItem}
					className="text-xs text-primary hover:brightness-110 transition-colors"
				>
					+ Ajouter
				</button>
			</div>
			{items.length === 0 ? (
				<p className="text-xs text-gray-600 italic">Aucun — le narrateur choisira</p>
			) : (
				<div className="space-y-2">
					{items.map((item, i) => (
						<div key={i} className="flex gap-2 items-start">
							<div className="flex-1 space-y-1">
								<input
									value={item.name}
									onChange={(e) => updateItem(i, 'name', e.target.value)}
									placeholder={placeholder}
									className="w-full px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded text-white text-sm placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary/50"
								/>
								<input
									value={item.description}
									onChange={(e) => updateItem(i, 'description', e.target.value)}
									placeholder={descPlaceholder}
									className="w-full px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded text-gray-300 text-xs placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary/50"
								/>
							</div>
							<button
								onClick={() => removeItem(i)}
								className="p-1 text-gray-500 hover:text-red-400 transition-colors mt-1"
							>
								✕
							</button>
						</div>
					))}
				</div>
			)}
		</div>
	);
}
