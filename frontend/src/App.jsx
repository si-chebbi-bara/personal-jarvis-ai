import { useState, useEffect } from 'react'
import './App.css'
import Sidebar from './components/Sidebar'
import ChatWindow from './components/ChatWindow'
import ToolPanel from './components/ToolPanel'

// Hard-coded sample content for the tool panel. The backend does not report
// tool activity yet, so this stands in for a future real event payload that
// will arrive in the same { lines } / { url, body } shape.
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

const STORAGE_KEY = 'jarvis.chats'
const TITLE_MAX = 40

// Load persisted chats once at startup. Wrapped defensively: a corrupt or
// missing value should just give us an empty list, never crash the app.
function loadChats() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

// Derive a chat title from its first user message. Never calls the backend.
function deriveTitle(text) {
  const clean = text.trim().replace(/\s+/g, ' ')
  if (clean.length <= TITLE_MAX) return clean
  return clean.slice(0, TITLE_MAX).trimEnd() + '…'
}

function App() {
  const [mode, setMode] = useState('manual')
  const [chats, setChats] = useState(loadChats)
  const [activeChatId, setActiveChatId] = useState(null)
  const [provider, setProvider] = useState('auto')
  const [toolPanelOpen, setToolPanelOpen] = useState(false)
  const [activeTool, setActiveTool] = useState('terminal')

  // Persist the whole chat list on every change. localStorage is the only
  // source of truth for history right now — the backend has no notion of
  // conversations.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(chats))
    } catch {
      // Storage full or blocked (private mode) — nothing useful to do here.
    }
  }, [chats])

  const activeChat = chats.find((c) => c.id === activeChatId) || null

  function newChat() {
    const id = crypto.randomUUID()
    setChats((prev) => [
      { id, title: null, messages: [], updatedAt: Date.now() },
      ...prev,
    ])
    setActiveChatId(id)
  }

  // Append one or more messages to the active chat. If there is no active chat
  // yet (fresh page load, straight into typing) create one on the fly. Also
  // fills in the title from the first user message and bumps updatedAt so the
  // chat floats to the top of Recent.
  function appendMessages(newMessages) {
    // Pre-compute a fresh id so both state updates below agree on it without
    // one setter reaching into the other.
    const fallbackId = crypto.randomUUID()
    const haveActive = chats.some((c) => c.id === activeChatId)
    const targetId = haveActive ? activeChatId : fallbackId
    if (!haveActive) setActiveChatId(fallbackId)

    setChats((prev) => {
      const list = prev.some((c) => c.id === targetId)
        ? prev
        : [
            { id: targetId, title: null, messages: [], updatedAt: Date.now() },
            ...prev,
          ]

      const updated = list.map((chat) => {
        if (chat.id !== targetId) return chat
        const messages = [...chat.messages, ...newMessages]
        let title = chat.title
        if (!title) {
          const firstUser = messages.find((m) => m.role === 'user')
          if (firstUser) title = deriveTitle(firstUser.text)
        }
        return { ...chat, messages, title, updatedAt: Date.now() }
      })

      // Keep Recent ordered newest-first.
      updated.sort((a, b) => b.updatedAt - a.updatedAt)
      return updated
    })
  }

  return (
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
  )
}

export default App
