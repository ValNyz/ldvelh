'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import Button from '../ui/Button';

export default function InputArea({
	onSend,
	disabled,
	fontSize = 14,
	placeholder = "Ton action... (Ctrl+Entrée pour envoyer)"
}) {
	const [input, setInput] = useState('');
	const textareaRef = useRef(null);

	// Auto-resize du textarea
	useEffect(() => {
		if (textareaRef.current) {
			textareaRef.current.style.height = 'auto';
			textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
		}
	}, [input]);

	const handleSend = useCallback(() => {
		if (!input.trim() || disabled) return;
		onSend(input.trim());
		setInput('');
	}, [input, disabled, onSend]);

	const handleKeyDown = useCallback((e) => {
		if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			handleSend();
		}
	}, [handleSend]);

	return (
		<div className="p-4 bg-gray-800 border-t border-gray-700">
			<div className="flex gap-2 items-end">
				<textarea
					ref={textareaRef}
					value={input}
					onChange={(e) => setInput(e.target.value)}
					onKeyDown={handleKeyDown}
					placeholder={placeholder}
					disabled={disabled}
					rows={1}
					className="
            flex-1 px-4 py-2.5
            bg-gray-700 border border-gray-600 rounded-lg
            text-white placeholder-gray-400
            resize-none
            focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors
          "
					style={{
						fontSize,
						minHeight: '44px',
						maxHeight: '200px'
					}}
				/>
				<Button
					onClick={handleSend}
					disabled={disabled || !input.trim()}
					className="h-11"
				>
					<SendIcon className="w-5 h-5" />
				</Button>
			</div>

			<div className="mt-1.5 text-xs text-gray-500">
				Entrée = nouvelle ligne • Ctrl+Entrée = envoyer
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
