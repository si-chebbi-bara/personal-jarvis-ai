import './ToolPanel.css'

/*
 * Right-hand panel — UI shell only. It renders whatever it is told to via props
 * and owns no data of its own, so a future version can pass real backend events
 * straight through:
 *   - activeTool  'terminal' | 'browser' | null
 *   - content     { lines: string[] }         when activeTool === 'terminal'
 *                 { url: string, body: string } when activeTool === 'browser'
 *   - onClose       close the panel
 *   - onSelectTool  preview control: switch which mock view is shown
 */
function ToolPanel({ activeTool, content, onClose, onSelectTool }) {
  return (
    <aside className="toolpanel">
      <header className="toolpanel-header">
        <span className="toolpanel-title">
          {activeTool === 'terminal'
            ? 'Terminal'
            : activeTool === 'browser'
              ? 'Browser'
              : 'Tool panel'}
        </span>
        <span className="toolpanel-preview-tag">preview</span>
        <div className="toolpanel-switch">
          <button
            className={activeTool === 'terminal' ? 'active' : ''}
            onClick={() => onSelectTool('terminal')}
          >
            Terminal
          </button>
          <button
            className={activeTool === 'browser' ? 'active' : ''}
            onClick={() => onSelectTool('browser')}
          >
            Browser
          </button>
        </div>
        <button className="toolpanel-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <div className="toolpanel-body">
        {activeTool === 'terminal' && (
          <pre className="toolpanel-terminal">
            {(content?.lines || []).join('\n')}
          </pre>
        )}

        {activeTool === 'browser' && (
          <div className="toolpanel-browser">
            <div className="toolpanel-addressbar">{content?.url || ''}</div>
            <div className="toolpanel-browser-content">{content?.body || ''}</div>
          </div>
        )}

        {!activeTool && (
          <div className="toolpanel-idle">No tool is running.</div>
        )}
      </div>
    </aside>
  )
}

export default ToolPanel
