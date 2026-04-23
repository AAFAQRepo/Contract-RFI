import { useRef } from 'react'
import { Icon } from '../common/Icon'

/* Circular progress ring around the file icon */
function ProcessingRing({ progress = 0 }) {
  const radius = 18
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
      {/* Background track */}
      <circle
        stroke="#e0e0e0"
        fill="transparent"
        strokeWidth={stroke}
        r={normalizedRadius}
        cx={radius}
        cy={radius}
      />
      {/* Progress arc */}
      <circle
        className="file-progress-arc"
        stroke="#4caf50"
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
  const colors = { pdf: '#e53935', docx: '#1e88e5', doc: '#1e88e5' }
  const bg = colors[ext] || '#757575'
  const label = ext?.toUpperCase().slice(0, 3) || 'DOC'
  const isProcessing = file.status === 'uploading' || file.status === 'processing'
  const progress = file.progress ?? 0

  return (
    <div className="file-chip">
      <div className="file-chip-icon-wrapper">
        <div className="file-card-icon" style={{ background: bg, width: 24, height: 24, fontSize: '0.55rem' }}>{label}</div>
        {isProcessing && (
          <>
            <ProcessingRing progress={progress} />
            <span className="file-chip-pct">{progress}%</span>
          </>
        )}
      </div>
      <span>{file.filename || file.name}</span>
      {!isProcessing && (
        <button className="file-chip-remove" onClick={onRemove}><Icon.Close /></button>
      )}
    </div>
  )
}

export default function ChatInput({
  input, setInput, onSend, onUploadClick,
  pendingFiles = [], onRemoveFile, sending,
  disabled = false,
  placeholder = "Ask Spellbook to edit, review, or summarize legal documents",
  idPrefix = "chat",
  variant = "classic" // or "spellbook"
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

  if (variant === 'spellbook') {
    return (
      <div className={`chat-input-box spellbook-style ${disabled ? 'disabled' : ''}`}>
        {pendingFiles.length > 0 && (
          <div className="file-chips-container" style={{ paddingBottom: 12 }}>
            {pendingFiles.map(f => (
              <FileChip key={f.id || f.name} file={f} onRemove={() => onRemoveFile(f)} />
            ))}
          </div>
        )}
        <textarea 
          ref={textareaRef} 
          className="spellbook-textarea" 
          placeholder={effectivePlaceholder}
          value={input} 
          onChange={handleInputChange} 
          onKeyDown={handleKeyDown}
          rows={1} 
          disabled={disabled} 
          id={`${idPrefix}-input`} 
        />
        <div className="spellbook-actions">
          <button className="spellbook-btn" onClick={onUploadClick} disabled={sending}>
            <Icon.Attach /> Add files
          </button>
          <button className="spellbook-btn" disabled={disabled}>
            <Icon.Library /> Library
          </button>
          <div style={{ flex: 1 }} />
          <button className="spellbook-btn prompts" disabled={disabled}>
            <Icon.Message /> Prompts
          </button>
          <button
            className={`spellbook-send ${(input.trim() || pendingFiles.length > 0) && !sending && !disabled ? 'active' : ''}`}
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

