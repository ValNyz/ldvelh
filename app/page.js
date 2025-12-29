'use client';
import { useState, useEffect, useRef } from 'react';

export default function Home() {
  const [parties, setParties] = useState([]);
  const [partieId, setPartieId] = useState(null);
  const [gameState, setGameState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingGame, setLoadingGame] = useState(false);
  const [error, setError] = useState('');
  const [showState, setShowState] = useState(false);
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
      
      // Charger les messages depuis la base de données
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
    setGameState(null);
    setMessages([]);
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

      // Utiliser displayText au lieu de parser le JSON côté client
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
        // Fallback pour les réponses brutes (non-JSON)
        setMessages(prev => [...prev, { role: 'assistant', content: data.content }]);
      }

    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const dots = (n, max=5) => '●'.repeat(Math.min(n,max)) + '○'.repeat(Math.max(0,max-n));

  // Écran sélection partie
  if (!partieId) {
    return (
      <div style={{ padding: 20, maxWidth: 600, margin: '0 auto' }}>
        <h1 style={{ color: '#60a5fa', marginBottom: 20 }}>LDVELH</h1>
        <button onClick={newGame} style={{ padding: '10px 20px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', marginBottom: 20, cursor: 'pointer' }}>
          Nouvelle partie
        </button>
        <h2 style={{ marginBottom: 10 }}>Parties existantes :</h2>
        {parties.length === 0 && <p style={{ color: '#6b7280' }}>Aucune partie sauvegardée</p>}
        {parties.map(p => (
          <div key={p.id} onClick={() => loadGame(p.id)} style={{ padding: 10, background: '#1f2937', marginBottom: 10, borderRadius: 4, cursor: 'pointer' }}>
            <strong>{p.nom}</strong> — Cycle {p.cycle_actuel || 0}
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
          <h1 style={{ fontSize: 18, color: '#60a5fa' }}>LDVELH</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setShowState(!showState)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
              {showState ? 'Masquer' : 'État'}
            </button>
            <button onClick={() => { setPartieId(null); setMessages([]); setGameState(null); }} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
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
