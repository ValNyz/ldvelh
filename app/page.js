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
  const messagesEndRef = useRef(null);
  const abortControllerRef = useRef(null);

  useEffect(() => { loadParties(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  
  // Charger la taille de police depuis localStorage
  useEffect(() => {
    const saved = localStorage.getItem('ldvelh-fontsize');
    if (saved) setFontSize(parseInt(saved, 10));
  }, []);

  const changeFontSize = (delta) => {
    const newSize = Math.min(24, Math.max(10, fontSize + delta));
    setFontSize(newSize);
    localStorage.setItem('ldvelh-fontsize', newSize.toString());
  };

  const loadParties = async () => {
    const res = await fetch('/api/chat?action=list');
    const data = await res.json();
    setParties(data.parties || []);
  };

  const loadGame = async (id) => {
    setLoadingGame(true);
    try {
      const res = await fetch(`/api/chat?action=load&partieId=${id}`);
      const data = await res.json();
      setPartieId(id);
      setGameState(data.state);
      setPartieName(data.state?.partie?.nom || 'Partie sans nom');
      
      if (data.messages && data.messages.length > 0) {
        setMessages(data.messages.map(m => ({
          role: m.role,
          content: m.content
        })));
      } else {
        setMessages([]);
      }
    } catch (e) {
      setError('Erreur lors du chargement de la partie');
    } finally {
      setLoadingGame(false);
    }
  };

  const newGame = async () => {
    setLoadingGame(true);
    try {
      const res = await fetch('/api/chat?action=new');
      const data = await res.json();
      if (data.partieId) {
        setPartieId(data.partieId);
        setPartieName('Nouvelle partie');
        setGameState(null);
        setMessages([]);
        // Rafraîchir la liste pour inclure la nouvelle partie
        loadParties();
      } else {
        setError('Erreur lors de la création de la partie');
      }
    } catch (e) {
      setError('Erreur lors de la création de la partie');
    } finally {
      setLoadingGame(false);
    }
  };

  const deleteGame = async (id) => {
    await fetch(`/api/chat?action=delete&partieId=${id}`);
    setConfirmDelete(null);
    loadParties();
  };

  const renameGame = async () => {
    if (!newName.trim()) return;
    await fetch(`/api/chat?action=rename&partieId=${partieId}&name=${encodeURIComponent(newName.trim())}`);
    setPartieName(newName.trim());
    setEditingName(false);
    setNewName('');
  };

  // Annuler la requête en cours
  const cancelRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setLoading(false);
      // Supprimer le dernier message user qui attendait une réponse
      setMessages(prev => prev.slice(0, -1));
    }
  };

  // Éditer un message et regénérer
  const startEditMessage = (index) => {
    if (messages[index].role !== 'user') return;
    setEditingMessageIndex(index);
    setEditedContent(messages[index].content);
  };

  const cancelEdit = () => {
    setEditingMessageIndex(null);
    setEditedContent('');
  };

  const submitEdit = async () => {
    if (!editedContent.trim() || loading) return;
    
    const messageIndex = editingMessageIndex;
    const newContent = editedContent.trim();
    
    setEditingMessageIndex(null);
    setEditedContent('');
    setLoading(true);
    setError('');

    // Supprimer les messages à partir de l'index édité (en local)
    const previousMessages = messages.slice(0, messageIndex);
    setMessages([...previousMessages, { role: 'user', content: newContent }]);

    // Supprimer les messages en BDD à partir de cet index
    try {
      await fetch('/api/chat', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          partieId, 
          fromIndex: messageIndex 
        })
      });
    } catch (e) {
      console.error('Erreur suppression messages:', e);
    }

    // Regénérer avec le nouveau message
    await sendMessageInternal(newContent, previousMessages);
  };

  // Regénérer le dernier message assistant
  const regenerateLastResponse = async () => {
    if (loading || messages.length < 2) return;
    
    // Trouver le dernier message user
    let lastUserIndex = messages.length - 1;
    while (lastUserIndex >= 0 && messages[lastUserIndex].role !== 'user') {
      lastUserIndex--;
    }
    if (lastUserIndex < 0) return;

    const userMessage = messages[lastUserIndex].content;
    const previousMessages = messages.slice(0, lastUserIndex);
    
    setMessages([...previousMessages, { role: 'user', content: userMessage }]);
    setLoading(true);
    setError('');

    // Supprimer le dernier échange en BDD
    try {
      await fetch('/api/chat', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          partieId, 
          fromIndex: lastUserIndex 
        })
      });
    } catch (e) {
      console.error('Erreur suppression:', e);
    }

    await sendMessageInternal(userMessage, previousMessages);
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMessage = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setLoading(true);
    setError('');
    await sendMessageInternal(userMessage, messages);
  };

  const sendMessageInternal = async (userMessage, previousMessages) => {
    abortControllerRef.current = new AbortController();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage, partieId, gameState }),
        signal: abortControllerRef.current.signal
      });

      // Vérifier si c'est du streaming (SSE)
      const contentType = res.headers.get('content-type');
      
      if (contentType?.includes('text/event-stream')) {
        // Mode streaming
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullJson = '';
        let assistantMessageAdded = false;

        // Fonction pour extraire le narratif du JSON partiel
        const extractNarratif = (jsonStr) => {
          // Chercher le contenu après "narratif": "
          const narratifMatch = jsonStr.match(/"narratif"\s*:\s*"([\s\S]*?)(?:"|$)/);
          if (narratifMatch) {
            let narratif = narratifMatch[1];
            // Nettoyer les échappements JSON
            narratif = narratif
              .replace(/\\n/g, '\n')
              .replace(/\\"/g, '"')
              .replace(/\\\\/g, '\\')
              .replace(/\\t/g, '\t');
            return narratif;
          }
          return null;
        };

        // Fonction pour extraire l'heure
        const extractHeure = (jsonStr) => {
          const heureMatch = jsonStr.match(/"heure"\s*:\s*"([^"]+)"/);
          return heureMatch ? heureMatch[1] : null;
        };

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value, { stream: true });
            const lines = text.split('\n');

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const data = JSON.parse(line.slice(6));

                  if (data.type === 'chunk') {
                    fullJson += data.content;
                    
                    // Extraire et afficher le narratif en cours
                    const narratif = extractNarratif(fullJson);
                    const heure = extractHeure(fullJson);
                    
                    if (narratif) {
                      const displayContent = heure ? `[${heure}] ${narratif}` : narratif;
                      
                      if (!assistantMessageAdded) {
                        setMessages([...previousMessages, 
                          { role: 'user', content: userMessage },
                          { role: 'assistant', content: displayContent, streaming: true }
                        ]);
                        assistantMessageAdded = true;
                      } else {
                        setMessages(prev => {
                          const newMessages = [...prev];
                          newMessages[newMessages.length - 1] = { 
                            role: 'assistant', 
                            content: displayContent,
                            streaming: true 
                          };
                          return newMessages;
                        });
                      }
                    }
                  } else if (data.type === 'done') {
                    setMessages([...previousMessages,
                      { role: 'user', content: userMessage },
                      { role: 'assistant', content: data.displayText || extractNarratif(fullJson) || fullJson }
                    ]);
                    
                    if (data.state) {
                      setGameState({ 
                        partie: { 
                          cycle_actuel: data.state.cycle, 
                          jour: data.state.jour,
                          date_jeu: data.state.date_jeu,
                          heure: data.heure
                        }, 
                        ...data.state 
                      });
                    }
                  } else if (data.type === 'error') {
                    setError(data.error);
                  }
                } catch (parseError) {
                  // Ignorer les lignes mal formées
                }
              }
            }
          }
        } catch (streamError) {
          if (streamError.name !== 'AbortError') {
            console.error('Stream error:', streamError);
            // Si on a du contenu, l'afficher quand même
            const narratif = extractNarratif(fullJson);
            if (narratif || fullJson) {
              setMessages([...previousMessages,
                { role: 'user', content: userMessage },
                { role: 'assistant', content: narratif || fullJson }
              ]);
            }
          }
        }
      } else {
        // Mode classique (fallback)
        const data = await res.json();

        if (data.error) {
          setError(data.error);
          return;
        }

        if (data.displayText) {
          setMessages([...previousMessages, 
            { role: 'user', content: userMessage },
            { role: 'assistant', content: data.displayText }
          ]);
          if (data.state) {
            setGameState({ 
              partie: { 
                cycle_actuel: data.state.cycle, 
                jour: data.state.jour,
                date_jeu: data.state.date_jeu,
                heure: data.heure
              }, 
              ...data.state 
            });
          }
        } else if (data.content) {
          setMessages([...previousMessages,
            { role: 'user', content: userMessage },
            { role: 'assistant', content: data.content }
          ]);
        }
      }

    } catch (e) {
      if (e.name === 'AbortError') {
        console.log('Requête annulée');
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const dots = (n, max=5) => '●'.repeat(Math.min(n,max)) + '○'.repeat(Math.max(0,max-n));

  // Écran sélection partie
  if (!partieId) {
    return (
      <div style={{ padding: 20, maxWidth: 600, margin: '0 auto' }}>
        <h1 style={{ color: '#60a5fa', marginBottom: 20 }}>LDVELH</h1>
        <button onClick={newGame} style={{ padding: '10px 20px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', marginBottom: 20, cursor: 'pointer' }}>
          + Nouvelle partie
        </button>
        <h2 style={{ marginBottom: 10 }}>Parties existantes :</h2>
        {parties.length === 0 && <p style={{ color: '#6b7280' }}>Aucune partie sauvegardée</p>}
        {parties.map(p => (
          <div key={p.id} style={{ padding: 12, background: '#1f2937', marginBottom: 10, borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div onClick={() => loadGame(p.id)} style={{ cursor: 'pointer', flex: 1 }}>
              <strong>{p.nom}</strong>
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>
                Cycle {p.cycle_actuel || 0} • {formatDate(p.updated_at)}
              </div>
            </div>
            {confirmDelete === p.id ? (
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => deleteGame(p.id)} style={{ padding: '4px 8px', background: '#dc2626', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                  Confirmer
                </button>
                <button onClick={() => setConfirmDelete(null)} style={{ padding: '4px 8px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                  Annuler
                </button>
              </div>
            ) : (
              <button onClick={(e) => { e.stopPropagation(); setConfirmDelete(p.id); }} style={{ padding: '4px 8px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                ✕
              </button>
            )}
          </div>
        ))}
      </div>
    );
  }

  // Écran de chargement
  if (loadingGame) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <p style={{ color: '#6b7280' }}>Chargement de la partie...</p>
      </div>
    );
  }

  // Écran jeu
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      {/* Header */}
      <div style={{ background: '#1f2937', padding: 12, borderBottom: '1px solid #374151' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ fontSize: 18, color: '#60a5fa' }}>{partieName}</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setShowSettings(!showSettings)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
              ⚙️
            </button>
            <button onClick={() => setShowState(!showState)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
              {showState ? 'Masquer' : 'État'}
            </button>
            <button onClick={() => { setPartieId(null); setMessages([]); setGameState(null); loadParties(); }} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
              Quitter
            </button>
          </div>
        </div>
        {gameState?.valentin && (
          <div style={{ fontFamily: 'monospace', fontSize: 12, marginTop: 8 }}>
            <div style={{ color: '#4ade80' }}>Cycle {gameState.partie?.cycle_actuel || gameState.cycle} | {gameState.partie?.jour || gameState.jour}</div>
            <div>Énergie: {dots(gameState.valentin.energie)} | Moral: {dots(gameState.valentin.moral)} | Santé: {dots(gameState.valentin.sante)}</div>
            <div style={{ color: '#fbbf24' }}>Crédits: {gameState.valentin.credits}</div>
          </div>
        )}
      </div>

      {/* Panneau paramètres */}
      {showSettings && (
        <div style={{ background: '#1f2937', padding: 16, borderBottom: '1px solid #374151' }}>
          <h3 style={{ marginBottom: 12, fontSize: 14, color: '#9ca3af' }}>Paramètres de la partie</h3>
          
          {/* Taille de police */}
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 8 }}>Taille de police</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button 
                onClick={() => changeFontSize(-2)} 
                disabled={fontSize <= 10}
                style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize <= 10 ? 0.5 : 1 }}
              >
                −
              </button>
              <span style={{ color: '#fff', minWidth: 40, textAlign: 'center' }}>{fontSize}px</span>
              <button 
                onClick={() => changeFontSize(2)} 
                disabled={fontSize >= 24}
                style={{ width: 32, height: 32, background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 18, opacity: fontSize >= 24 ? 0.5 : 1 }}
              >
                +
              </button>
              <span style={{ color: '#6b7280', fontSize: 12, marginLeft: 8 }}>Aperçu :</span>
              <span style={{ color: '#fff', fontSize: fontSize }}>Texte</span>
            </div>
          </div>
          
          {/* Nom de la partie */}
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, color: '#6b7280', display: 'block', marginBottom: 4 }}>Nom de la partie</label>
            {editingName ? (
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && renameGame()}
                  placeholder={partieName}
                  autoFocus
                  style={{ flex: 1, padding: '6px 12px', background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize: 14 }}
                />
                <button onClick={renameGame} style={{ padding: '6px 12px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                  OK
                </button>
                <button onClick={() => { setEditingName(false); setNewName(''); }} style={{ padding: '6px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                  ✕
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ color: '#fff' }}>{partieName}</span>
                <button onClick={() => { setEditingName(true); setNewName(partieName); }} style={{ padding: '4px 8px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 12 }}>
                  ✏️ Modifier
                </button>
              </div>
            )}
          </div>

          <div>
            <button 
              onClick={() => {
                if (confirm('Supprimer définitivement cette partie ?')) {
                  deleteGame(partieId);
                  setPartieId(null);
                  setMessages([]);
                  setGameState(null);
                  setShowSettings(false);
                }
              }} 
              style={{ padding: '8px 16px', background: '#dc2626', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}
            >
              🗑️ Supprimer cette partie
            </button>
          </div>
        </div>
      )}

      {showState && gameState && (
        <div style={{ background: '#1f2937', padding: 12, maxHeight: 200, overflow: 'auto', borderBottom: '1px solid #374151' }}>
          <pre style={{ fontSize: 10, color: '#9ca3af' }}>{JSON.stringify(gameState, null, 2)}</pre>
        </div>
      )}

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#6b7280', marginTop: 40 }}>
            <p>Tape "Commencer" pour lancer la partie</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{ marginBottom: 16, textAlign: msg.role === 'user' ? 'right' : 'left' }}>
            {editingMessageIndex === i ? (
              // Mode édition
              <div style={{ display: 'inline-block', maxWidth: '80%', padding: 12, borderRadius: 8, background: '#1e3a5f' }}>
                <textarea
                  value={editedContent}
                  onChange={(e) => setEditedContent(e.target.value)}
                  autoFocus
                  style={{ width: '100%', minHeight: 60, padding: 8, background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none', fontSize: fontSize, resize: 'vertical' }}
                />
                <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
                  <button onClick={cancelEdit} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                    Annuler
                  </button>
                  <button onClick={submitEdit} style={{ padding: '4px 12px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}>
                    Envoyer
                  </button>
                </div>
              </div>
            ) : (
              // Mode affichage
              <div style={{ display: 'inline-block', maxWidth: '80%', position: 'relative' }}>
                <div style={{ padding: 12, borderRadius: 8, background: msg.role === 'user' ? '#1e3a5f' : '#1f2937' }}>
                  <div className="markdown-content" style={{ fontSize: fontSize }}>
                    <ReactMarkdown
                      components={{
                        p: ({children}) => <p style={{ margin: '0 0 8px 0' }}>{children}</p>,
                        strong: ({children}) => <strong style={{ color: '#60a5fa' }}>{children}</strong>,
                        em: ({children}) => <em style={{ color: '#a5b4fc' }}>{children}</em>,
                        ul: ({children}) => <ul style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ul>,
                        ol: ({children}) => <ol style={{ margin: '8px 0', paddingLeft: 20 }}>{children}</ol>,
                        li: ({children}) => <li style={{ marginBottom: 4 }}>{children}</li>,
                        code: ({inline, children}) => inline 
                          ? <code style={{ background: '#374151', padding: '2px 6px', borderRadius: 4, fontSize: '0.9em' }}>{children}</code>
                          : <pre style={{ background: '#374151', padding: 12, borderRadius: 4, overflow: 'auto', margin: '8px 0' }}><code>{children}</code></pre>,
                        blockquote: ({children}) => <blockquote style={{ borderLeft: '3px solid #60a5fa', paddingLeft: 12, margin: '8px 0', color: '#9ca3af', fontStyle: 'italic' }}>{children}</blockquote>,
                        h1: ({children}) => <h1 style={{ fontSize: '1.4em', margin: '12px 0 8px', color: '#60a5fa' }}>{children}</h1>,
                        h2: ({children}) => <h2 style={{ fontSize: '1.2em', margin: '10px 0 6px', color: '#60a5fa' }}>{children}</h2>,
                        h3: ({children}) => <h3 style={{ fontSize: '1.1em', margin: '8px 0 4px', color: '#60a5fa' }}>{children}</h3>,
                        hr: () => <hr style={{ border: 'none', borderTop: '1px solid #374151', margin: '12px 0' }} />,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  {msg.streaming && <span style={{ color: '#60a5fa' }}>▋</span>}
                </div>
                {/* Boutons d'action au survol */}
                <div style={{ position: 'absolute', top: -8, right: msg.role === 'user' ? 0 : 'auto', left: msg.role === 'assistant' ? 0 : 'auto', display: 'flex', gap: 4, opacity: 0.7 }}>
                  {msg.role === 'user' && !loading && (
                    <button 
                      onClick={() => startEditMessage(i)} 
                      title="Éditer et regénérer"
                      style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}
                    >
                      ✏️
                    </button>
                  )}
                  {msg.role === 'assistant' && i === messages.length - 1 && !loading && (
                    <button 
                      onClick={regenerateLastResponse} 
                      title="Regénérer"
                      style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}
                    >
                      🔄
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, color: '#6b7280', fontStyle: 'italic' }}>
            <span>En cours...</span>
            <button 
              onClick={cancelRequest}
              style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}
            >
              ✕ Annuler
            </button>
          </div>
        )}
        {error && <div style={{ color: '#f87171' }}>{error}</div>}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 16, background: '#1f2937', borderTop: '1px solid #374151' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Ton action... (Ctrl+Entrée pour envoyer)"
            disabled={loading}
            rows={2}
            style={{ 
              flex: 1, 
              padding: '8px 16px', 
              background: '#374151', 
              border: '1px solid #4b5563', 
              borderRadius: 4, 
              color: '#fff', 
              outline: 'none', 
              fontSize: fontSize,
              resize: 'vertical',
              minHeight: 44,
              maxHeight: 200,
              fontFamily: 'inherit'
            }}
          />
          <button onClick={sendMessage} disabled={loading} style={{ padding: '12px 24px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', opacity: loading ? 0.5 : 1, height: 44 }}>
            Envoyer
          </button>
        </div>
        <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
          Entrée = nouvelle ligne • Ctrl+Entrée = envoyer
        </div>
      </div>
    </div>
  );
}
