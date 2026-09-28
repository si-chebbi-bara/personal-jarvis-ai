import { useState, useRef, useEffect } from 'react'
import { API_BASE } from '../api'
import './ToolPanel.css'

const TOOLS = ['activity', 'terminal']
const TOOL_LABEL = { activity: 'Activity', terminal: 'Terminal' }

// Renders one call's arguments as compact JSON, e.g. {app_name: "firefox"} —
// falls back to '—' rather than an empty '{}' for no-argument tools.
function formatArgs(args) {
  if (!args || Object.keys(args).length === 0) return '—'
  try {
    return JSON.stringify(args)
  } catch {
    return String(args)
  }
}

function formatTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

/*
 * Right-hand panel — two real, backend-backed views (no mock data):
 *   - activity   read-only feed of tool calls Jarvis has actually run via
 *                chat (open_app, run_shell_command, etc.), passed down from
 *                App.jsx as `activity` (see core/executor.py's `calls`).
 *   - terminal   a real terminal that hits POST /api/shell directly,
 *                bypassing the LLM — same blocklist/timeout/logging as any
 *                shell call made through chat.
 * There used to be a third "browser" tab with hardcoded sample content; it
 * was removed because there's no working browser-automation feature behind
 * it (Selenium was abandoned early on — see the repo's known gotchas).
 */
function ToolPanel({ activeTool, activity, onClose, onSelectTool }) {
  return (
    <aside className="toolpanel">
      <header className="toolpanel-header">
        <span className="toolpanel-title">{TOOL_LABEL[activeTool] || 'Tool panel'}</span>
        <div className="toolpanel-switch">
          {TOOLS.map((tool) => (
            <button
              key={tool}
              className={activeTool === tool ? 'active' : ''}
              onClick={() => onSelectTool(tool)}
            >
              {TOOL_LABEL[tool]}
            </button>
          ))}
        </div>
        <button className="toolpanel-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <div className="toolpanel-body">
        {activeTool === 'activity' && <ActivityView activity={activity} />}
        {activeTool === 'terminal' && <TerminalView />}
      </div>
    </aside>
  )
}

function ActivityView({ activity }) {
  const scrollRef = useRef(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activity])

  if (!activity || activity.length === 0) {
    return (
      <div className="toolpanel-idle">
        No tool calls yet — ask Jarvis to do something (e.g. &ldquo;what&rsquo;s my
        battery&rdquo; or &ldquo;open firefox&rdquo;) and it&rsquo;ll show up here.
      </div>
    )
  }

  return (
    <div className="toolpanel-activity" ref={scrollRef}>
      {activity.map((call, i) => (
        <div key={i} className={'activity-item' + (call.success ? '' : ' failed')}>
          <div className="activity-item-head">
            <span className="activity-tool">{call.tool}</span>
            <span className="activity-args">{formatArgs(call.arguments)}</span>
            <span className="activity-time">{formatTime(call.ts)}</span>
          </div>
          <div className="activity-message">{call.message}</div>
        </div>
      ))}
    </div>
  )
}

// A real terminal: every command goes straight to POST /api/shell (the same
// run_shell_command the LLM can call, minus the LLM) and shows real
// stdout/stderr. Subject to the backend's blocklist/timeout, same as chat.
function TerminalView() {
  const [history, setHistory] = useState([]) // { command, success, output, error, message }
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [history])

  async function run() {
    const command = input.trim()
    if (!command || busy) return
    setInput('')
    setBusy(true)

    try {
      const res = await fetch(`${API_BASE}/api/shell`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      })
      if (!res.ok) throw new Error(`Backend returned HTTP ${res.status}`)
      const data = await res.json()
      setHistory((prev) => [...prev, { command, ...data }])
    } catch (err) {
      const message =
        err instanceof TypeError
          ? `Can't reach the Jarvis backend at ${API_BASE}.`
          : `Request failed: ${err.message}`
      setHistory((prev) => [...prev, { command, success: false, message }])
    } finally {
      setBusy(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter') {
      e.preventDefault()
      run()
    }
  }

  return (
    <div className="toolpanel-terminal-wrap">
      <pre className="toolpanel-terminal" ref={scrollRef}>
        {history.length === 0 && (
          <span className="toolpanel-terminal-hint">
            Runs directly against the machine Jarvis is on — bypasses the LLM,
            subject to the same safety blocklist and 30s timeout as a
            chat-triggered command.
          </span>
        )}
        {history.map((h, i) => (
          <div key={i} className={'terminal-line' + (h.success ? '' : ' failed')}>
            <div>$ {h.command}</div>
            <div className="terminal-output">{h.output || h.message}</div>
            {h.error ? <div className="terminal-stderr">{h.error}</div> : null}
          </div>
        ))}
      </pre>
      <div className="toolpanel-terminal-input">
        <span className="toolpanel-terminal-prompt">$</span>
        <input
          value={input}
          placeholder="Type a shell command and press Enter"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={busy}
        />
      </div>
    </div>
  )
}

export default ToolPanel
