'use client';

import { useState } from 'react';
import { useAuthContext } from '../../../lib/AuthContext';

export default function RegisterPage() {
	const { register, error, clearError, isAuthenticated } = useAuthContext();
	const [email, setEmail] = useState('');
	const [password, setPassword] = useState('');
	const [passwordConfirm, setPasswordConfirm] = useState('');
	const [displayName, setDisplayName] = useState('');
	const [loading, setLoading] = useState(false);
	const [localError, setLocalError] = useState(null);

	// Redirect if already authenticated
	if (isAuthenticated) {
		if (typeof window !== 'undefined') window.location.href = '/game';
		return null;
	}

	const displayError = localError || error;

	const handleSubmit = async (e) => {
		e.preventDefault();
		clearError();
		setLocalError(null);
		if (password !== passwordConfirm) {
			setLocalError('Les mots de passe ne correspondent pas');
			return;
		}
		setLoading(true);
		try {
			await register(email, password, passwordConfirm, displayName || null);
			window.location.href = '/game';
		} catch {
			// Error handled by useAuth
		} finally {
			setLoading(false);
		}
	};

	return (
		<form onSubmit={handleSubmit} className="bg-surface border border-outline-variant/20 rounded-xl p-8 space-y-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
			<h2 className="text-xl font-headline font-semibold text-on-surface">Créer un compte</h2>

			{displayError && (
				<div className="bg-error/8 border-l-[3px] border-error rounded-r-lg px-4 py-3 text-error text-sm">
					{displayError}
				</div>
			)}

			<div>
				<label className="block text-on-surface-variant text-xs font-label mb-1.5 tracking-wide">Email</label>
				<input
					type="email"
					value={email}
					onChange={(e) => setEmail(e.target.value)}
					required
					autoFocus
					className="w-full px-4 py-3 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all"
					placeholder="you@example.com"
				/>
			</div>

			<div>
				<label className="block text-on-surface-variant text-xs font-label mb-1.5 tracking-wide">
					Nom d&apos;affichage <span className="text-on-surface-variant/40">(optionnel)</span>
				</label>
				<input
					type="text"
					value={displayName}
					onChange={(e) => setDisplayName(e.target.value)}
					className="w-full px-4 py-3 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all"
					placeholder="Votre pseudo"
				/>
			</div>

			<div>
				<label className="block text-on-surface-variant text-xs font-label mb-1.5 tracking-wide">Mot de passe</label>
				<input
					type="password"
					value={password}
					onChange={(e) => setPassword(e.target.value)}
					required
					minLength={6}
					className="w-full px-4 py-3 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all"
					placeholder="Min. 6 caractères"
				/>
			</div>

			<div>
				<label className="block text-on-surface-variant text-xs font-label mb-1.5 tracking-wide">Confirmer le mot de passe</label>
				<input
					type="password"
					value={passwordConfirm}
					onChange={(e) => setPasswordConfirm(e.target.value)}
					required
					minLength={6}
					className="w-full px-4 py-3 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all"
					placeholder="Retapez le mot de passe"
				/>
			</div>

			<button
				type="submit"
				disabled={loading}
				className="w-full py-3 bg-primary text-on-primary font-bold uppercase tracking-widest text-sm rounded-lg hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
			>
				{loading ? 'Création...' : 'Créer le compte'}
			</button>

			<p className="text-center text-on-surface-variant/60 text-sm">
				Déjà un compte ?{' '}
				<a href="/login/" className="text-primary hover:brightness-125 transition-all">
					Se connecter
				</a>
			</p>
		</form>
	);
}
