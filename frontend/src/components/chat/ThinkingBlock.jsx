import { useState, useEffect } from 'react'
import { Icon } from '../common/Icon'

/**
 * Collapsible thinking block for AI responses.
 * Auto-opens when thinking content first arrives.
 */
export default function ThinkingBlock({ thinking }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (thinking && thinking.trim().length > 0) setOpen(true)
  }, [!!thinking])

  if (!thinking) return null

  const renderedThinking = thinking.split('\n').map((line, i) => {
    const t = line.trim()
    if (t.startsWith('-') || t.startsWith('*')) {
      return <li key={i} style={{ marginBottom: 4 }}>{t.substring(1).trim()}</li>
    }
    return <p key={i} style={{ marginBottom: 4 }}>{t}</p>
  })

  return (
    <div className="thinking-block">
      <button className="thinking-toggle" onClick={() => setOpen(v => !v)}>
        <span className="thinking-dot-anim"></span>
        <span>Thinking</span>
        <span className={`thinking-chevron ${open ? 'open' : ''}`}></span>
      </button>
      {open && (
        <div className="thinking-content">
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {renderedThinking}
          </ul>
        </div>
      )}
    </div>
  )
}
