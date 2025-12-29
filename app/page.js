'use client';
import { useState, useEffect, useRef } from 'react';

export default function Home() {
  const [parties, setParties] = useState([]);
  const [partieId, setPartieId] = useState(null);
  const [gameState, setGameState] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
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
    const res = await fetch(`/api/chat?action=load&partieId=${id}`);
    const data = await res.json();
    setPartieId(id);
    setGameState(data.state);
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

      if (data.parsed) {
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: `[${data.parsed.heure}] ${data.parsed.narratif}\n\n${data.parsed.choix?.map((c,i) => `${i+1}. ${c}`).join('\n') || ''}`
        }]);
        if (data.parsed.state) {
          setGameState({ partie: data.parsed.state, ...data.parsed.state });
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

  const dots = (n, max=5) => '●'.repeat(Math.min(n,max)) + '○'.repeat(Math.max(0,max-n));

  if (!partieId) {
    return (
      <div style={{ padding: 20, maxWidth: 600, margin: '0 auto' }}>
        <h1 style={{ color: '#60a5fa', marginBottom: 20 }}>LDVELH</h1>
        <button onClick={newGame} style={{ padding: '10px 20px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', marginBottom: 20, cursor: 'pointer' }}>
          Nouvelle partie
        </button>
        <h2 style={{ marginBottom: 10 }}>Parties existantes :</h2>
        {parties.map(p => (
          <div key={p.id} onClick={() => loadGame(p.id)} style={{ padding: 10, background: '#1f2937', marginBottom: 10, borderRadius: 4, cursor: 'pointer' }}>
            <strong>{p.nom}</strong> — Cycle {p.cycle_actuel}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div style={{ background: '#1f2937', padding: 12, borderBottom: '1px solid #374151' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ fontSize: 18, color: '#60a5fa' }}>LDVELH</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setShowState(!showState)} style={{ padding: '4px 12px', background: '#374151', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
              {showState ? 'Masquer' : 'État'}
            </button>
            <button onClick={() => { setPartieId(null); setMessages([]); }} style={{ padding: '4px 12px', background: '#7f1d1d', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
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

      {showState && (
        <div style={{ background: '#1f2937', padding: 12, maxHeight: 200, overflow: 'auto', borderBottom: '1px solid #374151' }}>
          <pre style={{ fontSize: 10, color: '#9ca3af' }}>{JSON.stringify(gameState, null, 2)}</pre>
        </div>
      )}

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
          <button onClick={sendMessage} disabled={loading} style={{ padding: '8px 24px', background: '#2563eb', border: 'none', borderRadius: 4, color: '#fff', cursor: 'pointer' }}>
            Envoyer
          </button>
        </div>
      </div>
    </div>
  );
}
