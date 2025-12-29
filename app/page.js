'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
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

  // Détecter le client (pour localStorage)
  useEffect(() => {
    setIsClient(true);
  }, []);

  useEffect(() => { loadParties(); }, []);
  
  // Charger la taille de police depuis localStorage (côté client uniquement)
  useEffect(() => {
    if (isClient) {
      const saved = localStorage.getItem('ldvelh-fontsize');
      if (saved) setFontSize(parseInt(saved, 10));
    }
  }, [isClient]);

  // Scroll auto seulement si l'utilisateur n'a pas scrollé vers le haut
  useEffect(() => { 
    if (!userScrolledUp.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); 
    }
  }, [messages]);

  // Auto-resize du textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
    }
  }, [input]);

  // Détecter si l'utilisateur scroll vers le haut
  const handleScroll = (e) => {
    const { scrollTop, scrollHeight, clientHeight } = e.target;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
    userScrolledUp.current = !isAtBottom;
  };

  // Reset le scroll quand on envoie un nouveau message
  const resetScrollBehavior = () => {
    userScrolledUp.current = false;
  };

  const changeFontSize = (delta) => {
    const newSize = Math.min(24, Math.max(10, fontSize + delta));
    setFontSize(newSize);
    if (isClient) {
      localStorage.setItem('ldvelh-fontsize', newSize.toString());
    }
  };

  const loadParties = async () => {
    try {
      const res = await fetch('/api/chat?action=list');
      const data = await res.json();
      setParties(data.parties || []);
    } catch (e) {
      console.error('Erreur chargement parties:', e);
    }
  };

  const loadGame = async (id) => {
    setLoadingGame(true);
    setError('');
    try {
      const res = await fetch(`/api/chat?action=load&partieId=${id}`);
      const data = await res.json();
      
      if (data.error) {
        setError(data.error);
        return;
      }
      
      setPartieId(id);
      
      if (data.state) {
        const state = data.state;
        setGameState({
          partie: state.partie,
          cycle: state.partie?.cycle_actuel || 1,
          jour: state.partie?.jour,
          valentin: state.valentin,
          ia: state.ia,
          contexte: state.contexte,
          pnj: state.pnj || [],
          arcs: state.arcs || [],
          historique: state.historique || [],
          aVenir: state.aVenir || [],
          lieux: state.lieux || [],
          horsChamp: state.horsChamp || []
        });
        setPartieName(state.partie?.nom || 'Partie sans nom');
      }
      
      if (data.messages && data.messages.length > 0) {
        setMessages(data.messages.map(m => ({
          role: m.role,
          content: m.content
        })));
      } else {
        setMessages([]);
      }
    } catch (e) {
      console.error('Load game error:', e);
      setError('Erreur lors du chargement de la partie');
    } finally {
      setLoadingGame(false);
    }
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
      } else {
        setError(data.error || 'Erreur lors de la création de la partie');
      }
    } catch (e) {
      setError('Erreur lors de la création de la partie');
    } finally {
      setLoadingGame(false);
    }
  };

  const deleteGame = async (id) => {
    try {
      const res = await fetch(`/api/chat?action=delete&partieId=${id}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        return;
      }
      setConfirmDelete(null);
      loadParties();
    } catch (e) {
      setError('Erreur lors de la suppression');
    }
  };

  const renameGame = async () => {
    if (!newName.trim()) return;
    try {
      await fetch(`/api/chat?action=rename&partieId=${partieId}&name=${encodeURIComponent(newName.trim())}`);
      setPartieName(newName.trim());
      setEditingName(false);
      setNewName('');
    } catch (e) {
      setError('Erreur lors du renommage');
    }
  };

  // Annuler la requête en cours
  const cancelRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setLoading(false);
      // Retirer le flag streaming du dernier message si présent
      setMessages(prev => {
        const newMessages = [...prev];
        if (newMessages.length > 0 && newMessages[newMessages.length - 1].streaming) {
          newMessages[newMessages.length - 1] = {
            ...newMessages[newMessages.length - 1],
            streaming: false,
            content: newMessages[newMessages.length - 1].content + '\n\n*(Annulé)*'
          };
        }
        return newMessages;
      });
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
    
    // Capturer le state actuel AVANT de modifier
    const currentMessages = [...messages];
    const previousMessages = currentMessages.slice(0, messageIndex);
    const currentGameState = gameState;
    
    setEditingMessageIndex(null);
    setEditedContent('');
    setLoading(true);
    setError('');
    resetScrollBehavior();

    // Mettre à jour l'affichage
    setMessages([...previousMessages, { role: 'user', content: newContent }]);

    // Supprimer les messages en BDD à partir de cet index
    if (partieId) {
      try {
        await fetch('/api/chat', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ partieId, fromIndex: messageIndex })
        });
      } catch (e) {
        console.error('Erreur suppression messages:', e);
      }
    }

    // Regénérer avec le nouveau message
    await sendMessageInternal(newContent, previousMessages, currentGameState);
  };

  // Regénérer le dernier message assistant
  const regenerateLastResponse = async () => {
    if (loading || messages.length < 2) return;
    
    // Capturer le state actuel
    const currentMessages = [...messages];
    const currentGameState = gameState;
    
    // Trouver le dernier message user
    let lastUserIndex = currentMessages.length - 1;
    while (lastUserIndex >= 0 && currentMessages[lastUserIndex].role !== 'user') {
      lastUserIndex--;
    }
    if (lastUserIndex < 0) return;

    const userMessage = currentMessages[lastUserIndex].content;
    const previousMessages = currentMessages.slice(0, lastUserIndex);
    
    setMessages([...previousMessages, { role: 'user', content: userMessage }]);
    setLoading(true);
    setError('');
    resetScrollBehavior();

    // Supprimer le dernier échange en BDD
    if (partieId) {
      try {
        await fetch('/api/chat', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ partieId, fromIndex: lastUserIndex })
        });
      } catch (e) {
        console.error('Erreur suppression:', e);
      }
    }

    await sendMessageInternal(userMessage, previousMessages, currentGameState);
  };

  const sendMessage = async () => {
    if (!input.trim() || loading || saving) return;
    const userMessage = input.trim();
    const currentMessages = [...messages];
    const currentGameState = gameState;
    
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setLoading(true);
    setError('');
    resetScrollBehavior();
    
    await sendMessageInternal(userMessage, currentMessages, currentGameState);
  };

  const sendMessageInternal = async (userMessage, previousMessages, currentGameState) => {
    abortControllerRef.current = new AbortController();

    // Fonction pour extraire le narratif du JSON partiel
    const extractNarratif = (jsonStr) => {
      const startMatch = jsonStr.match(/"narratif"\s*:\s*"/);
      if (!startMatch) return null;
      
      const startIndex = startMatch.index + startMatch[0].length;
      let narratif = '';
      let i = startIndex;
      
      while (i < jsonStr.length) {
        const char = jsonStr[i];
        
        if (char === '\\' && i + 1 < jsonStr.length) {
          const nextChar = jsonStr[i + 1];
          if (nextChar === 'n') { narratif += '\n'; i += 2; }
          else if (nextChar === '"') { narratif += '"'; i += 2; }
          else if (nextChar === '\\') { narratif += '\\'; i += 2; }
          else if (nextChar === 't') { narratif += '\t'; i += 2; }
          else if (nextChar === 'r') { narratif += '\r'; i += 2; }
          else { break; }
        } else if (char === '"') {
          break;
        } else {
          narratif += char;
          i++;
        }
      }
      
      return narratif || null;
    };

    const extractHeure = (jsonStr) => {
      const heureMatch = jsonStr.match(/"heure"\s*:\s*"([^"]+)"/);
      return heureMatch ? heureMatch[1] : null;
    };

    // Fonction pour extraire le contenu affichable (gère JSON pur ou texte mixte)
    const extractDisplayContent = (content) => {
      const trimmed = content.trim();
      
      // Cas 1: JSON pur (commence par {)
      if (trimmed.startsWith('{')) {
        const narratif = extractNarratif(content);
        const heure = extractHeure(content);
        if (narratif) {
          return heure ? `[${heure}] ${narratif}` : narratif;
        }
        return null;
      }
      
      // Cas 2: Texte libre (peut-être avec JSON à la fin)
      // Retirer le JSON partiel à la fin s'il y en a un
      let displayContent = content;
      const jsonStartIndex = content.lastIndexOf('\n{');
      if (jsonStartIndex > 0) {
        displayContent = content.slice(0, jsonStartIndex).trim();
      }
      
      // Retirer les doublons d'heure du type "[09h15] [09h15]"
      displayContent = displayContent.replace(/\[(\d{2}h\d{2})\]\s*\[\1\]/g, '[$1]');
      
      return displayContent || null;
    };

    // Helper pour finaliser le message (retirer streaming)
    const finalizeMessage = (content) => {
      setMessages([...previousMessages,
        { role: 'user', content: userMessage },
        { role: 'assistant', content }
      ]);
    };

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage, partieId, gameState: currentGameState }),
        signal: abortControllerRef.current.signal
      });

      const contentType = res.headers.get('content-type');
      
      if (contentType?.includes('text/event-stream')) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullJson = '';
        let assistantMessageAdded = false;

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
                    
                    const displayContent = extractDisplayContent(fullJson);
                    
                    if (displayContent) {
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
                    // Toujours utiliser displayText du serveur s'il existe et contient des choix
                    let finalContent = data.displayText;
                    
                    // Si pas de displayText ou pas de choix dedans, essayer de reconstruire
                    if (!finalContent || !finalContent.includes('1.')) {
                      const narratif = extractNarratif(fullJson);
                      const heure = extractHeure(fullJson);
                      const choixMatch = fullJson.match(/"choix"\s*:\s*\[([\s\S]*?)\]/);
                      
                      if (narratif) {
                        finalContent = heure ? `[${heure}] ${narratif}` : narratif;
                        
                        // Extraire et ajouter les choix
                        if (choixMatch) {
                          try {
                            const choixArray = JSON.parse(`[${choixMatch[1]}]`);
                            if (choixArray.length > 0) {
                              finalContent += '\n\n' + choixArray.map((c, i) => `${i + 1}. ${c}`).join('\n');
                            }
                          } catch (e) {
                            // Ignore parsing errors
                          }
                        }
                      }
                    }
                    
                    finalizeMessage(finalContent || extractDisplayContent(fullJson) || fullJson);
                    
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
                    
                    // Attendre la confirmation de sauvegarde
                    setSaving(true);
                  } else if (data.type === 'saved') {
                    // Sauvegarde terminée
                    setSaving(false);
                  } else if (data.type === 'error') {
                    setError(data.error);
                    if (fullJson) {
                      finalizeMessage(extractDisplayContent(fullJson) || fullJson);
                    }
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
            const displayContent = extractDisplayContent(fullJson);
            if (displayContent || fullJson) {
              finalizeMessage(displayContent || fullJson);
            }
          }
        }
      } else {
        const data = await res.json();

        if (data.error) {
          setError(data.error);
          return;
        }

        if (data.displayText) {
          finalizeMessage(data.displayText);
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
          finalizeMessage(data.content);
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
      <div 
        ref={messagesContainerRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflow: 'auto', padding: 16 }}
      >
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
              <div 
                style={{ display: 'inline-block', maxWidth: msg.role === 'user' ? '80%' : '95%', position: 'relative' }}
                className="message-container"
              >
                <div style={{ padding: 12, borderRadius: 8, background: msg.role === 'user' ? '#1e3a5f' : '#1f2937', maxWidth: msg.role === 'user' ? '80%' : '95%' }}>
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
                <div className="message-actions" style={{ position: 'absolute', top: -8, right: msg.role === 'user' ? 0 : 'auto', left: msg.role === 'assistant' ? 0 : 'auto', display: 'flex', gap: 4, opacity: 0, transition: 'opacity 0.2s' }}>
                  {msg.role === 'user' && !loading && (
                    <button 
                      onClick={() => startEditMessage(i)} 
                      title="Éditer et regénérer"
                      style={{ padding: '2px 6px', background: '#374151', border: 'none', borderRadius: 4, color: '#9ca3af', cursor: 'pointer', fontSize: 10 }}
                    >
                      ✏️
                    </button>
                  )}
                  {msg.role === 'assistant' && i === messages.length - 1 && !loading && !msg.streaming && (
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
        {loading && !messages.some(m => m.streaming) && (
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
        {loading && messages.some(m => m.streaming) && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
            <button 
              onClick={cancelRequest}
              style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', fontSize: 12 }}
            >
              ✕ Annuler
            </button>
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
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Ton action... (Ctrl+Entrée pour envoyer)"
            disabled={loading}
            style={{ 
              flex: 1, 
              padding: '8px 16px', 
              background: '#374151', 
              border: '1px solid #4b5563', 
              borderRadius: 4, 
              color: '#fff', 
              outline: 'none', 
              fontSize: fontSize,
              resize: 'none',
              minHeight: 44,
              maxHeight: 200,
              fontFamily: 'inherit',
              overflow: 'hidden'
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

      {/* CSS pour le hover des boutons d'action */}
      <style jsx>{`
        .message-container:hover .message-actions {
          opacity: 1 !important;
        }
      `}</style>
    </div>
  );
}
