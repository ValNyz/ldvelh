/**
 * LDVELH - API Client Configuration
 * 
 * Centralise les appels au backend Python FastAPI
 */

// URL du backend Python - À configurer via env
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Construit l'URL complète de l'API
 */
export function apiUrl(path) {
	// Si le path commence déjà par /api, ne pas le doubler
	const cleanPath = path.startsWith('/api') ? path : `/api${path}`;
	return `${API_BASE_URL}${cleanPath}`;
}

/**
 * Client API avec gestion d'erreurs
 */
export const api = {
	/**
	 * GET request
	 */
	async get(path, params = {}) {
		const url = new URL(apiUrl(path));
		Object.entries(params).forEach(([k, v]) => {
			if (v !== undefined && v !== null) {
				url.searchParams.append(k, v);
			}
		});

		const res = await fetch(url.toString());
		if (!res.ok) {
			const error = await res.json().catch(() => ({ error: res.statusText }));
			throw new Error(error.error || error.detail || 'API Error');
		}
		return res.json();
	},

	/**
	 * POST request
	 */
	async post(path, body = {}) {
		const res = await fetch(apiUrl(path), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		});

		if (!res.ok) {
			const error = await res.json().catch(() => ({ error: res.statusText }));
			throw new Error(error.error || error.detail || 'API Error');
		}
		return res.json();
	},

	/**
	 * DELETE request
	 */
	async delete(path) {
		const res = await fetch(apiUrl(path), { method: 'DELETE' });
		if (!res.ok) {
			const error = await res.json().catch(() => ({ error: res.statusText }));
			throw new Error(error.error || error.detail || 'API Error');
		}
		return res.json();
	},

	/**
	 * PATCH request
	 */
	async patch(path, body = {}) {
		const res = await fetch(apiUrl(path), {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		});

		if (!res.ok) {
			const error = await res.json().catch(() => ({ error: res.statusText }));
			throw new Error(error.error || error.detail || 'API Error');
		}
		return res.json();
	},

	/**
	 * POST avec streaming SSE
	 */
	async stream(path, body = {}, handlers = {}) {
		const { onChunk, onProgress, onDone, onSaved, onError } = handlers;

		const res = await fetch(apiUrl(path), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(body)
		});

		// Si pas de streaming, traiter comme JSON normal
		if (!res.headers.get('content-type')?.includes('text/event-stream')) {
			const data = await res.json();
			if (data.error) {
				onError?.(data.error, data.details);
				return { success: false };
			}
			onDone?.(data.displayText || data.content, data.state);
			return { success: true, data };
		}

		// Traiter le stream SSE
		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let fullJson = '';

		try {
			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				const text = decoder.decode(value, { stream: true });

				for (const line of text.split('\n')) {
					if (!line.startsWith('data: ')) continue;

					try {
						const data = JSON.parse(line.slice(6));

						switch (data.type) {
							case 'chunk':
								onChunk?.(data.content);
								break;
							case 'progress':
								fullJson = data.rawJson || fullJson;
								onProgress?.(fullJson);
								break;
							case 'done':
								onDone?.(data.displayText, data.state);
								break;
							case 'saved':
								onSaved?.();
								break;
							case 'error':
								onError?.(data.error, data.details);
								break;
							case 'warning':
								console.warn('[API] Warning:', data.message);
								break;
						}
					} catch (e) {
						// Ignorer les lignes mal formées
					}
				}
			}

			return { success: true, fullJson };
		} catch (e) {
			if (e.name === 'AbortError') {
				return { success: false, aborted: true };
			}
			onError?.(e.message);
			return { success: false, error: e };
		}
	}
};

// ============================================================================
// API ENDPOINTS
// ============================================================================

export const gamesApi = {
	/**
	 * Liste toutes les parties
	 */
	list: () => api.get('/games'),

	/**
	 * Crée une nouvelle partie
	 */
	create: () => api.post('/games'),

	/**
	 * Charge une partie
	 */
	load: (gameId) => api.get(`/games/${gameId}`),

	/**
	 * Supprime une partie
	 */
	delete: (gameId) => api.delete(`/games/${gameId}`),

	/**
	 * Renomme une partie
	 */
	rename: (gameId, name) => api.patch(`/games/${gameId}`, { name }),

	/**
	 * Rollback à un message
	 */
	rollback: (gameId, fromIndex) => api.post(`/games/${gameId}/rollback`, { fromIndex })
};

export const chatApi = {
	/**
	 * Envoie un message avec streaming
	 */
	send: (gameId, message, handlers) => api.stream('/chat', { gameId, message }, handlers)
};

export const tooltipsApi = {
	/**
	 * Récupère les tooltips pour une partie
	 */
	get: (partieId) => api.get('/tooltips', { partieId })
};
