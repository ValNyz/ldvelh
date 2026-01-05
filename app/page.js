'use client';
import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';

function InputArea({ onSend, disabled, fontSize }) {
	const [input, setInput] = useState('');
	const textareaRef = useRef(null);

	useEffect(() => {
		if (textareaRef.current) {
			textareaRef.current.style.height = 'auto';
			textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
		}
	}, [input]);

	const handleSend = () => {
		if (!input.trim() || disabled) return;
		onSend(input.trim());
		setInput('');
	};

	return (
		<div style={{ padding: 16, background: '#1f2937', borderTop: '1px solid #374151' }}>
			<div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
				<textarea
					ref={textareaRef}
					value={input}
					onChange={(e) => setInput(e.target.value)}
					onKeyDown={(e) => {
						if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
							e.preventDefault();
							handleSend();
						}
					}}
					placeholder="Ton action... (Ctrl+Entrée)"
					disabled={disabled}
					style={{
						flex: 1, padding: '8px 16px', background: '#374151',
						border: '1px solid #4b5563', borderRadius: 4, color: '#fff',
						outline: 'none', fontSize, resize: 'none', minHeight: 44,
						maxHeight: 200, fontFamily: 'inherit', overflow: 'hidden'
					}}
				/>
				<button
					onClick={handleSend}
					disabled={disabled}
					style={{
						padding: '12px 24px', background: '#2563eb', border: 'none',
						borderRadius: 4, color: '#fff', cursor: 'pointer',
						opacity: disabled ? 0.5 : 1, height: 44
					}}
				>
					Envoyer
				</button>
			</div>
			<div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
				Entrée = nouvelle ligne • Ctrl+Entrée = envoyer
			</div>
		</div>
	);
}

export default function Home() {
	const [parties, setParties] = useState([]);
	const [partieId, setPartieId] = useState(null);
	const [partieName, setPartieName] = useState('');
	const [gameState, setGameState] = useState(null);
	const [messages, setMessages] = useState([]);
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [loadingGame, setLoadingGame] = useState(false);
	const [error, setError] = useState('');
	const [showState, setShowState] = useState(false);
	const [showSettings, setShowSettings] = useState(false);
	const [editingName, setEditingName] = useState(false);
	const [newName, setNewName] = useState('');
	const [confirmDelete, setConfirmDelete] = useState(null);
	const [editingMessageIndex, setEditingMessageIndex] = useState(null);
	const [editedContent, setEditedContent] = useState('');
	const [fontSize, setFontSize] = useState(14);
	const [isClient, setIsClient] = useState(false);

	const messagesEndRef = useRef(null);
	const messagesContainerRef = useRef(null);
	const abortControllerRef = useRef(null);
	const userScrolledUp = useRef(false);

	useEffect(() => { setIsClient(true); }, []);
	useEffect(() => { loadParties(); }, []);
	useEffect(() => {
		if (isClient) {
			const saved = localStorage.getItem('ldvelh-fontsize');
			if (saved) setFontSize(parseInt(saved, 10));
		}
	}, [isClient]);
	useEffect(() => {
		if (!userScrolledUp.current) messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
	}, [messages]);

	const handleScroll = (e) => {
		const { scrollTop, scrollHeight, clientHeight } = e.target;
		userScrolledUp.current = scrollHeight - scrollTop - clientHeight > 50;
	};

	const resetScrollBehavior = () => { userScrolledUp.current = false; };

	const changeFontSize = (delta) => {
		const newSize = Math.min(24, Math.max(10, fontSize + delta));
		setFontSize(newSize);
		if (isClient) localStorage.setItem('ldvelh-fontsize', newSize.toString());
	};

	const loadParties = async () => {
		try {
			const res = await fetch('/api/chat?action=list');
			const data = await res.json();
			setParties(data.parties || []);
		} catch (e) { console.error('Erreur chargement parties:', e); }
	};

	// Normalise le gameState depuis différentes sources
	const normalizeGameState = (rawState) => {
		if (!rawState) return null;

		// Depuis loadGame (Supabase)
		if (rawState.partie) {
			return {
				partie: {
					cycle_actuel: rawState.partie.cycle_actuel || 1,
					jour: rawState.partie.jour,
					date_jeu: rawState.partie.date_jeu,
					heure: rawState.partie.heure,
					lieu_actuel: rawState.partie.lieu_actuel,
					pnjs_presents: rawState.partie.pnjs_presents || []
				},
				valentin: rawState.valentin || { energie: 3, moral: 3, sante: 5, credits: 1400, inventaire: [] },
				ia: rawState.ia || {}
			};
		}

		// Depuis Claude (réponse API avec cycle à la racine)
		if (rawState.cycle !== undefined) {
			return {
				partie: {
					cycle_actuel: rawState.cycle || 1,
					jour: rawState.jour,
					date_jeu: rawState.date_jeu,
					heure: rawState.heure,
					lieu_actuel: rawState.lieu_actuel,
					pnjs_presents: rawState.pnjs_presents || []
				},
				valentin: rawState.valentin || { energie: 3, moral: 3, sante: 5, credits: 1400, inventaire: [] },
				ia: rawState.ia || {}
			};
		}

		return null;
	};

	const loadGame = async (id) => {
		setLoadingGame(true);
		setError('');
		try {
			const res = await fetch(`/api/chat?action=load&partieId=${id}`);
			const data = await res.json();
			if (data.error) { setError(data.error); return; }

			setPartieId(id);
			if (data.state) {
				setGameState(normalizeGameState(data.state));
				setPartieName(data.state.partie?.nom || 'Partie sans nom');
			}
			setMessages(data.messages?.map(m => ({ role: m.role, content: m.content })) || []);
		} catch (e) {
			console.error('Load game error:', e);
			setError('Erreur lors du chargement');
		} finally { setLoadingGame(false); }
	};

	const newGame = async () => {
		setLoadingGame(true);
		setError('');
		try {
			const res = await fetch('/api/chat?action=new');
			const data = await res.json();
			if (data.partieId) {
				setPartieId(data.partieId);
				setPartieName('Nouvelle partie');
				setGameState(null);
				setMessages([]);
				loadParties();
			} else setError(data.error || 'Erreur création');
		} catch (e) { setError('Erreur création'); }
		finally { setLoadingGame(false); }
	};

	const deleteGame = async (id) => {
		try {
			const res = await fetch(`/api/chat?action=delete&partieId=${id}`);
			const data = await res.json();
			if (data.error) { setError(data.error); return; }
			setConfirmDelete(null);
			loadParties();
		} catch (e) { setError('Erreur suppression'); }
	};

	const renameGame = async () => {
		if (!newName.trim()) return;
		try {
			await fetch(`/api/chat?action=rename&partieId=${partieId}&name=${encodeURIComponent(newName.trim())}`);
			setPartieName(newName.trim());
			setEditingName(false);
			setNewName('');
		} catch (e) { setError('Erreur renommage'); }
	};

	const cancelRequest = () => {
		if (abortControllerRef.current) {
			abortControllerRef.current.abort();
			abortControllerRef.current = null;
			setLoading(false);
			setMessages(prev => {
				const n = [...prev];
				if (n.length > 0 && n[n.length - 1].streaming) {
					n[n.length - 1] = { ...n[n.length - 1], streaming: false, content: n[n.length - 1].content + '\n\n*(Annulé)*' };
				}
				return n;
			});
		}
	};

	const startEditMessage = (index) => {
		if (messages[index].role !== 'user') return;
		setEditingMessageIndex(index);
		setEditedContent(messages[index].content);
	};

	const cancelEdit = () => { setEditingMessageIndex(null); setEditedContent(''); };

	const submitEdit = async () => {
		if (!editedContent.trim() || loading) return;
		const idx = editingMessageIndex, content = editedContent.trim();
		const prevMsgs = [...messages].slice(0, idx), currState = gameState;
		setEditingMessageIndex(null);
		setEditedContent('');
		setLoading(true);
		setError('');
		resetScrollBehavior();
		setMessages([...prevMsgs, { role: 'user', content }]);
		if (partieId) {
			try { await fetch('/api/chat', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ partieId, fromIndex: idx }) }); }
			catch (e) { console.error('Erreur suppression:', e); }
		}
		await sendMessageInternal(content, prevMsgs, currState);
	};

	const regenerateLastResponse = async () => {
		if (loading || messages.length < 2) return;
		const currMsgs = [...messages], currState = gameState;
		let lastUserIdx = currMsgs.length - 1;
		while (lastUserIdx >= 0 && currMsgs[lastUserIdx].role !== 'user') lastUserIdx--;
		if (lastUserIdx < 0) return;
		const userMsg = currMsgs[lastUserIdx].content, prevMsgs = currMsgs.slice(0, lastUserIdx);
		setMessages([...prevMsgs, { role: 'user', content: userMsg }]);
		setLoading(true);
		setError('');
		resetScrollBehavior();
		if (partieId) {
			try { await fetch('/api/chat', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ partieId, fromIndex: lastUserIdx }) }); }
			catch (e) { console.error('Erreur suppression:', e); }
		}
		await sendMessageInternal(userMsg, prevMsgs, currState);
	};

	const handleSendMessage = async (userMsg) => {
		if (loading || saving) return;
		const currMsgs = [...messages], currState = gameState;
		setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
		setLoading(true);
		setError('');
		resetScrollBehavior();
		await sendMessageInternal(userMsg, currMsgs, currState);
	};

	const sendMessageInternal = async (userMessage, previousMessages, currentGameState) => {
		abortControllerRef.current = new AbortController();

		// Extraction du narratif depuis JSON streamé
		const extractNarratif = (jsonStr) => {
			const m = jsonStr.match(/"narratif"\s*:\s*"/);
			if (!m) return null;
			let narratif = '', i = m.index + m[0].length;
			while (i < jsonStr.length) {
				const c = jsonStr[i];
				if (c === '\\' && i + 1 < jsonStr.length) {
					const n = jsonStr[i + 1];
					if (n === 'n') { narratif += '\n'; i += 2; }
					else if (n === '"') { narratif += '"'; i += 2; }
					else if (n === '\\') { narratif += '\\'; i += 2; }
					else if (n === 't') { narratif += '\t'; i += 2; }
					else if (n === 'r') { narratif += '\r'; i += 2; }
					else { narratif += c; i++; }
				} else if (c === '"') { break; }
				else { narratif += c; i++; }
			}
			return narratif || null;
		};

		const extractHeure = (jsonStr) => {
			const m = jsonStr.match(/"heure"\s*:\s*"([^"]+)"/);
			return m ? m[1] : null;
		};

		const extractChoix = (jsonStr) => {
			const match = jsonStr.match(/"choix"\s*:\s*\[([\s\S]*?)\]/);
			if (!match) return null;
			try { const arr = JSON.parse(`[${match[1]}]`); return arr.length > 0 ? arr : null; }
			catch (e) { return null; }
		};

		const extractDisplayContent = (content) => {
			const trimmed = content.trim();
			if (trimmed.startsWith('{')) {
				const narratif = extractNarratif(content);
				const heure = extractHeure(content);
				const choix = extractChoix(content);
				if (narratif) {
					let display = narratif.replace(/^\[?\d{2}h\d{2}\]?\s*[-–—:]?\s*/i, '');
					if (heure) display = `[${heure}] ${display}`;
					if (choix?.length > 0) display += '\n\n' + choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
					return display;
				}
				return null;
			}
			return content || null;
		};

		const finalizeMessage = (content) => {
			setMessages([...previousMessages, { role: 'user', content: userMessage }, { role: 'assistant', content }]);
		};

		try {
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ message: userMessage, partieId, gameState: currentGameState }),
				signal: abortControllerRef.current.signal
			});

			if (res.headers.get('content-type')?.includes('text/event-stream')) {
				const reader = res.body.getReader(), decoder = new TextDecoder();
				let fullJson = '', assistantAdded = false;

				try {
					while (true) {
						const { done, value } = await reader.read();
						if (done) break;
						const text = decoder.decode(value, { stream: true });

						for (const line of text.split('\n')) {
							if (!line.startsWith('data: ')) continue;
							try {
								const data = JSON.parse(line.slice(6));

								if (data.type === 'chunk') {
									fullJson += data.content;
									const display = extractDisplayContent(fullJson);
									if (display) {
										if (!assistantAdded) {
											setMessages([...previousMessages, { role: 'user', content: userMessage }, { role: 'assistant', content: display, streaming: true }]);
											assistantAdded = true;
										} else {
											setMessages(prev => {
												const n = [...prev];
												n[n.length - 1] = { role: 'assistant', content: display, streaming: true };
												return n;
											});
										}
									}
								} else if (data.type === 'done') {
									setLoading(false);
									setSaving(true);
									finalizeMessage(data.displayText || fullJson);

									if (data.state) {
										const normalized = normalizeGameState(data.state);
										if (normalized) {
											setGameState(prev => {
												if (!prev) return normalized;
												return {
													...prev,
													partie: { ...prev.partie, ...normalized.partie },
													valentin: { ...prev.valentin, ...normalized.valentin },
													ia: normalized.ia?.nom ? { ...prev.ia, ...normalized.ia } : prev.ia
												};
											});
										}
									}
								} else if (data.type === 'saved') {
									setSaving(false);
								} else if (data.type === 'error') {
									setError(data.error);
									if (fullJson) finalizeMessage(extractDisplayContent(fullJson) || fullJson);
								}
							} catch (e) { }
						}
					}
				} catch (e) {
					if (e.name !== 'AbortError') {
						const display = extractDisplayContent(fullJson);
						if (display || fullJson) finalizeMessage(display || fullJson);
					}
				}
			} else {
				const data = await res.json();
				if (data.error) { setError(data.error); return; }
				if (data.displayText) {
					finalizeMessage(data.displayText);
					if (data.state) setGameState(normalizeGameState(data.state));
				} else if (data.content) finalizeMessage(data.content);
			}
		} catch (e) {
			if (e.name !== 'AbortError') setError(e.message);
		} finally {
			setLoading(false);
			abortControllerRef.current = null;
		}
	};

	const formatDate = (d) => d ? new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
	const dots = (n, max = 5) => '●'.repeat(Math.min(Math.max(Math.round(n) || 0, 0), max)) + '○'.repeat(Math.max(0, max - Math.round(n || 0)));

	// === ÉCRAN LISTE DES PARTIES ===
	if (!partieId) {
		return (
			<div style={{ padding: 20, maxWidth: 600, margin: '0 auto' }}>
				<h1 style={{ color: '#60a5fa', marginBottom: 20 }}>LDVELH</h1>
				<button onClick={newGame} disabled={loadingGame} style={{ padding: '10px 20px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', marginBottom: 20, cursor: 'pointer', opacity: loadingGame ? 0.5 : 1 }}>
					{loadingGame ? 'Création...' : '+ Nouvelle partie'}
				</button>
				{error && <div style={{ color: '#f87171', marginBottom: 10 }}>{error}</div>}
				<h2 style={{ marginBottom: 10 }}>Parties existantes :</h2>
				{parties.length === 0 && <p style={{ color: '#6b7280' }}>Aucune partie sauvegardée</p>}
				{parties.map(p => (
					<div key={p.id} style={{ padding: 12, background: '#1f2937', marginBottom: 10, borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
						<div onClick={() => loadGame(p.id)} style={{ cursor: 'pointer', flex: 1 }}>
							<strong>{p.nom}</strong>
							<div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
								Cycle {p.cycle_actuel || 1} • {formatDate(p.updated_at)}
							</div>
						</div>
						{confirmDelete === p.id ? (
							<div style={{ display: 'flex', gap: 8 }}>
								<button onClick={() => deleteGame(p.id)} style={{ padding: '4px 8px', background: '#dc2626', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Confirmer</button>
								<button onClick={() => setConfirmDelete(null)} style={{ padding: '4px 8px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Annuler</button>
							</div>
						) : (
							<button onClick={(e) => { e.stopPropagation(); setConfirmDelete(p.id); }} style={{ padding: '4px 8px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>✕</button>
						)}
					</div>
				))}
			</div>
		);
	}

	if (loadingGame) return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><p style={{ color: '#6b7280' }}>Chargement...</p></div>;

	// === ÉCRAN JEU ===
	return (
		<div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
			{/* HEADER */}
			<div style={{ background: '#1f2937', padding: 12, borderBottom: '1px solid #374151' }}>
				<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
					<h1 style={{ fontSize: 18, color: '#60a5fa' }}>{partieName}</h1>
					<div style={{ display: 'flex', gap: 8 }}>
						<button onClick={() => setShowSettings(!showSettings)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>⚙️</button>
						<button onClick={() => setShowState(!showState)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>{showState ? 'Masquer' : 'État'}</button>
						<button onClick={() => { setPartieId(null); setMessages([]); setGameState(null); loadParties(); }} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>Quitter</button>
					</div>
				</div>

				{/* Stats bar */}
				{gameState?.valentin && (
					<div style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 8 }}>
						<div style={{ color: '#4ade80' }}>
							Cycle {gameState.partie?.cycle_actuel || 1} | {gameState.partie?.jour || '-'} {gameState.partie?.date_jeu || '-'}
							{gameState.partie?.heure && <span style={{ marginLeft: 8 }}>🕐 {gameState.partie.heure}</span>}
						</div>
						<div style={{ display: 'flex', gap: 16, marginTop: 4 }}>
							<span>Énergie: {dots(gameState.valentin.energie)}</span>
							<span>Moral: {dots(gameState.valentin.moral)}</span>
							<span>Santé: {dots(gameState.valentin.sante)}</span>
						</div>
						<div style={{ marginTop: 4 }}>
							<span style={{ color: '#fbbf24' }}>💰 {gameState.valentin.credits ?? 1400} cr</span>
							{gameState.partie?.lieu_actuel && (
								<span style={{ color: '#93c5fd', marginLeft: 12 }}>📍 {gameState.partie.lieu_actuel}</span>
							)}
							{gameState.partie?.pnjs_presents?.length > 0 && (
								<span style={{ color: '#a78bfa', marginLeft: 12 }}>👥 {gameState.partie.pnjs_presents.join(', ')}</span>
							)}
						</div>
						{gameState.valentin.inventaire?.length > 0 && (
							<div style={{ color: '#6b7280', marginTop: 4, fontSize: 11 }}>
								🎒 {gameState.valentin.inventaire.join(', ')}
							</div>
						)}
					</div>
				)}
			</div>

			{/* SETTINGS PANEL */}
			{showSettings && (
				<div style={{ background: '#1f2937', padding: 16, borderBottom: '1px solid #374151' }}>
					<h3 style={{ marginBottom: 12, fontSize: 14, color: '#9ca3af' }}>Paramètres</h3>

					{/* Font size */}
					<div style={{ marginBottom: 16 }}>
						<label style={{ fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 8 }}>Taille police</label>
						<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
							<button onClick={() => changeFontSize(-2)} disabled={fontSize <= 10} style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize <= 10 ? 0.5 : 1 }}>−</button>
							<span style={{ color: '#fff', minWidth: 40, textAlign: 'center' }}>{fontSize}px</span>
							<button onClick={() => changeFontSize(2)} disabled={fontSize >= 24} style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize >= 24 ? 0.5 : 1 }}>+</button>
						</div>
					</div>

					{/* Rename */}
					<div style={{ marginBottom: 12 }}>
						<label style={{ fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 4 }}>Nom partie</label>
						{editingName ? (
							<div style={{ display: 'flex', gap: 8 }}>
								<input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && renameGame()} placeholder={partieName} autoFocus style={{ flex: 1, padding: '6px 12px', background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize: 14 }} />
								<button onClick={renameGame} style={{ padding: '6px 12px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>OK</button>
								<button onClick={() => { setEditingName(false); setNewName(''); }} style={{ padding: '6px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>✕</button>
							</div>
						) : (
							<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
								<span style={{ color: '#fff' }}>{partieName}</span>
								<button onClick={() => { setEditingName(true); setNewName(partieName); }} style={{ padding: '4px 8px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 12 }}>✏️</button>
							</div>
						)}
					</div>

					{/* Delete */}
					<button onClick={() => { if (confirm('Supprimer cette partie ?')) { deleteGame(partieId); setPartieId(null); setMessages([]); setGameState(null); setShowSettings(false); } }} style={{ padding: '8px 16px', background: '#dc2626', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>🗑️ Supprimer</button>
				</div>
			)}

			{/* DEBUG STATE */}
			{showState && gameState && (
				<div style={{ background: '#1f2937', padding: 12, maxHeight: 200, overflow: 'auto', borderBottom: '1px solid #374151' }}>
					<pre style={{ fontSize: 10, color: '#9ca3af' }}>{JSON.stringify(gameState, null, 2)}</pre>
				</div>
			)}

			{/* MESSAGES */}
			<div ref={messagesContainerRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto', padding: 16 }}>
				{messages.length === 0 && (
					<div style={{ textAlign: 'center', color: '#6b7280', marginTop: 40 }}>
						<p>Tape "Commencer" pour lancer l'aventure</p>
					</div>
				)}

				{messages.map((msg, i) => (
					<div key={i} style={{
						marginBottom: 16,
						display: 'flex',
						justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start'
					}}>
						{editingMessageIndex === i ? (
							<div style={{ maxWidth: '80%', padding: 12, borderRadius: 8, background: '#1e3a5f' }}>
								<textarea value={editedContent} onChange={(e) => setEditedContent(e.target.value)} autoFocus style={{ width: '100%', minHeight: 60, padding: 8, background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize, resize: 'vertical' }} />
								<div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
									<button onClick={cancelEdit} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Annuler</button>
									<button onClick={submitEdit} style={{ padding: '4px 12px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Envoyer</button>
								</div>
							</div>
						) : (
							<div style={{ maxWidth: msg.role === 'user' ? '80%' : '95%', position: 'relative' }} className="message-container">
								<div style={{
									padding: 12,
									borderRadius: msg.role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
									background: msg.role === 'user' ? '#2563eb' : '#1f2937',
									textAlign: 'left'
								}}>
									<div className="markdown-content" style={{ fontSize }}>
										<ReactMarkdown components={{
											p: ({ children }) => <p style={{ margin: '0 0 8px 0' }}>{children}</p>,
											strong: ({ children }) => <strong style={{ color: msg.role === 'user' ? '#fff' : '#60a5fa' }}>{children}</strong>,
											em: ({ children }) => <em style={{ color: msg.role === 'user' ? '#e0e7ff' : '#a5b4fc' }}>{children}</em>,
											ul: ({ children }) => <ul style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ul>,
											ol: ({ children }) => <ol style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ol>,
											li: ({ children }) => <li style={{ marginBottom: 4 }}>{children}</li>,
											code: ({ inline, children }) => inline
												? <code style={{ background: msg.role === 'user' ? '#1e40af' : '#374151', padding: '2px 6px', borderRadius: 4, fontSize: '0.9em' }}>{children}</code>
												: <pre style={{ background: msg.role === 'user' ? '#1e40af' : '#374151', padding: 12, borderRadius: 4, overflow: 'auto', margin: '8px 0' }}><code>{children}</code></pre>,
											blockquote: ({ children }) => <blockquote style={{ borderLeft: '3px solid #60a5fa', paddingLeft: 12, margin: '8px 0', color: '#9ca3af', fontStyle: 'italic' }}>{children}</blockquote>,
										}}>{msg.content}</ReactMarkdown>
									</div>
									{msg.streaming && <span style={{ color: '#60a5fa' }}>▋</span>}
								</div>

								{/* Actions */}
								<div className="message-actions" style={{
									position: 'absolute', top: -8,
									left: msg.role === 'user' ? 'auto' : 0,
									right: msg.role === 'user' ? 0 : 'auto',
									display: 'flex', gap: 4, opacity: 0, transition: 'opacity 0.2s'
								}}>
									{msg.role === 'user' && !loading && (
										<button onClick={() => startEditMessage(i)} title="Éditer" style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}>✏️</button>
									)}
									{msg.role === 'assistant' && i === messages.length - 1 && !loading && !msg.streaming && (
										<button onClick={regenerateLastResponse} title="Regénérer" style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}>🔄</button>
									)}
								</div>
							</div>
						)}
					</div>
				))}

				{/* Loading indicator */}
				{loading && !messages.some(m => m.streaming) && (
					<div style={{ display: 'flex', alignItems: 'center', gap: 12, color: '#6b7280', fontStyle: 'italic' }}>
						<span>En cours...</span>
						<button onClick={cancelRequest} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>✕ Annuler</button>
					</div>
				)}
				{loading && messages.some(m => m.streaming) && (
					<div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
						<button onClick={cancelRequest} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>✕ Annuler</button>
					</div>
				)}

				{error && <div style={{ color: '#f87171', marginTop: 8 }}>{error}</div>}
				<div ref={messagesEndRef} />
			</div>

			<InputArea onSend={handleSendMessage} disabled={loading || saving} fontSize={fontSize} />

			<style jsx>{`.message-container:hover .message-actions { opacity: 1 !important; }`}</style>
		</div>
	);
}
