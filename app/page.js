'use client';
import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';

export default function Home() {
  const [parties, setParties] = useState([]);
  const [partieId, setPartieId] = useState(null);
  const [partieName, setPartieName] = useState('');
  const [gameState, setGameState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
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
  const textareaRef = useRef(null);

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
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target;
    // Si l'utilisateur est à moins de 50px du bas, on considère qu'il est "en bas"
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

  // Fonction pour normaliser le state (utilisée par loadGame et après réponse Claude)
  const normalizeGameState = (rawState) => {
    if (!rawState) return null;
    
    // Si ça vient de Supabase (loadGame), la structure est différente
    if (rawState.partie && rawState.partie.id) {
      return {
        partie: {
          cycle_actuel: rawState.partie.cycle_actuel || 1,
          jour: rawState.partie.jour,
          date_jeu: rawState.partie.date_jeu,
          heure: rawState.partie.heure
        },
        valentin: rawState.valentin,
        ia: rawState.ia,
        contexte: rawState.contexte,
        pnj: rawState.pnj || [],
        arcs: rawState.arcs || [],
        historique: rawState.historique || [],
        aVenir: rawState.aVenir || [],
        lieux: rawState.lieux || [],
        horsChamp: rawState.horsChamp || []
      };
    }
    
    // Si ça vient de Claude (réponse API), normaliser depuis le format Claude
    return {
      partie: {
        cycle_actuel: rawState.cycle || 1,
        jour: rawState.jour,
        date_jeu: rawState.date_jeu,
        heure: rawState.heure
      },
      valentin: rawState.valentin,
      ia: rawState.ia,
      contexte: rawState.contexte,
      pnj: rawState.pnj || [],
      arcs: rawState.arcs || [],
      historique: rawState.historique || [],
      aVenir: rawState.a_venir || [],
      lieux: rawState.lieux || [],
      horsChamp: rawState.hors_champ || []
    };
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

  const sendMessage = async () => {
    if (!input.trim() || loading || saving) return;
    const userMsg = input.trim(), currMsgs = [...messages], currState = gameState;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setLoading(true);
    setError('');
    resetScrollBehavior();
    await sendMessageInternal(userMsg, currMsgs, currState);
  };

  const sendMessageInternal = async (userMessage, previousMessages, currentGameState) => {
    abortControllerRef.current = new AbortController();

    // Extraction robuste du narratif depuis le JSON en streaming
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
          else if (n === 'b') { narratif += '\b'; i += 2; }
          else if (n === 'f') { narratif += '\f'; i += 2; }
          else if (n === '/') { narratif += '/'; i += 2; }
          else if (n === 'u' && i + 5 < jsonStr.length) {
            const hex = jsonStr.slice(i + 2, i + 6);
            if (/^[0-9a-fA-F]{4}$/.test(hex)) {
              narratif += String.fromCharCode(parseInt(hex, 16));
              i += 6;
            } else {
              narratif += '\\u';
              i += 2;
            }
          } else {
            narratif += c;
            i++;
          }
        } else if (c === '"') {
          break;
        } else {
          narratif += c;
          i++;
        }
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
      try {
        const choixArray = JSON.parse(`[${match[1]}]`);
        return choixArray.length > 0 ? choixArray : null;
      } catch (e) {
        return null;
      }
    };

    const extractDisplayContent = (content) => {
      const trimmed = content.trim();
      if (trimmed.startsWith('{')) {
        const narratif = extractNarratif(content);
        const heure = extractHeure(content);
        const choix = extractChoix(content);
        
        if (narratif) {
          let display = narratif.replace(/^\[?\d{2}h\d{2}\]?\s*[-–—:]?\s*/i, '');
          if (heure) {
            display = `[${heure}] ${display}`;
          }
          if (choix && choix.length > 0) {
            display += '\n\n' + choix.map((c, i) => `${i + 1}. ${c}`).join('\n');
          }
          return display;
        }
        return null;
      }
      
      let display = content;
      const jsonIdx = content.lastIndexOf('\n{');
      if (jsonIdx > 0) display = content.slice(0, jsonIdx).trim();
      display = display.replace(/\[(\d{2}h\d{2})\]\s*\[\1\]/g, '[$1]');
      return display || null;
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
                      setMessages(prev => { const n = [...prev]; n[n.length - 1] = { role: 'assistant', content: display, streaming: true }; return n; });
                    }
                  }
                } else if (data.type === 'done') {
                  setLoading(false);
                  setSaving(true);
                  finalizeMessage(data.displayText || fullJson);
                  if (data.state) {
                    const normalized = normalizeGameState({ ...data.state, heure: data.heure });
                    setGameState(normalized);
                  }
                } else if (data.type === 'saved') {
                  setSaving(false);
                } else if (data.type === 'error') {
                  setError(data.error);
                  if (fullJson) finalizeMessage(extractDisplayContent(fullJson) || fullJson);
                }
              } catch (e) {}
            }
          }
        } catch (e) {
          if (e.name !== 'AbortError') {
            console.error('Stream error:', e);
            const display = extractDisplayContent(fullJson);
            if (display || fullJson) finalizeMessage(display || fullJson);
          }
        }
      } else {
        const data = await res.json();
        if (data.error) { setError(data.error); return; }
        if (data.displayText) {
          finalizeMessage(data.displayText);
          if (data.state) {
            const normalized = normalizeGameState({ ...data.state, heure: data.heure });
            setGameState(normalized);
          }
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
  const dots = (n, max = 5) => '●'.repeat(Math.min(Math.max(n || 0, 0), max)) + '○'.repeat(Math.max(0, max - (n || 0)));

  // Écran sélection partie
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
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>Cycle {p.cycle_actuel || 0} • {formatDate(p.updated_at)}</div>
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

  // Écran jeu
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Header */}
      <div style={{ background: '#1f2937', padding: 12, borderBottom: '1px solid #374151' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ fontSize: 18, color: '#60a5fa' }}>{partieName}</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setShowSettings(!showSettings)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>⚙️</button>
            <button onClick={() => setShowState(!showState)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>{showState ? 'Masquer' : 'État'}</button>
            <button onClick={() => { setPartieId(null); setMessages([]); setGameState(null); loadParties(); }} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>Quitter</button>
          </div>
        </div>
        {gameState?.valentin && (
          <div style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 8 }}>
            <div style={{ color: '#4ade80' }}>Cycle {gameState.partie?.cycle_actuel || 1} | {gameState.partie?.jour || '-'}</div>
            <div>Énergie: {dots(gameState.valentin.energie)} | Moral: {dots(gameState.valentin.moral)} | Santé: {dots(gameState.valentin.sante)}</div>
            <div style={{ color: '#fbbf24' }}>Crédits: {gameState.valentin.credits ?? 1400}</div>
          </div>
        )}
      </div>

      {/* Paramètres */}
      {showSettings && (
        <div style={{ background: '#1f2937', padding: 16, borderBottom: '1px solid #374151' }}>
          <h3 style={{ marginBottom: 12, fontSize: 14, color: '#9ca3af' }}>Paramètres</h3>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 8 }}>Taille police</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button onClick={() => changeFontSize(-2)} disabled={fontSize <= 10} style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize <= 10 ? 0.5 : 1 }}>−</button>
              <span style={{ color: '#fff', minWidth: 40, textAlign: 'center' }}>{fontSize}px</span>
              <button onClick={() => changeFontSize(2)} disabled={fontSize >= 24} style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize >= 24 ? 0.5 : 1 }}>+</button>
            </div>
          </div>
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
          <button onClick={() => { if (confirm('Supprimer cette partie ?')) { deleteGame(partieId); setPartieId(null); setMessages([]); setGameState(null); setShowSettings(false); }}} style={{ padding: '8px 16px', background: '#dc2626', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>🗑️ Supprimer</button>
        </div>
      )}

      {showState && gameState && (
        <div style={{ background: '#1f2937', padding: 12, maxHeight: 200, overflow: 'auto', borderBottom: '1px solid #374151' }}>
          <pre style={{ fontSize: 10, color: '#9ca3af' }}>{JSON.stringify(gameState, null, 2)}</pre>
        </div>
      )}

      {/* Messages */}
      <div ref={messagesContainerRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {messages.length === 0 && <div style={{ textAlign: 'center', color: '#6b7280', marginTop: 40 }}><p>Tape "Commencer" pour lancer</p></div>}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 16, textAlign: 'left' }}>
            {editingMessageIndex === i ? (
              <div style={{ display: 'inline-block', maxWidth: '80%', padding: 12, borderRadius: 8, background: '#1e3a5f' }}>
                <textarea value={editedContent} onChange={(e) => setEditedContent(e.target.value)} autoFocus style={{ width: '100%', minHeight: 60, padding: 8, background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize, resize: 'vertical' }} />
                <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
                  <button onClick={cancelEdit} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Annuler</button>
                  <button onClick={submitEdit} style={{ padding: '4px 12px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>Envoyer</button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'inline-block', maxWidth: msg.role === 'user' ? '80%' : '95%', position: 'relative' }} className="message-container">
                <div style={{ padding: 12, borderRadius: 8, background: msg.role === 'user' ? '#1e3a5f' : '#1f2937' }}>
                  <div className="markdown-content" style={{ fontSize }}>
                    <ReactMarkdown components={{
                      p: ({ children }) => <p style={{ margin: '0 0 8px 0' }}>{children}</p>,
                      strong: ({ children }) => <strong style={{ color: '#60a5fa' }}>{children}</strong>,
                      em: ({ children }) => <em style={{ color: '#a5b4fc' }}>{children}</em>,
                      ul: ({ children }) => <ul style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ul>,
                      ol: ({ children }) => <ol style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ol>,
                      li: ({ children }) => <li style={{ marginBottom: 4 }}>{children}</li>,
                      code: ({ inline, children }) => inline ? <code style={{ background: '#374151', padding: '2px 6px', borderRadius: 4, fontSize: '0.9em' }}>{children}</code> : <pre style={{ background: '#374151', padding: 12, borderRadius: 4, overflow: 'auto', margin: '8px 0' }}><code>{children}</code></pre>,
                      blockquote: ({ children }) => <blockquote style={{ borderLeft: '3px solid #60a5fa', paddingLeft: 12, margin: '8px 0', color: '#9ca3af', fontStyle: 'italic' }}>{children}</blockquote>,
                      h1: ({ children }) => <h1 style={{ fontSize: '1.4em', margin: '12px 0 8px', color: '#60a5fa' }}>{children}</h1>,
                      h2: ({ children }) => <h2 style={{ fontSize: '1.2em', margin: '10px 0 6px', color: '#60a5fa' }}>{children}</h2>,
                      h3: ({ children }) => <h3 style={{ fontSize: '1.1em', margin: '8px 0 4px', color: '#60a5fa' }}>{children}</h3>,
                      hr: () => <hr style={{ border: 'none', borderTop: '1px solid #374151', margin: '12px 0' }} />
                    }}>{msg.content}</ReactMarkdown>
                  </div>
                  {msg.streaming && <span style={{ color: '#60a5fa' }}>▋</span>}
                </div>
                <div className="message-actions" style={{ position: 'absolute', top: -8, left: 0, display: 'flex', gap: 4, opacity: 0, transition: 'opacity 0.2s' }}>
                  {msg.role === 'user' && !loading && <button onClick={() => startEditMessage(i)} title="Éditer" style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}>✏️</button>}
                  {msg.role === 'assistant' && i === messages.length - 1 && !loading && !msg.streaming && <button onClick={regenerateLastResponse} title="Regénérer" style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}>🔄</button>}
                </div>
              </div>
            )}
          </div>
        ))}
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

      {/* Input */}
      <div style={{ padding: 16, background: '#1f2937', borderTop: '1px solid #374151' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendMessage(); }}}
            placeholder="Ton action... (Ctrl+Entrée)"
            disabled={loading}
            style={{ flex: 1, padding: '8px 16px', background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize, resize: 'none', minHeight: 44, maxHeight: 200, fontFamily: 'inherit', overflow: 'hidden' }}
          />
          <button onClick={sendMessage} disabled={loading} style={{ padding: '12px 24px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', opacity: loading ? 0.5 : 1, height: 44 }}>Envoyer</button>
        </div>
        <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>Entrée = nouvelle ligne • Ctrl+Entrée = envoyer</div>
      </div>

      <style jsx>{`.message-container:hover .message-actions { opacity: 1 !important; }`}</style>
    </div>
  );
}
