import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { API_BASE } from '../api'
import './ChatWindow.css'

const PROVIDERS = ['auto', 'gemini', 'claude', 'openai', 'ollama']

// Speaker label shown above each bubble; anything else (e.g. 'jarvis') is Jarvis.
const ROLE_LABEL = { user: 'You', error: 'Error' }

// Automatic mode's compact inline lines (one per tool call, plus notices like
// "Stopped") — rendered without a speaker label or bubble.
const INLINE_ROLES = new Set(['step', 'note'])

// How much of a tool's result to show on its inline "→ ran …" line; the full
// text is in the line's tooltip and in the tool panel's Activity tab.
const STEP_PREVIEW = 140

// "→ ran get_system_stats: CPU 2% | RAM 36% …" — whitespace collapsed so
// multi-line shell output stays on one line.
function stepLine(step) {
  const detail = (step.message || '').replace(/\s+/g, ' ').trim()
  const short =
    detail.length > STEP_PREVIEW
      ? detail.slice(0, STEP_PREVIEW).trimEnd() + '…'
      : detail
  return `→ ran ${step.tool}${short ? `: ${short}` : ''}`
}

// Yields each `data:` payload of a Server-Sent Events response, parsed as
// JSON. EventSource can only GET, so POST /api/command/auto is read by hand.
async function* readEvents(body) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    let end
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const data = buffer
        .slice(0, end)
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      buffer = buffer.slice(end + 2)
      if (data) yield JSON.parse(data)
    }
  }
}

// A plain fetch TypeError ("NetworkError...", "Failed to fetch") means the
// request never reached a server at all — almost always the backend just
// isn't running yet, not a real error to troubleshoot.
function describeFetchError(err) {
  return err instanceof TypeError
    ? `Can't reach the Jarvis backend at ${API_BASE} — make sure "uvicorn server:app" is running.`
    : `Could not reach Jarvis: ${err.message}`
}

/*
 * Centre panel: the chat itself. This is the original App.jsx chat logic moved
 * here almost unchanged. The one structural difference is that the message list
 * is NOT local state any more — it is owned by App.jsx (so switching chats in
 * the sidebar swaps the conversation) and arrives via props:
 *   - messages          the active chat's messages
 *   - onAppendMessages  append one or more messages to the active chat (or to
 *                       the chat id passed as its second argument); returns
 *                       the id of the chat it appended to
 *
 * `mode` picks what sending does: 'manual' is one POST /api/command, one
 * reply. 'automatic' streams POST /api/command/auto — Jarvis chains tool calls
 * toward a goal (backend-capped at 8 turns), each step lands in the chat as it
 * completes, and a Stop button aborts the stream, which ends the loop.
 */
function ChatWindow({
  mode,
  messages,
  onAppendMessages,
  provider,
  onProviderChange,
  onToggleToolPanel,
  toolPanelOpen,
  onOpenSidebar,
  onToolActivity,
}) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  // Non-null while an Automatic run is in flight: the live status line
  // ("Step 2/8: running get_system_stats…"), and the cue to show Stop.
  const [progress, setProgress] = useState(null)
  const abortRef = useRef(null)
  const scrollRef = useRef(null)

  // Leaving this chat (ChatWindow remounts on a switch) stops a running
  // Automatic loop rather than leaving it working with no Stop button.
  useEffect(() => () => abortRef.current?.abort(), [])

  // Keep the chat scrolled to the newest message.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, progress])

  async function send() {
    const command = input.trim()
    if (!command || busy) return

    const chatId = onAppendMessages([{ role: 'user', text: command }])
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
      ], chatId)
      // Surface real tool calls (open_app, run_shell_command, etc.) in the
      // tool panel's Activity tab — only present when the executor actually
      // ran something, per core/executor.py.
      onToolActivity(data.calls)
    } catch (err) {
      onAppendMessages([{ role: 'error', text: describeFetchError(err) }], chatId)
    } finally {
      setBusy(false)
    }
  }

  async function sendAuto() {
    const command = input.trim()
    if (!command || busy) return

    const chatId = onAppendMessages([{ role: 'user', text: command }])
    setInput('')
    setBusy(true)
    setProgress('Starting…')
    const controller = new AbortController()
    abortRef.current = controller

    let finished = false
    let maxSteps = 8
    try {
      const res = await fetch(`${API_BASE}/api/command/auto`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, provider }),
        signal: controller.signal,
      })
      if (!res.ok) {
        throw new Error(`Backend returned HTTP ${res.status}`)
      }
      for await (const event of readEvents(res.body)) {
        if (event.type === 'start') {
          maxSteps = event.max_iterations || maxSteps
          setProgress(`Working on it with ${event.provider}…`)
        } else if (event.type === 'notice') {
          onAppendMessages([{ role: 'note', text: event.message }], chatId)
        } else if (event.type === 'turn') {
          setProgress(
            `Step ${event.iteration}/${maxSteps}: running ${event.tools.join(', ')}…`,
          )
        } else if (event.type === 'step') {
          const { tool, arguments: args, success, message, output, error } = event
          onAppendMessages(
            [{ role: 'step', text: stepLine(event), detail: message, ok: success }],
            chatId,
          )
          // Same record shape as Manual mode's `calls`, so the Activity tab
          // shows every step as it happens.
          onToolActivity([{ tool, arguments: args, success, message, output, error }])
        } else if (event.type === 'final') {
          finished = true
          onAppendMessages(
            [
              {
                role: 'jarvis',
                text: event.message || '(no message in response)',
                provider: event.provider,
                ok: event.success,
              },
            ],
            chatId,
          )
        }
      }
      if (!finished) {
        throw new Error('the connection closed before Jarvis finished.')
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        onAppendMessages(
          [{ role: 'note', text: 'Stopped — Jarvis won’t run any more steps for this goal.' }],
          chatId,
        )
      } else {
        onAppendMessages([{ role: 'error', text: describeFetchError(err) }], chatId)
      }
    } finally {
      abortRef.current = null
      setBusy(false)
      setProgress(null)
    }
  }

  const automatic = mode === 'automatic'
  const submit = automatic ? sendAuto : send

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="chatwindow">
      <header className="chatwindow-header">
        <div className="chatwindow-header-left">
          {/* Only shown below the mobile breakpoint (see App.css) — desktop
              keeps the sidebar visible so there's nothing to open. */}
          <button
            className="chatwindow-menubtn"
            onClick={onOpenSidebar}
            aria-label="Open sidebar"
          >
            ☰
          </button>
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
        </div>
        <button
          className="chatwindow-tooltoggle"
          onClick={onToggleToolPanel}
          aria-pressed={toolPanelOpen}
        >
          {toolPanelOpen ? 'Hide tool panel' : 'Open tool panel'}
        </button>
      </header>

      <div className="chatwindow-messages" ref={scrollRef}>
        {messages.length === 0 &&
          (automatic ? (
            <p className="chatwindow-empty">
              Give Jarvis a goal and it will work through it step by step — e.g.
              &ldquo;check disk space and clean up temp files if it&rsquo;s over
              90% full&rdquo;.
            </p>
          ) : (
            <p className="chatwindow-empty">
              Ask Jarvis something — e.g. &ldquo;what&rsquo;s my battery&rdquo;,
              &ldquo;open firefox&rdquo;, &ldquo;take a screenshot&rdquo;.
            </p>
          ))}
        {/* Index keys are safe here: messages are only ever appended, never
            reordered or removed within a conversation. */}
        {messages.map((msg, i) =>
          INLINE_ROLES.has(msg.role) ? (
            <div
              key={i}
              className={`msg ${msg.role}` + (msg.ok === false ? ' failed' : '')}
              title={msg.detail}
            >
              {msg.text}
            </div>
          ) : (
            <div key={i} className={`msg ${msg.role}`}>
              <span className="who">
                {ROLE_LABEL[msg.role] || 'Jarvis'}
                {msg.provider ? ` (${msg.provider})` : ''}
              </span>
              <div className="text">
                {msg.role === 'jarvis' ? (
                  <ReactMarkdown>{msg.text}</ReactMarkdown>
                ) : (
                  msg.text
                )}
              </div>
            </div>
          ),
        )}
        {busy && (
          <div className="msg jarvis pending">{progress || 'Jarvis is thinking…'}</div>
        )}
      </div>

      <footer className="chatwindow-composer">
        <textarea
          rows={1}
          value={input}
          placeholder={
            automatic
              ? 'Describe a goal and press Enter'
              : 'Type a command and press Enter'
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />
        {progress !== null ? (
          <button className="stop" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button onClick={submit} disabled={busy || !input.trim()}>
            Send
          </button>
        )}
      </footer>
    </div>
  )
}

export default ChatWindow
