// 'use client';

import { useRef, useEffect, useCallback } from 'react';
import Message, { MessageEditForm } from './Message';
import Button from '../ui/Button';

export default function MessageList({
	messages,
	loading,
	saving,
	error,
	fontSize,
	editingIndex,
	onEdit,
	onCancelEdit,
	onSubmitEdit,
	onRegenerate,
	onCancel,
	onClearError,
	onRetry,
	tooltipMap  // NOUVEAU
}) {
	const containerRef = useRef(null);
	const endRef = useRef(null);
	const userScrolledUp = useRef(false);

	// Auto-scroll vers le bas sauf si l'utilisateur a scrollé
	useEffect(() => {
		if (!userScrolledUp.current) {
			endRef.current?.scrollIntoView({ behavior: 'smooth' });
		}
	}, [messages]);

	const handleScroll = useCallback((e) => {
		const { scrollTop, scrollHeight, clientHeight } = e.target;
		userScrolledUp.current = scrollHeight - scrollTop - clientHeight > 50;
	}, []);

	// Reset scroll behavior quand on envoie un message
	const resetScroll = useCallback(() => {
		userScrolledUp.current = false;
	}, []);

	// Message vide
	if (messages.length === 0 && !loading) {
		return (
			<div className="flex-1 flex items-center justify-center p-4">
				<div className="text-center text-gray-500">
					<p className="text-lg mb-2">Bienvenue dans LDVELH</p>
					<p className="text-sm">Tape "Commencer" pour lancer l'aventure</p>
				</div>
			</div>
		);
	}

	const isStreaming = messages.some(m => m.streaming);

	return (
		<div
			ref={containerRef}
			onScroll={handleScroll}
			className="flex-1 overflow-y-auto p-4"
		>
			{messages.map((msg, index) => (
				editingIndex === index ? (
					<MessageEditForm
						key={`edit-${index}`}
						content={msg.content}
						fontSize={fontSize}
						onSubmit={(content) => {
							resetScroll();
							onSubmitEdit(content);
						}}
						onCancel={onCancelEdit}
					/>
				) : (
					<Message
						key={index}
						message={msg}
						index={index}
						isLast={index === messages.length - 1}
						isLoading={loading}
						fontSize={fontSize}
						onEdit={msg.role === 'user' && !loading ? onEdit : null}
						onRegenerate={!loading ? onRegenerate : null}
						tooltipMap={tooltipMap}  // NOUVEAU : passer la map
					/>
				)
			))}

			{/* Indicateur de chargement */}
			{loading && !isStreaming && (
				<LoadingIndicator onCancel={onCancel} />
			)}

			{/* Bouton annuler pendant streaming */}
			{loading && isStreaming && (
				<div className="flex justify-start mb-4">
					<Button
						variant="danger"
						size="sm"
						onClick={onCancel}
					>
						✕ Annuler
					</Button>
				</div>
			)}

			{/* Indicateur de sauvegarde */}
			{saving && (
				<div className="text-center text-gray-500 text-sm py-2">
					<span className="inline-flex items-center gap-2">
						<svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
							<circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
							<path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
						</svg>
						Sauvegarde...
					</span>
				</div>
			)}

			{/* Erreur */}
			{error && (
				<ErrorDisplay
					error={error}
					onClear={onClearError}
					onRetry={onRetry}
				/>
			)}

			<div ref={endRef} />
		</div>
	);
}

/**
 * Indicateur de chargement
 */
function LoadingIndicator({ onCancel }) {
	return (
		<div className="flex items-center gap-3 text-gray-400 mb-4">
			<div className="flex gap-1">
				<span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
				<span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
				<span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
			</div>
			<span className="text-sm italic">En cours...</span>
			<Button variant="danger" size="sm" onClick={onCancel}>
				✕ Annuler
			</Button>
		</div>
	);
}

/**
 * Affichage d'erreur
 */
function ErrorDisplay({ error, onClear, onRetry }) {
	const errorObj = typeof error === 'string' ? { message: error } : error;

	return (
		<div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-4">
			<div className="flex items-start gap-3">
				<svg className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				<div className="flex-1">
					<p className="text-red-400 font-medium">{errorObj.message}</p>
					{errorObj.details && (
						<p className="text-red-300/70 text-sm mt-1">
							{Array.isArray(errorObj.details)
								? errorObj.details.join(', ')
								: errorObj.details
							}
						</p>
					)}
					<div className="flex gap-2 mt-3">
						{errorObj.recoverable !== false && onRetry && (
							<Button variant="danger" size="sm" onClick={onRetry}>
								Réessayer
							</Button>
						)}
						<Button variant="ghost" size="sm" onClick={onClear}>
							Fermer
						</Button>
					</div>
				</div>
			</div>
		</div>
	);
}
