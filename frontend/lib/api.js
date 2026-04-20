/**
 * LDVELH - API Client Configuration
 *
 * Centralise les appels au backend Python FastAPI
 */

// In production (same-origin via Traefik): NEXT_PUBLIC_API_URL is empty/unset.
// In dev: NEXT_PUBLIC_API_URL=http://localhost:8000
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

/**
 * Build full API URL from a path
 */
export function apiUrl(path) {
	const cleanPath = path.startsWith('/api') ? path : `/api${path}`;
	return `${API_BASE_URL}${cleanPath}`;
}

/**
 * Get auth headers from localStorage (if token exists)
 */
export function getAuthHeaders() {
	if (typeof window === 'undefined') return {};
	const token = localStorage.getItem('ldvelh-auth-token');
	if (!token) return {};
	return { 'Authorization': `Bearer ${token}` };
}

/**
 * Handle 401: attempt one token refresh, then retry the original request.
 * If refresh fails, clear auth and redirect to login.
 */
let _refreshPromise = null;

async function attemptRefreshAndRetry(method, url, options) {
	// Coalesce concurrent refresh attempts into one
	if (!_refreshPromise) {
		_refreshPromise = fetch(apiUrl('/auth/refresh'), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
		}).then(async (res) => {
			if (!res.ok) throw new Error('Refresh failed');
			const data = await res.json();
			localStorage.setItem('ldvelh-auth-token', data.token);
			return data.token;
		}).finally(() => {
			_refreshPromise = null;
		});
	}

	try {
		await _refreshPromise;
	} catch {
		// Refresh failed — clear auth and redirect
		localStorage.removeItem('ldvelh-auth-token');
		localStorage.removeItem('ldvelh-auth-user');
		if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
			window.location.href = '/login/';
		}
		throw new Error('Session expired');
	}

	// Retry original request with refreshed token
	const retryOptions = { ...options, headers: { ...options.headers, ...getAuthHeaders() } };
	const res = await fetch(url, retryOptions);
	if (!res.ok) {
		const error = await res.json().catch(() => ({ error: res.statusText }));
		throw new Error(error.error || error.detail || 'API Error');
	}
	return res.json();
}

/**
 * Core request function with 401 retry logic.
 * Skips refresh for auth endpoints to avoid infinite loops.
 */
async function request(method, path, body = null) {
	const isFullUrl = typeof path === 'string' && path.startsWith('http');
	const url = isFullUrl ? path : apiUrl(path);
	const isAuthEndpoint = url.includes('/auth/login') ||
		url.includes('/auth/register') ||
		url.includes('/auth/refresh');

	const options = { method, headers: { ...getAuthHeaders() } };
	if (body !== null) {
		options.headers['Content-Type'] = 'application/json';
		options.body = JSON.stringify(body);
	}

	const res = await fetch(url, options);

	if (res.status === 401 && !isAuthEndpoint) {
		return attemptRefreshAndRetry(method, url, options);
	}

	if (!res.ok) {
		const error = await res.json().catch(() => ({ error: res.statusText }));
		throw new Error(error.error || error.detail || 'API Error');
	}
	return res.json();
}

/**
 * API client with auth headers
 */
export const api = {
	async get(path, params = {}) {
		const base = apiUrl(path);
		const url = new URL(base, window.location.origin);
		Object.entries(params).forEach(([k, v]) => {
			if (v !== undefined && v !== null) {
				url.searchParams.append(k, v);
			}
		});
		return request('GET', url.toString());
	},
	post: (path, body = {}) => request('POST', path, body),
	delete: (path) => request('DELETE', path),
	patch: (path, body = {}) => request('PATCH', path, body),
};

// ============================================================================
// GAMES API
// ============================================================================

export const gamesApi = {
	list: () => api.get('/games'),
	create: (engine = null) => api.post('/games', engine ? { engine } : {}),
	delete: (gameId) => api.delete(`/games/${gameId}`),
	rename: (gameId, name) => api.patch(`/games/${gameId}`, { gameId, name })
};

// ============================================================================
// STATE API
// ============================================================================

export const stateApi = {
	load: (gameId) => api.get(`/games/${gameId}`),
	getWorld: (gameId) => api.get(`/games/${gameId}/world`),
	rollback: (gameId, messageId) => api.post(`/games/${gameId}/rollback`, { messageId })
};

// ============================================================================
// PREFERENCES API
// ============================================================================

export const preferencesApi = {
	get: () => api.get('/auth/preferences'),
	update: (prefs) => api.patch('/auth/preferences', { preferences: prefs }),
};

// ============================================================================
// TOOLTIPS API
// ============================================================================

export const tooltipsApi = {
	getAnnotations: (gameId) => api.get('/tooltips/annotations', { gameId }),
	getEntity: (gameId, name, entityType) => api.get('/tooltips/entity', { gameId, name, entityType }),
};
