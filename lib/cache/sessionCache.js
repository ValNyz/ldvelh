/**
 * Cache en mémoire pour LDVELH
 * Cache LRU par partie avec TTL configurable
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
	TTL: {
		protagoniste: 5 * 60 * 1000,      // 5 min
		ia: 10 * 60 * 1000,               // 10 min
		stats: 30 * 1000,                 // 30 sec
		relations: 60 * 1000,             // 1 min
		personnages: 2 * 60 * 1000,       // 2 min
		lieux: 5 * 60 * 1000,             // 5 min
		inventaire: 30 * 1000,            // 30 sec
		scene: 30 * 1000,                 // 30 sec
		evenements: 60 * 1000,            // 1 min
		default: 60 * 1000                // 1 min
	},
	MAX_ENTRIES_PER_PARTIE: 100,
	MAX_PARTIES: 10
};

// ============================================================================
// STORAGE
// ============================================================================

// Map: partieId -> Map<cacheKey, { data, expiry, hits }>
const cacheStore = new Map();

// LRU tracking
const partiesAccess = [];

// Stats globales
const globalStats = {
	hits: 0,
	misses: 0,
	evictions: 0
};

// ============================================================================
// HELPERS INTERNES
// ============================================================================

function getCacheKey(type, identifiers) {
	if (identifiers.length === 0) return type;
	return `${type}:${identifiers.join(':')}`;
}

function isExpired(entry) {
	return !entry || Date.now() > entry.expiry;
}

function getPartieCache(partieId) {
	if (!cacheStore.has(partieId)) {
		// Éviction LRU si trop de parties
		if (cacheStore.size >= CONFIG.MAX_PARTIES) {
			const oldestPartie = partiesAccess.shift();
			if (oldestPartie && cacheStore.has(oldestPartie)) {
				cacheStore.delete(oldestPartie);
				globalStats.evictions++;
				console.log(`[CACHE] Éviction partie LRU: ${oldestPartie.slice(0, 8)}...`);
			}
		}
		cacheStore.set(partieId, new Map());
	}

	// Mettre à jour LRU
	const idx = partiesAccess.indexOf(partieId);
	if (idx > -1) partiesAccess.splice(idx, 1);
	partiesAccess.push(partieId);

	return cacheStore.get(partieId);
}

function cleanExpiredEntries(cache) {
	let cleaned = 0;
	for (const [key, entry] of cache) {
		if (isExpired(entry)) {
			cache.delete(key);
			cleaned++;
		}
	}
	return cleaned;
}

// ============================================================================
// API PUBLIQUE - LECTURE
// ============================================================================

/**
 * Récupère une valeur du cache
 * @param {string} partieId 
 * @param {string} type - Type de donnée (pour TTL)
 * @param {...string} identifiers - Identifiants additionnels
 * @returns {any|null}
 */
export function cacheGet(partieId, type, ...identifiers) {
	const cache = cacheStore.get(partieId);
	if (!cache) {
		globalStats.misses++;
		return null;
	}

	const key = getCacheKey(type, identifiers);
	const entry = cache.get(key);

	if (isExpired(entry)) {
		cache.delete(key);
		globalStats.misses++;
		return null;
	}

	entry.hits++;
	globalStats.hits++;
	return entry.data;
}

/**
 * Vérifie si une clé existe et n'est pas expirée
 */
export function cacheHas(partieId, type, ...identifiers) {
	const cache = cacheStore.get(partieId);
	if (!cache) return false;

	const key = getCacheKey(type, identifiers);
	const entry = cache.get(key);

	return !isExpired(entry);
}

// ============================================================================
// API PUBLIQUE - ÉCRITURE
// ============================================================================

/**
 * Stocke une valeur dans le cache
 * @param {string} partieId 
 * @param {string} type - Type de donnée (pour TTL)
 * @param {any} data - Données à cacher
 * @param {...string} identifiers - Identifiants additionnels
 */
export function cacheSet(partieId, type, data, ...identifiers) {
	const cache = getPartieCache(partieId);
	const key = getCacheKey(type, identifiers);
	const ttl = CONFIG.TTL[type] || CONFIG.TTL.default;

	// Nettoyage si cache trop grand
	if (cache.size >= CONFIG.MAX_ENTRIES_PER_PARTIE) {
		const cleaned = cleanExpiredEntries(cache);
		if (cleaned === 0 && cache.size >= CONFIG.MAX_ENTRIES_PER_PARTIE) {
			// Supprimer l'entrée la moins accédée
			let minHits = Infinity;
			let minKey = null;
			for (const [k, v] of cache) {
				if (v.hits < minHits) {
					minHits = v.hits;
					minKey = k;
				}
			}
			if (minKey) {
				cache.delete(minKey);
				globalStats.evictions++;
			}
		}
	}

	cache.set(key, {
		data,
		expiry: Date.now() + ttl,
		hits: 0,
		createdAt: Date.now()
	});
}

// ============================================================================
// API PUBLIQUE - INVALIDATION
// ============================================================================

/**
 * Invalide une entrée spécifique
 */
export function cacheInvalidate(partieId, type, ...identifiers) {
	const cache = cacheStore.get(partieId);
	if (!cache) return false;

	const key = getCacheKey(type, identifiers);
	return cache.delete(key);
}

/**
 * Invalide toutes les entrées d'un type
 */
export function cacheInvalidateType(partieId, type) {
	const cache = cacheStore.get(partieId);
	if (!cache) return 0;

	let count = 0;
	for (const key of cache.keys()) {
		if (key === type || key.startsWith(`${type}:`)) {
			cache.delete(key);
			count++;
		}
	}
	return count;
}

/**
 * Invalide tout le cache d'une partie
 */
export function cacheInvalidatePartie(partieId) {
	const deleted = cacheStore.delete(partieId);
	const idx = partiesAccess.indexOf(partieId);
	if (idx > -1) partiesAccess.splice(idx, 1);
	return deleted;
}

/**
 * Vide tout le cache global
 */
export function cacheClear() {
	const count = cacheStore.size;
	cacheStore.clear();
	partiesAccess.length = 0;
	return count;
}

// ============================================================================
// WRAPPER CACHE-ASIDE
// ============================================================================

/**
 * Pattern cache-aside : récupère du cache ou exécute la fonction
 * @param {string} partieId 
 * @param {string} type - Type de donnée (pour TTL)
 * @param {Function} fetchFn - Fonction async qui récupère les données
 * @param {...string} identifiers - Identifiants additionnels
 * @returns {Promise<any>}
 */
export async function withCache(partieId, type, fetchFn, ...identifiers) {
	// 1. Vérifier le cache
	const cached = cacheGet(partieId, type, ...identifiers);
	if (cached !== null) {
		return cached;
	}

	// 2. Fetch depuis la source
	const data = await fetchFn();

	// 3. Stocker en cache (sauf null/undefined)
	if (data !== null && data !== undefined) {
		cacheSet(partieId, type, data, ...identifiers);
	}

	return data;
}

/**
 * Comme withCache mais avec un fallback si fetch échoue
 */
export async function withCacheOrFallback(partieId, type, fetchFn, fallback, ...identifiers) {
	try {
		return await withCache(partieId, type, fetchFn, ...identifiers);
	} catch (e) {
		console.warn(`[CACHE] Fetch échoué pour ${type}, fallback utilisé:`, e.message);
		return fallback;
	}
}

// ============================================================================
// STATS & DEBUG
// ============================================================================

/**
 * Retourne les statistiques du cache
 */
export function cacheStats() {
	const stats = {
		global: { ...globalStats },
		hitRate: globalStats.hits + globalStats.misses > 0
			? (globalStats.hits / (globalStats.hits + globalStats.misses) * 100).toFixed(1) + '%'
			: 'N/A',
		parties: cacheStore.size,
		totalEntries: 0,
		entriesByPartie: {}
	};

	for (const [partieId, cache] of cacheStore) {
		const shortId = partieId.slice(0, 8);
		stats.entriesByPartie[shortId] = cache.size;
		stats.totalEntries += cache.size;
	}

	return stats;
}

/**
 * Reset les stats (pour tests)
 */
export function cacheResetStats() {
	globalStats.hits = 0;
	globalStats.misses = 0;
	globalStats.evictions = 0;
}

/**
 * Debug : affiche le contenu du cache
 */
export function cacheDebug(partieId) {
	const cache = cacheStore.get(partieId);
	if (!cache) return { exists: false };

	const entries = [];
	for (const [key, entry] of cache) {
		entries.push({
			key,
			expired: isExpired(entry),
			hits: entry.hits,
			age: Math.round((Date.now() - entry.createdAt) / 1000) + 's',
			ttlRemaining: Math.round((entry.expiry - Date.now()) / 1000) + 's'
		});
	}

	return { exists: true, entries };
}
