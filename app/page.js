'use client';
import { useState, useEffect, useRef } from 'react';

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
  const messagesEndRef = useRef(null);

  useEffect(() => { loadParties(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

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
    const res = await fetch('/api/chat?action=new');
    const data = await res.json();
    setPartieId(data.partieId);
    setPartieName('Nouvelle partie');
    setGameState(null);
    setMessages([]);
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

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMessage = input.trim();
    setInput('');
    setLoading(true);
    setError('');

    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage, partieId, gameState })
      });
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        return;
      }

      if (data.displayText) {
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: data.displayText
        }]);
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
        setMessages(prev => [...prev, { role: 'assistant', content: data.content }]);
      }

    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
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
          
          {/* Renommer */}
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

          {/* Supprimer */}
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
            <div style={{ display: 'inline-block', maxWidth: '80%', padding: 12, borderRadius: 8, background: msg.role === 'user' ? '#1e3a5f' : '#1f2937' }}>
              <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 14, margin: 0 }}>{msg.content}</pre>
            </div>
          </div>
        ))}
        {loading && <div style={{ color: '#6b7280', fontStyle: 'italic' }}>En cours...</div>}
        {error && <div style={{ color: '#f87171' }}>{error}</div>}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{ padding: 16, background: '#1f2937', borderTop: '1px solid #374151' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            placeholder="Ton action..."
            disabled={loading}
            style={{ flex: 1, padding: '8px 16px', background: '#374151', border: '1px solid #4b5563', borderRadius: 4, color: '#fff', outline: 'none' }}
          />
          <button onClick={sendMessage} disabled={loading} style={{ padding: '8px 24px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer', opacity: loading ? 0.5 : 1 }}>
            Envoyer
          </button>
        </div>
      </div>
    </div>
  );
    }
