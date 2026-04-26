import { useState, useEffect, useRef } from 'react'
import { Icon } from '../common/Icon'

/**
 * Premium collapsible thinking block inspired by Antigravity/Claude.
 * Shows thought duration and has a clean, minimal UI.
 */
export default function ThinkingBlock({ thinking, isComplete }) {
  const [open, setOpen] = useState(false)
  const [duration, setDuration] = useState(0)
  const timerRef = useRef(null)
  const startTimeRef = useRef(null)

  // Auto-open when thinking content arrives
  useEffect(() => {
    if (thinking && thinking.trim().length > 0) {
      setOpen(true)
    }
  }, [!!thinking])

  // Timer logic
  useEffect(() => {
    if (thinking && !isComplete && !startTimeRef.current) {
      startTimeRef.current = Date.now()
      timerRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000))
      }, 1000)
    }

    if (isComplete && timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
      
      // Auto-collapse after a short delay when complete
      setTimeout(() => {
        setOpen(false)
      }, 1000)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [thinking, isComplete])

  if (!thinking && !isComplete) return null
  if (!thinking && isComplete) return null // Should not happen but for safety

  const renderedThinking = thinking.split('\n').map((line, i) => {
    const t = line.trim()
    if (!t) return <div key={i} style={{ height: '8px' }} />
    return <p key={i}>{t}</p>
  })

  return (
    <div className={`premium-thinking-block ${isComplete ? 'complete' : 'active'}`}>
      <div className="premium-thinking-header" onClick={() => setOpen(v => !v)}>
        <div className="premium-thinking-label">
          {isComplete ? (
            <span className="thought-duration">Thought for {duration}s</span>
          ) : (
            <span className="thinking-status">
              <span className="thinking-spinner"></span>
              Thinking...
            </span>
          )}
        </div>
        <div className={`premium-thinking-chevron ${open ? 'open' : ''}`}>
          <Icon.ChevronDown />
        </div>
      </div>
      
      {open && (
        <div className="premium-thinking-content">
          {renderedThinking}
        </div>
      )}
    </div>
  )
}
