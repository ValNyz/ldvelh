/**
 * Gestion d'erreurs centralisée pour LDVELH
 */

import { ERROR_CODES } from './constants.js';

// ============================================================================
// CLASSES D'ERREURS
// ============================================================================

export class LDVELHError extends Error {
	constructor(message, code, details = null) {
		super(message);
		this.name = 'LDVELHError';
		this.code = code;
		this.details = details;
		this.timestamp = new Date().toISOString();
	}

	toJSON() {
		return {
			error: this.message,
			code: this.code,
			details: this.details,
			timestamp: this.timestamp
		};
	}

	getStatusCode() {
		switch (this.code) {
			case ERROR_CODES.NOT_FOUND: return 404;
			case ERROR_CODES.VALIDATION_ERROR: return 400;
			case ERROR_CODES.CLAUDE_API_ERROR: return 502;
			default: return 500;
		}
	}
}

export class DatabaseError extends LDVELHError {
	constructor(message, operation, originalError) {
		super(message, 'DB_ERROR', {
			operation,
			original: originalError?.message,
			code: originalError?.code
		});
		this.name = 'DatabaseError';
	}
}

export class ValidationError extends LDVELHError {
	constructor(message, fields) {
		super(message, 'VALIDATION_ERROR', { fields });
		this.name = 'ValidationError';
	}
}

export class EntityNotFoundError extends LDVELHError {
	constructor(entityType, identifier) {
		super(`${entityType} non trouvé: ${identifier}`, 'NOT_FOUND', {
			entityType,
			identifier
		});
		this.name = 'EntityNotFoundError';
	}
}

export class ClaudeAPIError extends LDVELHError {
	constructor(message, statusCode, rawResponse) {
		super(message, 'CLAUDE_API_ERROR', {
			statusCode,
			rawResponse: rawResponse?.slice?.(0, 500)
		});
		this.name = 'ClaudeAPIError';
	}
}

export class StreamError extends LDVELHError {
	constructor(message, phase) {
		super(message, 'STREAM_ERROR', { phase });
		this.name = 'StreamError';
	}
}

// ============================================================================
// WRAPPERS SUPABASE
// ============================================================================

/**
 * Wrapper pour opérations Supabase critiques (throw si erreur)
 * @param {Promise} operation - Promesse Supabase
 * @param {string} operationName - Nom pour les logs
 * @returns {Promise<any>} - Les données
 * @throws {DatabaseError}
 */
export async function dbOperation(operation, operationName) {
	const { data, error } = await operation;

	if (error) {
		console.error(`[DB] Erreur ${operationName}:`, error);
		throw new DatabaseError(`Échec ${operationName}`, operationName, error);
	}

	return data;
}

/**
 * Wrapper pour opérations non-critiques (retourne fallback si erreur)
 * @param {Promise} operation - Promesse Supabase
 * @param {string} operationName - Nom pour les logs
 * @param {any} fallback - Valeur par défaut si erreur
 * @returns {Promise<any>} - Les données ou le fallback
 */
export async function dbOperationWithFallback(operation, operationName, fallback) {
	try {
		const { data, error } = await operation;

		if (error) {
			console.warn(`[DB] ${operationName} échoué, fallback:`, error.message);
			return fallback;
		}

		return data ?? fallback;
	} catch (e) {
		console.warn(`[DB] ${operationName} exception, fallback:`, e.message);
		return fallback;
	}
}

/**
 * Wrapper pour opérations qui peuvent retourner null légitimement
 * @param {Promise} operation - Promesse Supabase
 * @param {string} operationName - Nom pour les logs
 * @returns {Promise<any|null>} - Les données ou null
 */
export async function dbOperationNullable(operation, operationName) {
	try {
		const { data, error } = await operation;

		if (error) {
			// PGRST116 = "no rows returned" - pas une vraie erreur
			if (error.code === 'PGRST116') {
				return null;
			}
			console.error(`[DB] ${operationName}:`, error);
			throw new DatabaseError(`Échec ${operationName}`, operationName, error);
		}

		return data;
	} catch (e) {
		if (e instanceof LDVELHError) throw e;
		console.error(`[DB] ${operationName} exception:`, e);
		throw new DatabaseError(`Exception ${operationName}`, operationName, e);
	}
}

// ============================================================================
// HANDLER D'ERREUR HTTP
// ============================================================================

/**
 * Convertit une erreur en Response HTTP appropriée
 * @param {Error} error 
 * @returns {Response}
 */
export function errorToResponse(error) {
	console.error('[ERROR]', error);

	// Erreurs métier connues
	if (error instanceof LDVELHError) {
		return Response.json(error.toJSON(), {
			status: error.getStatusCode()
		});
	}

	// Erreur Anthropic API
	if (error.status && error.error) {
		return Response.json({
			error: 'Erreur API Claude',
			code: 'CLAUDE_API_ERROR',
			details: error.error?.message || 'Erreur inconnue'
		}, { status: 502 });
	}

	// Erreur inconnue
	return Response.json({
		error: 'Erreur serveur interne',
		code: 'INTERNAL_ERROR',
		details: process.env.NODE_ENV === 'development' ? error.message : null
	}, { status: 500 });
}

// ============================================================================
// UTILITAIRES
// ============================================================================

/**
 * Log structuré pour debug
 */
export function logError(context, error, extra = {}) {
	console.error(`[${context}]`, {
		message: error.message,
		code: error.code,
		stack: process.env.NODE_ENV === 'development' ? error.stack : undefined,
		...extra
	});
}
