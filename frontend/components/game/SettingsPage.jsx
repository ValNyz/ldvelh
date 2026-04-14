'use client';

import { useState, useEffect } from 'react';
import { api } from '../../lib/api';

// Display labels for provider IDs (order matters for tab display)
const PROVIDER_LABELS = {
	anthropic: 'Anthropic',
	mistral: 'Mistral AI',
	wandb: 'W&B Inference',
	nebius: 'Nebius',
	nous: 'Nous Research',
};
const PROVIDER_ORDER = Object.keys(PROVIDER_LABELS);

export default function SettingsPage({
	onBack,
	preferences,
	onDeleteGame,
	gameId,
	user,
}) {
	const [activeTab, setActiveTab] = useState('anthropic');
	const [keyInputs, setKeyInputs] = useState({});
	const [showKey, setShowKey] = useState({});
	const [saving, setSaving] = useState({});
	const [saveSuccess, setSaveSuccess] = useState({});
	const [providers, setProviders] = useState([]);

	// Fetch provider catalog from backend
	useEffect(() => {
		let cancelled = false;
		api.get('/providers').then(data => {
			if (cancelled) return;
			const catalog = data.providers || {};
			const list = PROVIDER_ORDER
				.filter(id => id in catalog)
				.map(id => ({
					id,
					label: PROVIDER_LABELS[id] || id,
					models: catalog[id].models || [],
					defaultModel: catalog[id].default_model,
				}));
			setProviders(list);
		}).catch(e => console.error('Failed to fetch provider catalog:', e));
		return () => { cancelled = true; };
	}, []);

	const handleSaveKey = async (provider) => {
		const key = keyInputs[provider];
		if (!key) return;

		setSaving(prev => ({ ...prev, [provider]: true }));
		setSaveSuccess(prev => ({ ...prev, [provider]: false }));
		try {
			await preferences.setApiKey(provider, key);
			setKeyInputs(prev => ({ ...prev, [provider]: '' }));
			setSaveSuccess(prev => ({ ...prev, [provider]: true }));
			setTimeout(() => setSaveSuccess(prev => ({ ...prev, [provider]: false })), 2000);
		} catch (e) {
			console.error('Failed to save key:', e);
		} finally {
			setSaving(prev => ({ ...prev, [provider]: false }));
		}
	};

	const handleRemoveKey = async (provider) => {
		setSaving(prev => ({ ...prev, [provider]: true }));
		try {
			await preferences.setApiKey(provider, null);
		} catch (e) {
			console.error('Failed to remove key:', e);
		} finally {
			setSaving(prev => ({ ...prev, [provider]: false }));
		}
	};

	const hasKey = (provider) => {
		const k = preferences.apiKeys?.[provider];
		return k && k !== '****' && k !== null;
	};

	const [confirmDelete, setConfirmDelete] = useState(false);

	return (
		<div className="min-h-screen bg-surface-container-lowest text-white flex flex-col">
			{/* Header */}
			<header className="bg-surface/80 border-b border-gray-800/50 px-6 py-4 flex items-center gap-4">
				<button
					onClick={onBack}
					className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
				>
					<ChevronLeftIcon className="w-5 h-5" />
				</button>
				<h1 className="text-lg font-bold text-white">Paramètres</h1>
			</header>

			{/* Content */}
			<div className="flex-1 overflow-auto">
				<div className="max-w-2xl mx-auto p-6 space-y-8">

					{/* Account section */}
					<AccountSection user={user} />

					{/* AI Provider section */}
					<section>
						<h2 className="text-sm text-gray-400 uppercase tracking-wider mb-4">
							Modèle IA
						</h2>

						{/* Provider selector dropdown */}
						<div className="mb-4">
							<label className="block text-xs text-gray-500 mb-2">Fournisseur actif</label>
							<select
								value={preferences.activeProvider || ''}
								onChange={(e) => preferences.setActiveProvider(e.target.value || null)}
								className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
							>
								<option value="">Aucun (clé serveur)</option>
								{providers.map(p => (
									<option key={p.id} value={p.id} disabled={!hasKey(p.id)}>
										{p.label} {hasKey(p.id) ? '' : '(pas de clé)'}
									</option>
								))}
							</select>
						</div>

						{/* Model selector — shown when active provider has multiple models */}
						{(() => {
							const activeP = providers.find(p => p.id === (preferences.activeProvider || ''));
							const models = activeP?.models || [];
							if (models.length <= 1) return null;
							return (
								<div className="mb-4">
									<label className="block text-xs text-gray-500 mb-2">Modèle</label>
									<select
										value={preferences.activeModel || models[0]?.id || ''}
										onChange={(e) => preferences.setActiveModel(e.target.value || null)}
										className="w-full px-3 py-2.5 bg-gray-900 border border-gray-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
									>
										{models.map(m => (
											<option key={m.id} value={m.id}>{m.label}</option>
										))}
									</select>
								</div>
							);
						})()}

						{/* Tab list */}
						<div className="flex gap-1 mb-4 flex-wrap">
							{providers.map(p => (
								<button
									key={p.id}
									onClick={() => setActiveTab(p.id)}
									className={`px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
										activeTab === p.id
											? 'bg-gray-800 text-white border border-gray-600'
											: 'text-gray-500 hover:text-gray-300 hover:bg-gray-900'
									}`}
								>
									<span className="flex items-center justify-center gap-2">
										{hasKey(p.id) && (
											<span className="w-2 h-2 rounded-full bg-green-500" />
										)}
										{p.label}
									</span>
								</button>
							))}
						</div>

						{/* Key input for active tab */}
						<div className="bg-gray-900/80 border border-gray-800 rounded-xl p-4 space-y-3">
							<div className="flex items-center justify-between">
								<label className="text-sm text-gray-300">
									Clé API {providers.find(p => p.id === activeTab)?.label || PROVIDER_LABELS[activeTab] || activeTab}
								</label>
								{hasKey(activeTab) && (
									<span className="text-xs text-green-400 flex items-center gap-1">
										<span className="w-1.5 h-1.5 rounded-full bg-green-500" />
										Configurée
									</span>
								)}
							</div>

							{hasKey(activeTab) && (
								<div className="flex items-center justify-between bg-gray-800/50 rounded-lg px-3 py-2 min-w-0">
									<span className="text-sm text-gray-400 font-mono truncate min-w-0">
										{preferences.apiKeys[activeTab]}
									</span>
									<button
										onClick={() => handleRemoveKey(activeTab)}
										disabled={saving[activeTab]}
										className="text-red-400 hover:text-red-300 text-xs transition-colors disabled:opacity-50"
									>
										Supprimer
									</button>
								</div>
							)}

							<div className="flex gap-2">
								<input
									type={showKey[activeTab] ? 'text' : 'password'}
									value={keyInputs[activeTab] || ''}
									onChange={(e) => setKeyInputs(prev => ({ ...prev, [activeTab]: e.target.value }))}
									placeholder={hasKey(activeTab) ? 'Remplacer la clé...' : 'Entrer la clé API...'}
									className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
								/>
								<button
									onClick={() => setShowKey(prev => ({ ...prev, [activeTab]: !prev[activeTab] }))}
									className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-gray-400 hover:text-white transition-colors text-sm"
								>
									{showKey[activeTab] ? '🙈' : '👁️'}
								</button>
								<button
									onClick={() => handleSaveKey(activeTab)}
									disabled={!keyInputs[activeTab] || saving[activeTab]}
									className="px-4 py-2 bg-primary hover:brightness-110 rounded-lg text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
								>
									{saving[activeTab] ? '...' : saveSuccess[activeTab] ? '✓' : 'Sauver'}
								</button>
							</div>
						</div>
					</section>

					{/* Display section */}
					<section>
						<h2 className="text-sm text-gray-400 uppercase tracking-wider mb-4">
							Affichage
						</h2>

						<div className="bg-gray-900/80 border border-gray-800 rounded-xl p-4 space-y-4">
							{/* Font size */}
							<div className="flex items-center justify-between">
								<span className="text-sm text-gray-300">Taille police</span>
								<div className="flex items-center gap-3">
									<button
										onClick={() => preferences.updatePreference('fontSize', Math.max(10, preferences.fontSize - 2))}
										disabled={preferences.fontSize <= 10}
										className="px-3 py-1 bg-gray-800 rounded text-gray-300 hover:bg-gray-700 disabled:opacity-50 transition-colors"
									>
										−
									</button>
									<span className="text-white text-sm w-12 text-center font-mono">
										{preferences.fontSize}px
									</span>
									<button
										onClick={() => preferences.updatePreference('fontSize', Math.min(24, preferences.fontSize + 2))}
										disabled={preferences.fontSize >= 24}
										className="px-3 py-1 bg-gray-800 rounded text-gray-300 hover:bg-gray-700 disabled:opacity-50 transition-colors"
									>
										+
									</button>
								</div>
							</div>

							{/* Debug toggle */}
							<div className="flex items-center justify-between">
								<span className="text-sm text-gray-300">Mode debug</span>
								<label className="relative inline-flex items-center cursor-pointer">
									<input
										type="checkbox"
										checked={preferences.showDebug}
										onChange={(e) => preferences.updatePreference('showDebug', e.target.checked)}
										className="sr-only peer"
									/>
									<div className="w-9 h-5 bg-gray-700 peer-focus:ring-2 peer-focus:ring-primary/50 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-gray-400 after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary peer-checked:after:bg-white" />
								</label>
							</div>
						</div>
					</section>

					{/* Danger zone */}
					{gameId && (
						<section>
							<h2 className="text-sm text-red-400/70 uppercase tracking-wider mb-4">
								Zone danger
							</h2>

							<div className="bg-gray-900/80 border border-red-900/30 rounded-xl p-4">
								{confirmDelete ? (
									<div className="flex items-center gap-3">
										<span className="text-sm text-red-400">Confirmer la suppression ?</span>
										<button
											onClick={() => { onDeleteGame(gameId); setConfirmDelete(false); }}
											className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-sm rounded-lg transition-colors"
										>
											Confirmer
										</button>
										<button
											onClick={() => setConfirmDelete(false)}
											className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded-lg transition-colors"
										>
											Annuler
										</button>
									</div>
								) : (
									<button
										onClick={() => setConfirmDelete(true)}
										className="text-red-400 hover:text-red-300 text-sm transition-colors"
									>
										Supprimer la partie
									</button>
								)}
							</div>
						</section>
					)}

				</div>
			</div>
		</div>
	);
}

function AccountSection({ user }) {
	const [displayName, setDisplayName] = useState(user?.display_name || '');
	const [nameStatus, setNameStatus] = useState(null); // null, 'saving', 'saved', 'error'

	const [currentPassword, setCurrentPassword] = useState('');
	const [newPassword, setNewPassword] = useState('');
	const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
	const [pwStatus, setPwStatus] = useState(null); // null, 'saving', 'saved', 'error'
	const [pwError, setPwError] = useState('');

	const handleSaveName = async () => {
		setNameStatus('saving');
		try {
			const { api } = await import('../../lib/api');
			await api.patch('/auth/profile', { display_name: displayName });
			setNameStatus('saved');
			setTimeout(() => setNameStatus(null), 2000);
		} catch {
			setNameStatus('error');
			setTimeout(() => setNameStatus(null), 2000);
		}
	};

	const handleChangePassword = async (e) => {
		e.preventDefault();
		setPwError('');
		if (newPassword !== newPasswordConfirm) {
			setPwError('Les mots de passe ne correspondent pas');
			return;
		}
		if (newPassword.length < 6) {
			setPwError('Le mot de passe doit faire au moins 6 caractères');
			return;
		}
		setPwStatus('saving');
		try {
			const { api } = await import('../../lib/api');
			await api.post('/auth/change-password', {
				current_password: currentPassword,
				new_password: newPassword,
				new_password_confirm: newPasswordConfirm,
			});
			setPwStatus('saved');
			setCurrentPassword('');
			setNewPassword('');
			setNewPasswordConfirm('');
			setTimeout(() => setPwStatus(null), 2000);
		} catch (err) {
			setPwStatus('error');
			setPwError(err.message || 'Erreur');
			setTimeout(() => setPwStatus(null), 2000);
		}
	};

	const nameChanged = displayName !== (user?.display_name || '');

	return (
		<section>
			<h2 className="text-sm text-gray-400 uppercase tracking-wider mb-4">
				Compte
			</h2>

			<div className="bg-gray-900/80 border border-gray-800 rounded-xl p-4 space-y-5">
				{/* Email (read-only) */}
				<div>
					<label className="block text-xs text-gray-500 mb-1">Email</label>
					<div className="flex items-center gap-2">
						<span className="text-sm text-gray-300">{user?.email}</span>
						{user?.email_verified ? (
							<span className="text-xs text-green-400 flex items-center gap-1">
								<span className="w-1.5 h-1.5 rounded-full bg-green-500" />
								Vérifié
							</span>
						) : (
							<span className="text-xs text-yellow-400">Non vérifié</span>
						)}
					</div>
				</div>

				{/* Display name */}
				<div>
					<label className="block text-xs text-gray-500 mb-1">Nom d'affichage</label>
					<div className="flex gap-2">
						<input
							type="text"
							value={displayName}
							onChange={(e) => setDisplayName(e.target.value)}
							maxLength={100}
							className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
							placeholder="Votre pseudo"
						/>
						<button
							onClick={handleSaveName}
							disabled={!nameChanged || nameStatus === 'saving'}
							className="px-4 py-2 bg-primary hover:brightness-110 rounded-lg text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{nameStatus === 'saving' ? '...' : nameStatus === 'saved' ? '✓' : 'Sauver'}
						</button>
					</div>
				</div>

				{/* Password change */}
				<div className="border-t border-gray-800 pt-4">
					<label className="block text-xs text-gray-500 mb-3">Changer le mot de passe</label>

					{pwError && (
						<div className="bg-red-900/30 border border-red-700 rounded-lg px-3 py-2 text-red-400 text-xs mb-3">
							{pwError}
						</div>
					)}
					{pwStatus === 'saved' && (
						<div className="bg-green-900/30 border border-green-700 rounded-lg px-3 py-2 text-green-400 text-xs mb-3">
							Mot de passe modifié
						</div>
					)}

					<form onSubmit={handleChangePassword} className="space-y-2">
						<input
							type="password"
							value={currentPassword}
							onChange={(e) => setCurrentPassword(e.target.value)}
							placeholder="Mot de passe actuel"
							required
							className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
						/>
						<input
							type="password"
							value={newPassword}
							onChange={(e) => setNewPassword(e.target.value)}
							placeholder="Nouveau mot de passe (min. 6)"
							required
							minLength={6}
							className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
						/>
						<input
							type="password"
							value={newPasswordConfirm}
							onChange={(e) => setNewPasswordConfirm(e.target.value)}
							placeholder="Confirmer le nouveau mot de passe"
							required
							minLength={6}
							className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-transparent"
						/>
						<button
							type="submit"
							disabled={!currentPassword || !newPassword || !newPasswordConfirm || pwStatus === 'saving'}
							className="px-4 py-2 bg-primary hover:brightness-110 rounded-lg text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{pwStatus === 'saving' ? '...' : 'Changer le mot de passe'}
						</button>
					</form>
				</div>
			</div>
		</section>
	);
}

function ChevronLeftIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
		</svg>
	);
}
