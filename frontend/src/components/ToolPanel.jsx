import './ToolPanel.css'

const TOOLS = ['terminal', 'browser']
const TOOL_LABEL = { terminal: 'Terminal', browser: 'Browser' }

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
          {TOOL_LABEL[activeTool] || 'Tool panel'}
        </span>
        <span className="toolpanel-preview-tag">preview</span>
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
