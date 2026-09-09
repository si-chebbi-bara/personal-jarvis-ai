import { useState, useRef, useEffect } from 'react'
import './ChatWindow.css'

// Where the FastAPI backend lives. Override with a VITE_API_BASE entry in
// frontend/.env when testing from another device (e.g. your phone on WiFi).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const PROVIDERS = ['auto', 'gemini', 'claude', 'openai', 'ollama']

// Speaker label shown above each bubble; anything else (e.g. 'jarvis') is Jarvis.
const ROLE_LABEL = { user: 'You', error: 'Error' }

/*
 * Centre panel: the chat itself. This is the original App.jsx chat logic moved
 * here almost unchanged. The one structural difference is that the message list
 * is NOT local state any more — it is owned by App.jsx (so switching chats in
 * the sidebar swaps the conversation) and arrives via props:
 *   - messages          the active chat's messages
 *   - onAppendMessages  append one or more messages to the active chat
 */
function ChatWindow({
  messages,
  onAppendMessages,
  provider,
  onProviderChange,
  onToggleToolPanel,
  toolPanelOpen,
}) {
  const [input, setInput] = useState('')
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

    onAppendMessages([{ role: 'user', text: command }])
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
      onAppendMessages([
        {
          role: 'jarvis',
          text: data.message || '(no message in response)',
          provider: data.provider,
          ok: data.success,
        },
      ])
    } catch (err) {
      onAppendMessages([
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
    <div className="chatwindow">
      <header className="chatwindow-header">
        <label className="chatwindow-provider">
          Provider:
          <select
            value={provider}
            onChange={(e) => onProviderChange(e.target.value)}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <button
          className="chatwindow-tooltoggle"
          onClick={onToggleToolPanel}
          aria-pressed={toolPanelOpen}
        >
          {toolPanelOpen ? 'Hide tool panel' : 'Preview tool panel'}
        </button>
      </header>

      <div className="chatwindow-messages" ref={scrollRef}>
        {messages.length === 0 && (
          <p className="chatwindow-empty">
            Ask Jarvis something — e.g. &ldquo;what&rsquo;s my battery&rdquo;,
            &ldquo;open firefox&rdquo;, &ldquo;take a screenshot&rdquo;.
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            <span className="who">
              {ROLE_LABEL[msg.role] || 'Jarvis'}
              {msg.provider ? ` (${msg.provider})` : ''}
            </span>
            <span className="text">{msg.text}</span>
          </div>
        ))}
        {busy && <div className="msg jarvis pending">Jarvis is thinking…</div>}
      </div>

      <footer className="chatwindow-composer">
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

export default ChatWindow
