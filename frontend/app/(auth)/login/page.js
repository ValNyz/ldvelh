'use client';

import { useState } from 'react';
import { useAuthContext } from '../../../lib/AuthContext';

export default function LoginPage() {
	const { login, error, clearError, isAuthenticated } = useAuthContext();
	const [identifier, setIdentifier] = useState('');
	const [password, setPassword] = useState('');
	const [loading, setLoading] = useState(false);

	// Redirect if already authenticated
	if (isAuthenticated) {
		if (typeof window !== 'undefined') window.location.href = '/game';
		return null;
	}

	const handleSubmit = async (e) => {
		e.preventDefault();
		clearError();
		setLoading(true);
		try {
			await login(identifier, password);
			window.location.href = '/game';
		} catch {
			// Error handled by useAuth
		} finally {
			setLoading(false);
		}
	};

	return (
		<form onSubmit={handleSubmit} className="bg-surface border border-outline-variant/20 rounded-xl p-8 space-y-5 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
			<h2 className="text-xl font-headline font-semibold text-on-surface">Connexion</h2>

			{error && (
				<div className="bg-error/8 border-l-[3px] border-error rounded-r-lg px-4 py-3 text-error text-sm">
					{error}
				</div>
			)}

			<div>
				<label className="block text-on-surface-variant text-xs font-label mb-1.5 tracking-wide">Email ou nom d&apos;utilisateur</label>
				<input
					type="text"
					value={identifier}
					onChange={(e) => setIdentifier(e.target.value)}
					required
					autoFocus
					className="w-full px-4 py-3 bg-surface-container border border-outline-variant/30 rounded-lg text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-2 focus:ring-primary/40 focus:border-primary transition-all"
					placeholder="you@example.com ou pseudo"
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

			<button
				type="submit"
				disabled={loading}
				className="w-full py-3 bg-primary text-on-primary font-bold uppercase tracking-widest text-sm rounded-lg hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
			>
				{loading ? 'Connexion...' : 'Se connecter'}
			</button>

			<p className="text-center text-on-surface-variant/60 text-sm">
				Pas de compte ?{' '}
				<a href="/register/" className="text-primary hover:brightness-125 transition-all">
					Créer un compte
				</a>
			</p>
		</form>
	);
}
