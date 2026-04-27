import { useState, useEffect, useRef } from 'react'
import { formatAIText } from './MarkdownRenderer'

/**
 * A smooth typewriter effect component.
 * It catches up to the target text character by character.
 */
export default function Typewriter({ text, speed = 10, onComplete, isStreaming = false }) {
  const [displayedText, setDisplayedText] = useState('')
  const indexRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => {
    // If the incoming text is shorter than what we've displayed (e.g. state reset), reset
    if (text.length < indexRef.current) {
      setDisplayedText('')
      indexRef.current = 0
    }

    const type = () => {
      if (indexRef.current < text.length) {
        // Grab the next character(s). 
        // If we are lagging far behind (e.g. large chunk arrived), move faster.
        const lag = text.length - indexRef.current
        const jump = lag > 100 ? 10 : (lag > 20 ? 3 : 1)
        
        indexRef.current += jump
        setDisplayedText(text.substring(0, indexRef.current))
        
        timerRef.current = setTimeout(type, speed)
      } else {
        if (!isStreaming && onComplete) onComplete()
        timerRef.current = null
      }
    }

    if (!timerRef.current && indexRef.current < text.length) {
      timerRef.current = setTimeout(type, speed)
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [text, speed, isStreaming])

  return <div dangerouslySetInnerHTML={{ __html: formatAIText(displayedText) }} />
}
