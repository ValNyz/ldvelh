'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../lib/api';

const TOKEN_KEY = 'ldvelh-auth-token';
const USER_KEY = 'ldvelh-auth-user';
const REFRESH_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

/**
 * Auth state management hook.
 * Handles login, register, logout, token validation, and silent refresh.
 */
export function useAuth() {
	const [user, setUser] = useState(null);
	const [token, setToken] = useState(null);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState(null);
	const refreshTimerRef = useRef(null);

	// Silent token refresh — issues a fresh JWT if current is still valid
	const refreshToken = useCallback(async () => {
		const currentToken = localStorage.getItem(TOKEN_KEY);
		if (!currentToken) return;
		try {
			const data = await api.post('/auth/refresh');
			localStorage.setItem(TOKEN_KEY, data.token);
			setToken(data.token);
		} catch {
			// Token invalid/expired — 401 handler in api.js will redirect
		}
	}, []);

	// Restore session from localStorage on mount
	useEffect(() => {
		const storedToken = localStorage.getItem(TOKEN_KEY);
		const storedUser = localStorage.getItem(USER_KEY);

		if (!storedToken) {
			setIsLoading(false);
			return;
		}

		// Set initial state from localStorage
		setToken(storedToken);
		if (storedUser) {
			try {
				setUser(JSON.parse(storedUser));
			} catch { /* ignore */ }
		}

		// Validate token with /auth/me, then refresh it
		api.get('/auth/me')
			.then(data => {
				setUser(data.user);
				localStorage.setItem(USER_KEY, JSON.stringify(data.user));
				// Refresh token on mount to extend expiry
				return api.post('/auth/refresh');
			})
			.then(data => {
				localStorage.setItem(TOKEN_KEY, data.token);
				setToken(data.token);
			})
			.catch(() => {
				localStorage.removeItem(TOKEN_KEY);
				localStorage.removeItem(USER_KEY);
				setToken(null);
				setUser(null);
			})
			.finally(() => setIsLoading(false));
	}, []);

	// Periodic token refresh while authenticated
	useEffect(() => {
		if (!token) {
			if (refreshTimerRef.current) {
				clearInterval(refreshTimerRef.current);
				refreshTimerRef.current = null;
			}
			return;
		}
		refreshTimerRef.current = setInterval(refreshToken, REFRESH_INTERVAL_MS);
		return () => {
			if (refreshTimerRef.current) {
				clearInterval(refreshTimerRef.current);
				refreshTimerRef.current = null;
			}
		};
	}, [token, refreshToken]);

	const login = useCallback(async (identifier, password) => {
		setError(null);
		try {
			const data = await api.post('/auth/login', { identifier, password });
			localStorage.setItem(TOKEN_KEY, data.token);
			localStorage.setItem(USER_KEY, JSON.stringify(data.user));
			setToken(data.token);
			setUser(data.user);
			return data;
		} catch (e) {
			setError(e.message);
			throw e;
		}
	}, []);

	const register = useCallback(async (email, password, passwordConfirm, displayName) => {
		setError(null);
		try {
			const data = await api.post('/auth/register', {
				email,
				password,
				password_confirm: passwordConfirm,
				display_name: displayName || null,
			});
			localStorage.setItem(TOKEN_KEY, data.token);
			localStorage.setItem(USER_KEY, JSON.stringify(data.user));
			setToken(data.token);
			setUser(data.user);
			return data;
		} catch (e) {
			setError(e.message);
			throw e;
		}
	}, []);

	const logout = useCallback(() => {
		localStorage.removeItem(TOKEN_KEY);
		localStorage.removeItem(USER_KEY);
		setToken(null);
		setUser(null);
	}, []);

	const clearError = useCallback(() => setError(null), []);

	return {
		user,
		token,
		isAuthenticated: !!token && !!user,
		isLoading,
		login,
		register,
		logout,
		error,
		clearError,
	};
}
