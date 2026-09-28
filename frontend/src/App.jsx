import { useState, useEffect } from 'react'
import './App.css'
import { API_BASE } from './api'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import ToolPanel from './components/ToolPanel'

const STORAGE_KEY = 'jarvis.chats'
const ACTIVE_CHAT_KEY = 'jarvis.activeChatId'
const TITLE_MAX = 40
const HEALTH_RECHECK_MS = 5000
const HEALTH_TIMEOUT_MS = 4000
const MAX_ACTIVITY = 50

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

// Restore the chat that was open before a reload. Only trust the stored id if
// it still points at a real chat — a stale id (from a chat that no longer
// exists) should fall back to "no chat selected", not a blank crash.
function loadActiveChatId(chats) {
  try {
    const id = localStorage.getItem(ACTIVE_CHAT_KEY)
    return id && chats.some((c) => c.id === id) ? id : null
  } catch {
    return null
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
  const [activeChatId, setActiveChatId] = useState(() => loadActiveChatId(loadChats()))
  const [chatViewKey, setChatViewKey] = useState(0)
  const [provider, setProvider] = useState('auto')
  const [toolPanelOpen, setToolPanelOpen] = useState(false)
  const [activeTool, setActiveTool] = useState('activity')
  // Off-canvas sidebar toggle, only relevant below the mobile breakpoint (see
  // App.css) — on desktop the sidebar is always visible and this is unused.
  const [sidebarOpen, setSidebarOpen] = useState(false)
  // Real record of tool calls Jarvis has actually run via chat (open_app,
  // run_shell_command, etc.) — fed by ChatWindow from /api/command's `calls`
  // field. Global rather than per-chat: it's "what Jarvis has been doing",
  // not part of any one conversation's transcript.
  const [toolActivity, setToolActivity] = useState([])

  function addToolActivity(calls) {
    if (!calls || !calls.length) return
    const stamped = calls.map((c) => ({ ...c, ts: Date.now() }))
    setToolActivity((prev) => [...prev, ...stamped].slice(-MAX_ACTIVITY))
  }

  // Persist on every change — localStorage is the only store of chat history.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats))
    } catch {
      // Storage full or blocked (private mode) — nothing useful to do.
    }
  }, [chats])

  // Remember which chat was open so a reload lands back on it instead of the
  // empty state.
  useEffect(() => {
    try {
      if (activeChatId) localStorage.setItem(ACTIVE_CHAT_KEY, activeChatId)
      else localStorage.removeItem(ACTIVE_CHAT_KEY)
    } catch {
      // Storage full or blocked (private mode) — nothing useful to do.
    }
  }, [activeChatId])

  const activeChat = chats.find((c) => c.id === activeChatId) || null

  function newChat() {
    const chat = makeChat()
    setChats((prev) => [chat, ...prev])
    switchChat(chat.id)
  }

  // Append message(s) to a chat and return that chat's id. With no chatId it
  // targets the active chat, creating one first if none is active (e.g. typing
  // straight after a fresh page load). Anything appended after an await (a
  // reply, Automatic mode's streamed steps) must pass back the id the first
  // call returned: the caller's `onAppendMessages` is from the render it
  // started in, where `activeChat` may still be null, so relying on it would
  // split one exchange across two chats. Newest chat sorts first.
  function appendMessages(added, chatId) {
    let targetId = chatId || (activeChat && activeChat.id)
    let fresh = null
    if (!targetId) {
      fresh = makeChat()
      targetId = fresh.id
      setActiveChatId(targetId)
    }

    setChats((prev) => {
      const list = fresh ? [fresh, ...prev] : prev
      return list
        .map((c) => (c.id === targetId ? withMessages(c, added) : c))
        .sort((a, b) => b.updatedAt - a.updatedAt)
    })
    return targetId
  }

  // Explicit chat switches remount ChatWindow (see its `key`); a chat created
  // by sending the first message must not, or the in-flight request would
  // lose its busy indicator (and Automatic mode its Stop button).
  function switchChat(id) {
    if (id === activeChatId) return
    setActiveChatId(id)
    setChatViewKey((k) => k + 1)
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
          open={sidebarOpen}
          mode={mode}
          onModeChange={setMode}
          chats={chats}
          activeChatId={activeChatId}
          onNewChat={() => {
            newChat()
            setSidebarOpen(false)
          }}
          onSelectChat={(id) => {
            switchChat(id)
            setSidebarOpen(false)
          }}
        />
        {/* Mobile only (see App.css) — dims the chat behind the open drawer
            and closes it on tap, same as the hamburger button. */}
        {sidebarOpen && (
          <div
            className="sidebar-backdrop"
            onClick={() => setSidebarOpen(false)}
          />
        )}
        <ChatWindow
          // Remount on chat switch so the composer draft and in-flight state
          // never leak from one conversation into another.
          key={chatViewKey}
          mode={mode}
          messages={activeChat ? activeChat.messages : []}
          onAppendMessages={appendMessages}
          provider={provider}
          onProviderChange={setProvider}
          toolPanelOpen={toolPanelOpen}
          onToggleToolPanel={() => setToolPanelOpen((v) => !v)}
          onOpenSidebar={() => setSidebarOpen(true)}
          onToolActivity={addToolActivity}
        />
        {toolPanelOpen && (
          <ToolPanel
            activeTool={activeTool}
            activity={toolActivity}
            onSelectTool={setActiveTool}
            onClose={() => setToolPanelOpen(false)}
          />
        )}
      </div>
    </div>
  )
}

export default App
