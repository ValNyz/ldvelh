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
		<form onSubmit={handleSubmit} className="bg-gray-900 rounded-xl p-6 space-y-4 border border-gray-800">
			<h2 className="text-xl font-semibold text-white">Connexion</h2>

			{error && (
				<div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-2 text-red-400 text-sm">
					{error}
				</div>
			)}

			<div>
				<label className="block text-gray-400 text-sm mb-1">Email ou nom d'utilisateur</label>
				<input
					type="text"
					value={identifier}
					onChange={(e) => setIdentifier(e.target.value)}
					required
					autoFocus
					className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent"
					placeholder="you@example.com ou pseudo"
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

			<button
				type="submit"
				disabled={loading}
				className="w-full py-2.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-white font-medium transition-colors"
			>
				{loading ? 'Connexion...' : 'Se connecter'}
			</button>

			<p className="text-center text-gray-500 text-sm">
				Pas de compte ?{' '}
				<a href="/register/" className="text-purple-400 hover:text-purple-300 transition-colors">
					Creer un compte
				</a>
			</p>
		</form>
	);
}
