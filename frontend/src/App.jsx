import { useState, useEffect } from 'react'
import './App.css'
import { API_BASE } from './api'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import ToolPanel from './components/ToolPanel'

const STORAGE_KEY = 'jarvis.chats'
const TITLE_MAX = 40
const HEALTH_RECHECK_MS = 5000
const HEALTH_TIMEOUT_MS = 4000

// Hard-coded sample content for the tool panel. The backend does not report
// tool activity yet; this stands in for a future event payload of the same
// shape ({ lines } for terminal, { url, body } for browser).
const MOCK_TOOL_CONTENT = {
  terminal: {
    lines: [
      '$ jarvis run "check disk space"',
      'Filesystem      Size  Used Avail Use% Mounted on',
      '/dev/nvme0n1p2  467G  312G  132G  71% /',
      '',
      '✓ done in 0.4s',
    ],
  },
  browser: {
    url: 'https://example.com/search?q=weather+today',
    body: 'Rendered page content would appear here.',
  },
}

const makeChat = () => ({
  id: crypto.randomUUID(),
  title: null,
  messages: [],
  updatedAt: Date.now(),
})

// Load persisted chats once at startup. A corrupt or missing value should just
// give an empty list, never crash the app.
function loadChats() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

// Title derived from the first user message — first ~40 chars, never a backend call.
function deriveTitle(text) {
  const clean = text.trim().replace(/\s+/g, ' ')
  return clean.length <= TITLE_MAX
    ? clean
    : clean.slice(0, TITLE_MAX).trimEnd() + '…'
}

// A copy of `chat` with messages appended and its title/timestamp refreshed.
function withMessages(chat, added) {
  const messages = [...chat.messages, ...added]
  const firstUser = messages.find((m) => m.role === 'user')
  return {
    ...chat,
    messages,
    title: chat.title || (firstUser ? deriveTitle(firstUser.text) : null),
    updatedAt: Date.now(),
  }
}

// Polls the backend's root endpoint so the UI can say plainly "Jarvis isn't
// running" instead of making the user find that out by sending a command and
// reading a fetch error. Keeps polling while offline so the banner clears
// itself the moment the backend comes up — no page reload needed.
function useBackendStatus() {
  const [status, setStatus] = useState('checking') // 'checking' | 'online' | 'offline'

  useEffect(() => {
    let cancelled = false
    let timer

    async function check() {
      try {
        const controller = new AbortController()
        const abortTimer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS)
        const res = await fetch(`${API_BASE}/`, { signal: controller.signal })
        clearTimeout(abortTimer)
        if (!cancelled) setStatus(res.ok ? 'online' : 'offline')
      } catch {
        if (!cancelled) setStatus('offline')
      } finally {
        if (!cancelled) timer = setTimeout(check, HEALTH_RECHECK_MS)
      }
    }

    check()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  return status
}

function App() {
  const backendStatus = useBackendStatus()
  const [mode, setMode] = useState('manual')
  const [chats, setChats] = useState(loadChats)
  const [activeChatId, setActiveChatId] = useState(null)
  const [provider, setProvider] = useState('auto')
  const [toolPanelOpen, setToolPanelOpen] = useState(false)
  const [activeTool, setActiveTool] = useState('terminal')

  // Persist on every change — localStorage is the only store of chat history.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats))
    } catch {
      // Storage full or blocked (private mode) — nothing useful to do.
    }
  }, [chats])

  const activeChat = chats.find((c) => c.id === activeChatId) || null

  function newChat() {
    const chat = makeChat()
    setChats((prev) => [chat, ...prev])
    setActiveChatId(chat.id)
  }

  // Append message(s) to the active chat, creating one first if none is active
  // (e.g. typing straight after a fresh page load). Newest chat sorts first.
  function appendMessages(added) {
    const target = activeChat || makeChat()
    if (!activeChat) setActiveChatId(target.id)

    setChats((prev) => {
      const list = prev.some((c) => c.id === target.id) ? prev : [target, ...prev]
      return list
        .map((c) => (c.id === target.id ? withMessages(c, added) : c))
        .sort((a, b) => b.updatedAt - a.updatedAt)
    })
  }

  return (
    <div className="app-shell">
      {backendStatus === 'offline' && (
        <div className="backend-banner" role="alert">
          Can&rsquo;t reach the Jarvis backend at <code>{API_BASE}</code> —
          start it with{' '}
          <code>uvicorn server:app --host 0.0.0.0 --port 8000</code> in the
          project folder. This will reconnect automatically.
        </div>
      )}
      <div className={'layout' + (toolPanelOpen ? ' has-tool' : '')}>
        <Sidebar
          mode={mode}
          onModeChange={setMode}
          chats={chats}
          activeChatId={activeChatId}
          onNewChat={newChat}
          onSelectChat={setActiveChatId}
        />
        <ChatWindow
          // Remount on chat switch so the composer draft and in-flight state
          // never leak from one conversation into another.
          key={activeChatId || 'no-chat'}
          messages={activeChat ? activeChat.messages : []}
          onAppendMessages={appendMessages}
          provider={provider}
          onProviderChange={setProvider}
          toolPanelOpen={toolPanelOpen}
          onToggleToolPanel={() => setToolPanelOpen((v) => !v)}
        />
        {toolPanelOpen && (
          <ToolPanel
            activeTool={activeTool}
            content={MOCK_TOOL_CONTENT[activeTool]}
            onSelectTool={setActiveTool}
            onClose={() => setToolPanelOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

export default App
