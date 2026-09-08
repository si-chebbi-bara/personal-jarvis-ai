import { useState, useRef, useEffect } from 'react'
import './App.css'

// Where the FastAPI backend lives. Override with a VITE_API_BASE entry in
// frontend/.env when testing from another device (e.g. your phone on WiFi).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const PROVIDERS = ['auto', 'gemini', 'claude', 'openai', 'ollama']

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [provider, setProvider] = useState('auto')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)

  // Keep the chat scrolled to the newest message.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  async function send() {
    const command = input.trim()
    if (!command || busy) return

    setMessages((m) => [...m, { role: 'user', text: command }])
    setInput('')
    setBusy(true)

    try {
      const res = await fetch(`${API_BASE}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, provider }),
      })
      if (!res.ok) {
        throw new Error(`Backend returned HTTP ${res.status}`)
      }
      const data = await res.json()
      setMessages((m) => [
        ...m,
        {
          role: 'jarvis',
          text: data.message || '(no message in response)',
          provider: data.provider,
          ok: data.success,
        },
      ])
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'error', text: `Could not reach Jarvis: ${err.message}` },
      ])
    } finally {
      setBusy(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>Jarvis</h1>
        <label className="provider">
          Provider:
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      </header>

      <main className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <p className="empty">
            Ask Jarvis something — e.g. &ldquo;what&rsquo;s my battery&rdquo;,
            &ldquo;open firefox&rdquo;, &ldquo;take a screenshot&rdquo;.
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            <span className="who">
              {msg.role === 'user'
                ? 'You'
                : msg.role === 'error'
                  ? 'Error'
                  : 'Jarvis'}
              {msg.provider ? ` (${msg.provider})` : ''}
            </span>
            <span className="text">{msg.text}</span>
          </div>
        ))}
        {busy && <div className="msg jarvis pending">Jarvis is thinking…</div>}
      </main>

      <footer className="composer">
        <textarea
          rows={1}
          value={input}
          placeholder="Type a command and press Enter"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>
          Send
        </button>
      </footer>
    </div>
  )
}

export default App
