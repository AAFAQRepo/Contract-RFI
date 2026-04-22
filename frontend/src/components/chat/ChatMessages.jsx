import { Icon } from '../common/Icon'
import { formatAIText } from './MarkdownRenderer'
import ThinkingBlock from './ThinkingBlock'

/**
 * User chat message — right-aligned bubble with delete on hover.
 */
export function UserMessage({ id, text, onDelete }) {
  const realId = id && String(id).startsWith('q-') ? String(id).slice(2) : id
  return (
    <div className="msg-user">
      <div className="msg-user-bubble">
        {text}
        <button className="msg-bubble-delete" onClick={() => onDelete(realId)} title="Delete message">
          <Icon.Trash />
        </button>
      </div>
    </div>
  )
}

/**
 * AI chat message — left-aligned with thinking block, sources, and action buttons.
 */
export function AIMessage({ id, text, thinking, sources, onDelete }) {
  const realId = id && String(id).startsWith('a-') ? String(id).slice(2) : id

  return (
    <div className="msg-ai">
      <ThinkingBlock thinking={thinking} />
      <div className="msg-ai-body" dangerouslySetInnerHTML={{ __html: formatAIText(text) }} />
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
        <button className="msg-action-btn" title="Delete" onClick={() => onDelete(realId)}><Icon.Trash /></button>
      </div>
    </div>
  )
}
