'use client';

import { useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import EntityTooltip from './EntityTooltip';
import { formatTooltip, fuzzyMatchEntity } from '../../lib/js/kg/knowledgeService';

/**
 * Composant Message unique
 */
export default function Message({
	message,
	index,
	isLast,
	isLoading,
	fontSize,
	onEdit,
	onRegenerate,
	tooltipMap  // NOUVEAU
}) {
	const [showActions, setShowActions] = useState(false);
	const isUser = message.role === 'user';
	const isStreaming = message.streaming;

	return (
		<div
			className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}
			onMouseEnter={() => setShowActions(true)}
			onMouseLeave={() => setShowActions(false)}
		>
			<div className={`relative ${isUser ? 'max-w-[80%]' : 'max-w-[95%]'}`}>
				{/* Bulle de message */}
				<div
					className={`
            px-4 py-3 
            ${isUser
							? 'bg-blue-600 rounded-2xl rounded-br-sm'
							: 'bg-gray-800 rounded-2xl rounded-bl-sm'
						}
          `}
				>
					<div style={{ fontSize }}>
						<MarkdownContent
							content={message.content}
							isUser={isUser}
							tooltipMap={tooltipMap}  // NOUVEAU
						/>
					</div>

					{/* Curseur de streaming */}
					{isStreaming && (
						<span className="inline-block w-2 h-4 ml-1 bg-blue-400 animate-cursor-blink" />
					)}
				</div>

				{/* Actions (éditer/regénérer) */}
				<div
					className={`
            absolute -top-2 flex gap-1
            ${isUser ? 'right-0' : 'left-0'}
            transition-opacity duration-200
            ${showActions && !isLoading ? 'opacity-100' : 'opacity-0'}
          `}
				>
					{isUser && onEdit && (
						<ActionButton
							onClick={() => onEdit(index)}
							title="Éditer"
							icon={<EditIcon />}
						/>
					)}
					{!isUser && isLast && onRegenerate && !isStreaming && (
						<ActionButton
							onClick={onRegenerate}
							title="Regénérer"
							icon={<RefreshIcon />}
						/>
					)}
				</div>
			</div>
		</div>
	);
}

/**
 * Rendu Markdown personnalisé avec tooltips
 */
function MarkdownContent({ content, isUser, tooltipMap }) {
	const components = useMemo(() => ({
		p: ({ children }) => (
			<p className="mb-2 last:mb-0">{children}</p>
		),
		strong: ({ children }) => {
			// NOUVEAU : Tooltip sur les éléments en gras
			const text = extractText(children);
			const entityData = tooltipMap ? fuzzyMatchEntity(text, tooltipMap, 70) : null;
			const tooltipData = entityData ? formatTooltip(entityData) : null;

			if (tooltipData && !isUser) {
				return (
					<EntityTooltip data={tooltipData}>
						<strong className="text-blue-400">{children}</strong>
					</EntityTooltip>
				);
			}

			return (
				<strong className={isUser ? 'text-white' : 'text-blue-400'}>
					{children}
				</strong>
			);
		},
		em: ({ children }) => (
			<em className={isUser ? 'text-blue-100' : 'text-purple-300'}>
				{children}
			</em>
		),
		ul: ({ children }) => (
			<ul className="list-disc list-inside my-2 space-y-1">{children}</ul>
		),
		ol: ({ children }) => (
			<ol className="list-decimal list-inside my-2 space-y-1">{children}</ol>
		),
		li: ({ children }) => (
			<li className="ml-2">{children}</li>
		),
		code: ({ inline, children }) => inline ? (
			<code className={`px-1.5 py-0.5 rounded text-sm ${isUser ? 'bg-blue-700' : 'bg-gray-700'}`}>
				{children}
			</code>
		) : (
			<pre className={`p-3 rounded my-2 overflow-x-auto ${isUser ? 'bg-blue-700' : 'bg-gray-700'}`}>
				<code className="text-sm">{children}</code>
			</pre>
		),
		blockquote: ({ children }) => (
			<blockquote className="border-l-2 border-blue-400 pl-3 my-2 text-gray-400 italic">
				{children}
			</blockquote>
		),
	}), [isUser, tooltipMap]);

	return (
		<ReactMarkdown components={components}>
			{content}
		</ReactMarkdown>
	);
}

/**
 * Extrait le texte brut des children React
 */
function extractText(children) {
	if (typeof children === 'string') return children;
	if (Array.isArray(children)) {
		return children.map(extractText).join('');
	}
	if (children?.props?.children) {
		return extractText(children.props.children);
	}
	return '';
}

/**
 * Bouton d'action sur message
 */
function ActionButton({ onClick, title, icon }) {
	return (
		<button
			onClick={onClick}
			title={title}
			className="p-1.5 bg-gray-700 hover:bg-gray-600 rounded text-gray-400 hover:text-white transition-colors"
		>
			{icon}
		</button>
	);
}

/**
 * Formulaire d'édition inline
 */
export function MessageEditForm({ content, onSubmit, onCancel, fontSize }) {
	const [editedContent, setEditedContent] = useState(content);

	const handleSubmit = () => {
		if (editedContent.trim()) {
			onSubmit(editedContent.trim());
		}
	};

	return (
		<div className="flex justify-end mb-4">
			<div className="max-w-[80%] w-full">
				<div className="bg-blue-900/50 border border-blue-700 rounded-lg p-3">
					<textarea
						value={editedContent}
						onChange={(e) => setEditedContent(e.target.value)}
						autoFocus
						className="w-full min-h-[60px] p-2 bg-gray-800 border border-gray-600 rounded text-white resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
						style={{ fontSize }}
					/>
					<div className="flex justify-end gap-2 mt-2">
						<button
							onClick={onCancel}
							className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white transition-colors"
						>
							Annuler
						</button>
						<button
							onClick={handleSubmit}
							className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white transition-colors"
						>
							Envoyer
						</button>
					</div>
				</div>
			</div>
		</div>
	);
}

// Icons
function EditIcon() {
	return (
		<svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
		</svg>
	);
}

function RefreshIcon() {
	return (
		<svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
			<path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
		</svg>
	);
}
