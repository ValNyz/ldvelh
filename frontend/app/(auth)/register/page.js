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
		if (typeof window !== 'undefined') window.location.href = '/';
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
			window.location.href = '/';
		} catch {
			// Error handled by useAuth
		} finally {
			setLoading(false);
		}
	};

	return (
		<form onSubmit={handleSubmit} className="bg-gray-900 rounded-xl p-6 space-y-4 border border-gray-800">
			<h2 className="text-xl font-semibold text-white">Creer un compte</h2>

			{displayError && (
				<div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-2 text-red-400 text-sm">
					{displayError}
				</div>
			)}

			<div>
				<label className="block text-gray-400 text-sm mb-1">Email</label>
				<input
					type="email"
					value={email}
					onChange={(e) => setEmail(e.target.value)}
					required
					autoFocus
					className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
					placeholder="you@example.com"
				/>
			</div>

			<div>
				<label className="block text-gray-400 text-sm mb-1">Nom d'affichage <span className="text-gray-600">(optionnel)</span></label>
				<input
					type="text"
					value={displayName}
					onChange={(e) => setDisplayName(e.target.value)}
					className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
					placeholder="Votre pseudo"
				/>
			</div>

			<div>
				<label className="block text-gray-400 text-sm mb-1">Mot de passe</label>
				<input
					type="password"
					value={password}
					onChange={(e) => setPassword(e.target.value)}
					required
					minLength={6}
					className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
					placeholder="Min. 6 caracteres"
				/>
			</div>

			<div>
				<label className="block text-gray-400 text-sm mb-1">Confirmer le mot de passe</label>
				<input
					type="password"
					value={passwordConfirm}
					onChange={(e) => setPasswordConfirm(e.target.value)}
					required
					minLength={6}
					className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
					placeholder="Retapez le mot de passe"
				/>
			</div>

			<button
				type="submit"
				disabled={loading}
				className="w-full py-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors"
			>
				{loading ? 'Creation...' : 'Creer le compte'}
			</button>

			<p className="text-center text-gray-500 text-sm">
				Deja un compte ?{' '}
				<a href="/login/" className="text-purple-400 hover:text-purple-300 transition-colors">
					Se connecter
				</a>
			</p>
		</form>
	);
}
