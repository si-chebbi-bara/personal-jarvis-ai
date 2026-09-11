import './Sidebar.css'

const APP_VERSION = '0.1.0'

// Top-of-rail mode switcher. Labels are placeholders and will be renamed later,
// so they live in one place. 'manual' is the default (see App.jsx).
const MODES = { manual: 'Manual', automatic: 'Automatic' }

// Compact "time ago" label for the Recent list. Kept local because the sidebar
// is the only place that needs it.
function relativeTime(ts) {
  if (!ts) return ''
  const seconds = Math.round((Date.now() - ts) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

/*
 * Left rail. Purely presentational: every piece of state (which mode is active,
 * the list of chats, which one is selected) lives in App.jsx and arrives here as
 * props, along with callbacks for the user actions.
 */
function Sidebar({
  mode,
  onModeChange,
  chats,
  activeChatId,
  onNewChat,
  onSelectChat,
}) {
  return (
    <div className="sidebar">
      <div className="sidebar-switcher">
        {Object.entries(MODES).map(([key, label]) => (
          <button
            key={key}
            className={mode === key ? 'active' : ''}
            onClick={() => onModeChange(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="sidebar-body">
        {mode === 'manual' ? (
          <>
            <button className="sidebar-newchat" onClick={onNewChat}>
              + New chat
            </button>

            <div className="sidebar-section-label">Recent</div>
            <ul className="sidebar-recent">
              {chats.length === 0 && (
                <li className="sidebar-recent-empty">No chats yet</li>
              )}
              {chats.map((chat) => (
                <li key={chat.id}>
                  <button
                    className={
                      'sidebar-recent-item' +
                      (chat.id === activeChatId ? ' active' : '')
                    }
                    onClick={() => onSelectChat(chat.id)}
                  >
                    <span className="sidebar-recent-title">
                      {chat.title || 'New chat'}
                    </span>
                    <span className="sidebar-recent-time">
                      {relativeTime(chat.updatedAt)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="sidebar-automatic-placeholder">
            Automatic mode is coming soon.
          </div>
        )}
      </div>

      <div className="sidebar-footer">
        <span>Jarvis</span>
        <span className="sidebar-version">v{APP_VERSION}</span>
      </div>
    </div>
  )
}

export default Sidebar
