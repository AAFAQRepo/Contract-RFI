import { useRef } from 'react'
import { Icon } from '../common/Icon'

function FileChip({ file, onRemove }) {
  const ext = (file.filename || file.name || '').split('.').pop()?.toLowerCase()
  const colors = { pdf: '#e53935', docx: '#1e88e5', doc: '#1e88e5' }
  const bg = colors[ext] || '#757575'
  const label = ext?.toUpperCase().slice(0, 3) || 'DOC'
  return (
    <div className="file-chip">
      <div className="file-card-icon" style={{ background: bg, width: 24, height: 24, fontSize: '0.55rem' }}>{label}</div>
      <span>{file.filename || file.name}</span>
      <button className="file-chip-remove" onClick={onRemove}><Icon.Close /></button>
    </div>
  )
}

export default function ChatInput({
  input, setInput, onSend, onUploadClick,
  pendingFiles = [], onRemoveFile, sending,
  disabled = false,
  placeholder = "Ask about your contracts...",
  idPrefix = "chat"
}) {
  const textareaRef = useRef(null)
  const effectivePlaceholder = disabled ? "Waiting for documents to process..." : placeholder

  const handleInputChange = e => {
    if (disabled) return
    setInput(e.target.value)
    const ta = textareaRef.current
    if (ta) { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 160) + 'px' }
  }

  const handleKeyDown = e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!disabled) onSend() }
  }

  return (
    <div className={`chat-input-box ${disabled ? 'disabled' : ''}`}>
      {pendingFiles.length > 0 && (
        <div className="file-chips-container">
          {pendingFiles.map(f => (
            <FileChip key={f.id || f.name} file={f} onRemove={() => onRemoveFile(f)} />
          ))}
        </div>
      )}
      <textarea ref={textareaRef} className="chat-input-textarea" placeholder={effectivePlaceholder}
        value={input} onChange={handleInputChange} onKeyDown={handleKeyDown}
        rows={1} disabled={disabled} id={`${idPrefix}-input`} />
      <div className="chat-input-actions chat-input-actions--simple">
        <button className="input-action-btn" id={`${idPrefix}-add-files-btn`} onClick={onUploadClick} disabled={sending}>
          <Icon.Attach /> Add files
        </button>
        <div style={{ flex: 1 }} />
        <button
          className={`input-send-btn ${(input.trim() || pendingFiles.length > 0) && !sending && !disabled ? 'active' : ''}`}
          onClick={onSend}
          disabled={(!input.trim() && pendingFiles.length === 0) || sending || disabled}
          id={`${idPrefix}-send-btn`}
        >
          <Icon.Send />
        </button>
      </div>
    </div>
  )
}
