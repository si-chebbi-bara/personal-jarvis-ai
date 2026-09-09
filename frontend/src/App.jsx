import { useState, useEffect } from 'react'
import './App.css'
import Sidebar from './components/Sidebar'

const STORAGE_KEY = 'jarvis.chats'

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

function App() {
  const [mode, setMode] = useState('manual')
  const [chats, setChats] = useState(loadChats)
  const [activeChatId, setActiveChatId] = useState(null)

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

  function newChat() {
    const id = crypto.randomUUID()
    setChats((prev) => [
      { id, title: null, messages: [], updatedAt: Date.now() },
      ...prev,
    ])
    setActiveChatId(id)
  }

  return (
    <div className="layout">
      <Sidebar
        mode={mode}
        onModeChange={setMode}
        chats={chats}
        activeChatId={activeChatId}
        onNewChat={newChat}
        onSelectChat={setActiveChatId}
      />
      <main className="layout-chat">chat</main>
    </div>
  )
}

export default App
