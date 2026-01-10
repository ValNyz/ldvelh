'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import Button from '../ui/Button';

export default function InputArea({
	onSend,
	disabled = false,
	disableInput = false,
	disableSend = false,
	fontSize = 14,
	placeholder = "Ton action... (Ctrl+Entrée pour envoyer)"
}) {
	const [input, setInput] = useState('');
	const textareaRef = useRef(null);

	// Calcul des états réels
	const inputDisabled = disabled || disableInput;
	const sendDisabled = disabled || disableSend || !input.trim();

	// Auto-resize du textarea
	useEffect(() => {
		if (textareaRef.current) {
			textareaRef.current.style.height = 'auto';
			textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 400) + 'px';
		}
	}, [input]);

	const handleSend = useCallback(() => {
		if (!input.trim() || sendDisabled) return;
		onSend(input.trim());
		setInput('');
	}, [input, sendDisabled, onSend]);

	const handleKeyDown = useCallback((e) => {
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			handleSend();
		}
	}, [handleSend]);

	// Placeholder dynamique selon l'état
	const currentPlaceholder = disableSend && !disableInput
		? "Prépare ta prochaine action... (mise à jour en cours)"
		: placeholder;

	return (
		<div className="p-4 bg-gray-800 border-t border-gray-700">
			<div className="flex gap-2 items-end">
				<textarea
					ref={textareaRef}
					value={input}
					onChange={(e) => setInput(e.target.value)}
					onKeyDown={handleKeyDown}
					placeholder={currentPlaceholder}
					disabled={inputDisabled}
					rows={1}
					className={`
						flex-1 px-4 py-2.5
						bg-gray-700 border border-gray-600 rounded-lg
						text-white placeholder-gray-400
						resize-none
						focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
						transition-colors
						${inputDisabled ? 'opacity-50 cursor-not-allowed' : ''}
					`}
					style={{
						fontSize,
						minHeight: '44px',
						maxHeight: '200px'
					}}
				/>
				<Button
					onClick={handleSend}
					disabled={sendDisabled}
					className="h-11"
					title={disableSend && !disabled ? "Mise à jour en cours..." : "Envoyer"}
				>
					{disableSend && !disableInput ? (
						<LoadingIcon className="w-5 h-5 animate-spin" />
					) : (
						<SendIcon className="w-5 h-5" />
					)}
				</Button>
			</div>

			<div className="mt-1.5 text-xs text-gray-500">
				{disableSend && !disableInput ? (
					<span className="text-amber-500">⏳ Mise à jour du monde en cours...</span>
				) : (
					<>Entrée = nouvelle ligne • Ctrl+Entrée = envoyer</>
				)}
			</div>
		</div>
	);
}

function SendIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
		</svg>
	);
}

function LoadingIcon({ className }) {
	return (
		<svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
		</svg>
	);
}
