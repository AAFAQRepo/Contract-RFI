import { Icon } from '../common/Icon'
import { formatAIText } from './MarkdownRenderer'
import ThinkingBlock from './ThinkingBlock'
import Typewriter from './Typewriter'

/**
 * User chat message — right-aligned bubble.
 */
export function UserMessage({ id, text }) {
  return (
    <div className="msg-user">
      <div className="msg-user-bubble">
        {text}
      </div>
    </div>
  )
}

/**
 * AI chat message — left-aligned with thinking block, sources, and action buttons.
 */
export function AIMessage({ id, text, thinking, isThinkingDone, sources, isStreaming }) {
  return (
    <div className="msg-ai">
      <ThinkingBlock thinking={thinking} isDone={isThinkingDone} />
      
      <div className="msg-ai-body">
        {isStreaming ? (
          <Typewriter text={text} speed={10} isStreaming={true} />
        ) : (
          <div dangerouslySetInnerHTML={{ __html: formatAIText(text) }} />
        )}
      </div>

      {sources && sources.length > 0 && (
        <div className="msg-sources">
          {sources.map((s, i) => (
            <span key={i} className="source-chip">Page {s.page}</span>
          ))}
        </div>
      )}
      <div className="msg-ai-actions">
        <button className="msg-action-btn" title="Helpful"><Icon.ThumbUp /></button>
        <button className="msg-action-btn" title="Not helpful"><Icon.ThumbDown /></button>
        <button className="msg-action-btn" title="Copy" onClick={() => navigator.clipboard.writeText(text)}><Icon.Copy /></button>
      </div>
    </div>
  )
}
