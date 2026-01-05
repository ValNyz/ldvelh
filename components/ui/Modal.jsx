'use client';

import { useEffect, useCallback } from 'react';
import Button from './Button';

export default function Modal({
	isOpen,
	onClose,
	title,
	children,
	showClose = true
}) {
	// Fermer avec Escape
	const handleKeyDown = useCallback((e) => {
		if (e.key === 'Escape') onClose?.();
	}, [onClose]);

	useEffect(() => {
		if (isOpen) {
			document.addEventListener('keydown', handleKeyDown);
			document.body.style.overflow = 'hidden';
		}
		return () => {
			document.removeEventListener('keydown', handleKeyDown);
			document.body.style.overflow = '';
		};
	}, [isOpen, handleKeyDown]);

	if (!isOpen) return null;

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center">
			{/* Backdrop */}
			<div
				className="absolute inset-0 bg-black/60 backdrop-blur-sm"
				onClick={onClose}
			/>

			{/* Modal */}
			<div className="relative z-10 w-full max-w-md mx-4 bg-gray-800 rounded-lg shadow-xl border border-gray-700">
				{/* Header */}
				{(title || showClose) && (
					<div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
						{title && (
							<h3 className="text-lg font-medium text-white">{title}</h3>
						)}
						{showClose && (
							<button
								onClick={onClose}
								className="text-gray-400 hover:text-white transition-colors"
							>
								<svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
									<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						)}
					</div>
				)}

				{/* Content */}
				<div className="p-4">
					{children}
				</div>
			</div>
		</div>
	);
}

/**
 * Modal de confirmation
 */
export function ConfirmModal({
	isOpen,
	onClose,
	onConfirm,
	title = 'Confirmer',
	message,
	confirmText = 'Confirmer',
	cancelText = 'Annuler',
	variant = 'danger'
}) {
	return (
		<Modal isOpen={isOpen} onClose={onClose} title={title}>
			<p className="text-gray-300 mb-6">{message}</p>
			<div className="flex justify-end gap-3">
				<Button variant="secondary" onClick={onClose}>
					{cancelText}
				</Button>
				<Button variant={variant} onClick={onConfirm}>
					{confirmText}
				</Button>
			</div>
		</Modal>
	);
}
