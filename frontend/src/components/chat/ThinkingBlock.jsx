import { useState, useEffect, useRef } from 'react'

/**
 * Collapsible thinking block for AI responses.
 * Auto-opens when thinking starts, auto-collapses when thinking finishes.
 */
export default function ThinkingBlock({ thinking, isDone }) {
  const [open, setOpen] = useState(false)
  const wasOpenedRef = useRef(false)

  useEffect(() => {
    if (thinking && thinking.trim().length > 0 && !wasOpenedRef.current) {
      setOpen(true)
      wasOpenedRef.current = true
    }
  }, [!!thinking])

  useEffect(() => {
    if (isDone && open) {
      // Small delay before collapsing so the user sees it finished
      const timer = setTimeout(() => {
        setOpen(false)
      }, 1000)
      return () => clearTimeout(timer)
    }
  }, [isDone])

  // Don't show anything if it's both empty AND done (e.g. legacy messages without thinking)
  if (!thinking && isDone) return null

  const renderedThinking = (thinking || '').split('\n').map((line, i) => {
    const t = line.trim()
    if (t.startsWith('-') || t.startsWith('*')) {
      return <li key={i} style={{ marginBottom: 4 }}>{t.substring(1).trim()}</li>
    }
    return <p key={i} style={{ marginBottom: 4 }}>{t}</p>
  })

  return (
    <div className={`thinking-block ${isDone ? 'is-done' : ''}`}>
      <button 
        className="thinking-toggle" 
        onClick={() => thinking && setOpen(v => !v)}
        style={{ cursor: thinking ? 'pointer' : 'default' }}
      >
        <span className={`thinking-dot-anim ${isDone ? 'stopped' : ''}`}></span>
        <span>{isDone ? 'Thought process' : (thinking ? 'Thinking' : 'Initializing…')}</span>
        {thinking && <span className={`thinking-chevron ${open ? 'open' : ''}`}></span>}
      </button>
      {open && thinking && (
        <div className="thinking-content">
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {renderedThinking}
          </ul>
        </div>
      )}
    </div>
  )
}
