import { useRef } from 'react'
import { Icon } from '../common/Icon'

/* Circular progress ring for the new modern design */
function ProcessingRing({ progress = 0 }) {
  const radius = 12
  const stroke = 2.5
  const normalizedRadius = radius - stroke
  const circumference = 2 * Math.PI * normalizedRadius
  const offset = circumference - (progress / 100) * circumference

  return (
    <svg
      className="file-progress-ring"
      width={radius * 2}
      height={radius * 2}
    >
      <circle
        stroke="rgba(255,255,255,0.3)"
        fill="transparent"
        strokeWidth={stroke}
        r={normalizedRadius}
        cx={radius}
        cy={radius}
      />
      <circle
        className="file-progress-arc"
        stroke="#ffffff"
        fill="transparent"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${circumference} ${circumference}`}
        style={{ strokeDashoffset: offset }}
        r={normalizedRadius}
        cx={radius}
        cy={radius}
      />
    </svg>
  )
}

function FileChip({ file, onRemove }) {
  const ext = (file.filename || file.name || '').split('.').pop()?.toLowerCase()
  const colors = { pdf: '#ef4444', docx: '#3b82f6', doc: '#3b82f6' }
  const bg = colors[ext] || '#6b7280'
  const label = ext?.toUpperCase().slice(0, 3) || 'DOC'
  const isProcessing = file.status === 'uploading' || file.status === 'processing'
  const progress = file.progress ?? 0

  return (
    <div className="file-chip-modern">
      <div className="file-chip-modern-icon" style={{ background: bg }}>
        {isProcessing ? (
          <ProcessingRing progress={progress} />
        ) : (
          <span>{label}</span>
        )}
      </div>
      <div className="file-chip-modern-info">
        <span className="file-chip-modern-name">{file.filename || file.name}</span>
        <span className="file-chip-modern-type">{label}</span>
      </div>
      <button className="file-chip-modern-close" onClick={onRemove}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
          <circle cx="12" cy="12" r="10" stroke="#e5e7eb" strokeWidth="1" />
          <path d="M15 9l-6 6M9 9l6 6" stroke="#111827" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
    </div>
  )
}

export default function ChatInput({
  input, setInput, onSend, onUploadClick,
  pendingFiles = [], onRemoveFile, sending,
  disabled = false,
  placeholder = "Ask Legal Assistant to edit, review, or summarize legal documents",
  idPrefix = "chat",
  variant = "classic" // or "legal-assistant"
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

  if (variant === 'legal-assistant') {
    return (
      <div className={`chat-input-box legal-assistant-style ${disabled ? 'disabled' : ''}`}>
        {pendingFiles.length > 0 && (
          <div className="file-chips-container" style={{ paddingBottom: 12 }}>
            {pendingFiles.map(f => (
              <FileChip key={f.id || f.name} file={f} onRemove={() => onRemoveFile(f)} />
            ))}
          </div>
        )}
        <textarea 
          ref={textareaRef} 
          className="legal-assistant-textarea" 
          placeholder={effectivePlaceholder}
          value={input} 
          onChange={handleInputChange} 
          onKeyDown={handleKeyDown}
          rows={1} 
          disabled={disabled} 
          id={`${idPrefix}-input`} 
        />
        <div className="legal-assistant-actions">
          <button className="legal-assistant-btn" onClick={onUploadClick} disabled={sending}>
            <Icon.Attach /> Add files
          </button>
          <button className="legal-assistant-btn" disabled={disabled}>
            <Icon.Library /> Library
          </button>
          <div style={{ flex: 1 }} />
          <button className="legal-assistant-btn prompts" disabled={disabled}>
            <Icon.Message /> Prompts
          </button>
          <button
            className={`legal-assistant-send ${(input.trim() || pendingFiles.length > 0) && !sending && !disabled ? 'active' : ''}`}
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

