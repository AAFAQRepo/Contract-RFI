import { useState, useRef, useEffect } from 'react'
import api from '../api/client'
import { Icon, Logo } from '../App'

/* ── File doc type icon ──────────────────────────────────────── */
function DocIcon({ name = '' }) {
  const ext = name.split('.').pop()?.toLowerCase()
  const colors = { pdf: '#e53935', docx: '#1e88e5', doc: '#1e88e5' }
  const bg = colors[ext] || '#757575'
  const label = ext?.toUpperCase().slice(0, 3) || 'DOC'
  return <div className="file-card-icon" style={{ background: bg }}>{label}</div>
}

/* ── Progress Ring ───────────────────────────────────────────── */
function ProgressRing({ percent = 0, size = 16, stroke = 2 }) {
  const radius = (size - stroke) / 2
  const circ = 2 * Math.PI * radius
  const offset = circ - (percent / 100) * circ
  return (
    <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
      <circle cx={size/2} cy={size/2} r={radius} fill="transparent" stroke="rgba(255,255,255,0.2)" strokeWidth={stroke} />
      <circle cx={size/2} cy={size/2} r={radius} fill="transparent" stroke="currentColor" strokeWidth={stroke} strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round" style={{ transition: 'stroke-dashoffset 0.3s ease' }} />
    </svg>
  )
}

/* ── Status Badge ──────────────────────────────────────────── */
const STATUS_MAP = { 
  uploading: ['Uploading', 'badge-uploading'], 
  processing: ['Processing', 'badge-processing'], 
  ready: ['Ready', 'badge-ready'], 
  error: ['Error', 'badge-error'] 
}
function StatusBadge({ status, step, progress }) {
  const [label, cls] = STATUS_MAP[status] || [status, '']
  
  if (status === 'processing') {
    return (
      <span className={`badge ${cls}`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ProgressRing percent={progress || 0} />
        <span>{step || label} {progress ? `${progress}%` : ''}</span>
      </span>
    )
  }
  
  return <span className={`badge ${cls}`}>{label}</span>
}

/* ── File Chip (Inside Input) ─────────────────────────────────── */
function FileChip({ file, onRemove }) {
  return (
    <div className="file-chip">
      <DocIcon name={file.filename || file.name} />
      <span>{file.filename || file.name}</span>
      <button className="file-chip-remove" onClick={onRemove}>
        <Icon.Close />
      </button>
    </div>
  )
}

/* ── Right Files Panel ───────────────────────────────────────── */
function FilesPanel({ files, onUpload, onUploadClick, uploading, dragOver, setDragOver, onClose, onDelete }) {
  return (
    <aside className="files-panel">
      <div className="files-panel-header">
        <span>{files.length} File{files.length !== 1 ? 's' : ''}</span>
        <button className="topbar-icon-btn" title="Close panel" onClick={onClose} style={{ border: 'none', width: 24, height: 24 }}>
          <Icon.Columns />
        </button>
      </div>
      <div className="files-panel-body">
        {files.map(f => (
          <div key={f.id} className="file-card" id={`file-card-${f.id}`}>
            <DocIcon name={f.filename} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="file-card-name">{f.filename}</div>
              <div style={{ marginTop: 4 }}><StatusBadge status={f.status} step={f.processing_step} progress={f.progress_percent} /></div>
            </div>
            <button
              className="file-card-delete-btn"
              title="Delete document"
              onClick={() => onDelete(f)}
            >
              <Icon.Close />
            </button>
          </div>
        ))}
        <div
          className={`upload-drop-area ${dragOver ? 'drag-over' : ''}`}
          style={{ marginTop: files.length ? 12 : 0 }}
          onClick={onUploadClick}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={e => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files[0]; if (f) onUpload(f) }}
        >
          <Icon.Attach />
          <div className="upload-drop-text">{uploading ? 'Uploading…' : 'Add files'}</div>
        </div>
      </div>
    </aside>
  )
}

/* ── Markdown / Table Renderer ───────────────────────────────── */
function formatAIText(text) {
  if (!text) return ''

  // Replace code blocks
  text = text.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
    `<pre class="ai-code-block"><code>${code.replace(/</g, '&lt;').replace(/>/g, '&gt;').trim()}</code></pre>`
  )

  // Parse markdown tables
  text = text.replace(/((?:\|.+\|\n?){3,})/g, (tableBlock) => {
    const lines = tableBlock.trim().split('\n').filter(l => l.trim())
    const isTable = lines.length >= 2 && lines.every(l => l.trim().startsWith('|'))
    if (!isTable) return tableBlock

    const parseRow = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    const headers = parseRow(lines[0])
    const isAlignRow = (l) => /^\|[\s\-:|\s]+\|$/.test(l.trim())
    const bodyLines = lines.slice(1).filter(l => !isAlignRow(l))

    const head = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`
    const body = `<tbody>${bodyLines.map(l => `<tr>${parseRow(l).map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`
    return `<div class="ai-table-wrapper"><table class="ai-table">${head}${body}</table></div>`
  })

  // Headings
  text = text.replace(/^### (.+)$/gm, '<h3 class="ai-h3">$1</h3>')
  text = text.replace(/^## (.+)$/gm, '<h2 class="ai-h2">$1</h2>')
  text = text.replace(/^# (.+)$/gm, '<h1 class="ai-h1">$1</h1>')

  // Bold, italic
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Lists (gather consecutive - lines into a <ul>)
  text = text.replace(/((?:^[-•] .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^[-•] /, '')}</li>`)
    return `<ul class="ai-list">${items.join('')}</ul>`
  })

  // Numbered lists
  text = text.replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`)
    return `<ol class="ai-list">${items.join('')}</ol>`
  })

  // Horizontal rules
  text = text.replace(/^[=\-]{3,}$/gm, '<hr class="ai-hr">')

  // Paragraphs (remaining lines)
  const lines = text.split('\n')
  const out = []
  for (const line of lines) {
    const t = line.trim()
    if (!t) continue
    if (/^<(h[1-3]|ul|ol|pre|div|hr|table)/.test(t)) {
      out.push(t)
    } else {
      out.push(`<p>${t}</p>`)
    }
  }
  return out.join('\n')
}

/* ── Collapsible Thinking block ──────────────────────────────── */
function ThinkingBlock({ thinking }) {
  const [open, setOpen] = useState(false)
  if (!thinking) return null
  return (
    <div className="thinking-block">
      <button className="thinking-toggle" onClick={() => setOpen(v => !v)}>
        <span className="thinking-dot-anim">●</span>
        <span>Thinking</span>
        <span className={`thinking-chevron ${open ? 'open' : ''}`}>▾</span>
      </button>
      {open && (
        <div className="thinking-content">
          {thinking}
        </div>
      )}
    </div>
  )
}

/* ── Chat messages ───────────────────────────────────────────── */
function UserMessage({ text }) {
  return <div className="msg-user"><div className="msg-user-bubble">{text}</div></div>
}

function AIMessage({ text, thinking, sources }) {
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
      </div>
    </div>
  )
}

/* ── Greeting helper ─────────────────────────────────────────── */
function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

/* ── Simplified Input Bar: only Add Files + Send ─────────────── */
function ChatInput({ 
  input, setInput, onSend, onUploadClick, 
  pendingFiles, onRemoveFile, sending, 
  disabled=false,
  placeholder="Ask Spellbook to edit, review, or summarize legal documents",
  idPrefix="home"
}) {
  const textareaRef = useRef(null)

  const effectivePlaceholder = disabled 
    ? "Waiting for documents to process..." 
    : placeholder

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
      <textarea
        ref={textareaRef}
        className="chat-input-textarea"
        placeholder={effectivePlaceholder}
        value={input}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        rows={1}
        disabled={disabled}
        id={`${idPrefix}-input`}
      />
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

/* ── Home Screen component ───────────────────────────────────── */
function HomeScreen({ input, setInput, onSend, onUploadClick, pendingFiles, onRemoveFile, sending, disabled }) {
  return (
    <div className="main-area">
      <div className="home-screen">
        <h1 className="home-greeting">{getGreeting()} Danish Ali, let's get to work</h1>

        <div className="home-input-box">
          <ChatInput 
            input={input} 
            setInput={setInput} 
            onSend={onSend} 
            onUploadClick={onUploadClick}
            pendingFiles={pendingFiles}
            onRemoveFile={onRemoveFile}
            sending={sending}
            disabled={disabled}
            idPrefix="home"
          />
        </div>

        <div className="home-footer">
          <Icon.Lock /> Your data is secure and private
        </div>
      </div>
    </div>
  )
}

/* ── Main ChatPage ───────────────────────────────────────────── */
export default function ChatPage({ project, setProject, projects, setProjects }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [files, setFiles] = useState([])
  const [pendingFiles, setPendingFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [showFiles, setShowFiles] = useState(false)   // ← closed by default
  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)

  // Load documents from API
  useEffect(() => {
    api.get('/documents/').then(r => {
      const docs = r.data.documents || []
      setFiles(docs)
      setProjects(docs)
    }).catch(() => {})
  }, [])

  // Scroll to bottom on messages
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const sendMessage = async () => {
    if ((!input.trim() && pendingFiles.length === 0) || sending) return
    const text = input.trim()
    const attachedFiles = [...pendingFiles]
    const currentDocId = project?.id && !project.id.startsWith('temp-') ? project.id : null

    setInput('')
    setPendingFiles([])
    setMessages(m => [...m, { id: Date.now(), role: 'user', text, files: attachedFiles }])
    setSending(true)

    // If we're on home screen, switch to chat with a temporary project
    if (!project) {
      setProject({ 
        id: `temp-${Date.now()}`, 
        name: text.slice(0, 40) || (attachedFiles[0]?.filename || attachedFiles[0]?.name) || 'New Chat', 
        files: attachedFiles.length 
      })
    }

    try {
      const response = await api.post('/chat/message', {
        query: text,
        document_id: currentDocId
      })

      const { answer, thinking, sources } = response.data

      setMessages(m => [...m, {
        id: Date.now() + 1,
        role: 'ai',
        text: answer,
        thinking: thinking,
        sources: sources
      }])
    } catch (err) {
      console.error('Chat failed', err)
      setMessages(m => [...m, {
        id: Date.now() + 1,
        role: 'ai',
        text: 'Sorry, I encountered an error while connecting to the AI server. Please ensure the GPU server is reachable.',
      }])
    } finally {
      setSending(false)
    }
  }

  const handleUpload = async (file) => {
    const tempFile = { id: `uploading-${Date.now()}`, filename: file.name, status: 'uploading' }
    setPendingFiles(p => [...p, tempFile])
    
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const r = await api.post('/documents/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      const newDoc = { id: r.data.document_id, filename: r.data.filename || file.name, status: 'processing', size_mb: r.data.size_mb }
      
      setPendingFiles(p => p.map(f => f.id === tempFile.id ? newDoc : f))
      setFiles(p => [newDoc, ...p])
      setProjects(p => [newDoc, ...p])

      const iv = setInterval(async () => {
        try {
          const s = await api.get(`/documents/${newDoc.id}/status`)
          const updated = { ...newDoc, ...s.data }
          setPendingFiles(p => p.map(f => f.id === newDoc.id ? updated : f))
          setFiles(p => p.map(d => d.id === newDoc.id ? updated : d))
          setProjects(p => p.map(d => d.id === newDoc.id ? updated : d))
          if (s.data.status === 'ready' || s.data.status === 'error') clearInterval(iv)
        } catch { clearInterval(iv) }
      }, 3000)
    } catch (e) {
      console.error('Upload failed', e)
      setPendingFiles(p => p.filter(f => f.id !== tempFile.id))
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return
    try {
      await api.delete(`/documents/${doc.id}`)
      setFiles(p => p.filter(f => f.id !== doc.id))
      setProjects(p => p.filter(f => f.id !== doc.id))
      setPendingFiles(p => p.filter(f => f.id !== doc.id))
    } catch (e) {
      alert('Failed to delete document: ' + (e.response?.data?.detail || e.message))
    }
  }

  const removePendingFile = (file) => {
    setPendingFiles(p => p.filter(f => (f.id || f.name) !== (file.id || file.name)))
  }

  const triggerFileUpload = () => fileInputRef.current?.click()
  
  const isProcessing = files.some(f => f.status === 'processing' || f.status === 'uploading')

  // ── Home screen (project=null) ──
  if (!project) {
    return (
      <>
        <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc" style={{ display: 'none' }}
          onChange={e => { const f = e.target.files[0]; if (f) handleUpload(f); e.target.value = '' }} />
        <HomeScreen
          input={input}
          setInput={setInput}
          onSend={sendMessage}
          onUploadClick={triggerFileUpload}
          pendingFiles={pendingFiles}
          onRemoveFile={removePendingFile}
          sending={sending}
          disabled={isProcessing}
        />
        {showFiles && (
          <FilesPanel
            files={files}
            onUpload={handleUpload}
            onUploadClick={triggerFileUpload}
            uploading={uploading}
            dragOver={dragOver}
            setDragOver={setDragOver}
            onClose={() => setShowFiles(false)}
            onDelete={handleDeleteDocument}
          />
        )}
      </>
    )
  }

  // ── Chat screen ──
  const projectName = project?.filename || project?.name || 'New Chat'

  return (
    <>
      <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc" style={{ display: 'none' }}
        onChange={e => { const f = e.target.files[0]; if (f) handleUpload(f); e.target.value = '' }} />
      <div className="main-area">
        {/* Topbar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">{projectName}</span>
            <span className="topbar-chevron"><Icon.ChevronDown /></span>
          </div>
          <div className="topbar-right">
            <button className="topbar-btn" id="share-btn"><Icon.Share /> Share</button>
            <button className="topbar-icon-btn" id="toggle-files-btn" onClick={() => setShowFiles(v => !v)}>
              <Icon.Columns />
            </button>
          </div>
        </div>

        {/* Chat messages */}
        <div className="chat-area">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <div className="chat-empty-icon">💬</div>
              <p>Discuss the files in this project</p>
              <p style={{ fontSize: '0.78rem', color: '#bbb' }}>Upload a contract to get started</p>
            </div>
          ) : (
            <div className="messages-wrapper">
              {messages.map(msg =>
                msg.role === 'user'
                  ? <UserMessage key={msg.id} text={msg.text} />
                  : <AIMessage key={msg.id} text={msg.text} thinking={msg.thinking} sources={msg.sources} />
              )}
              {sending && (
                <div className="msg-ai">
                  <div className="thinking-block" style={{ pointerEvents: 'none' }}>
                    <div className="thinking-toggle" style={{ cursor: 'default' }}>
                      <span className="thinking-dot-anim">●</span>
                      <span>Thinking…</span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="chat-input-wrapper">
          <ChatInput 
            input={input} 
            setInput={setInput} 
            onSend={sendMessage} 
            onUploadClick={triggerFileUpload}
            pendingFiles={pendingFiles}
            onRemoveFile={removePendingFile}
            sending={sending}
            disabled={isProcessing}
            idPrefix="chat"
          />
        </div>

        <div className="bottom-privacy">
          <Icon.Lock /> Your data is secure and private
        </div>
      </div>

      {showFiles && (
        <FilesPanel
          files={files}
          onUpload={handleUpload}
          onUploadClick={triggerFileUpload}
          uploading={uploading}
          dragOver={dragOver}
          setDragOver={setDragOver}
          onClose={() => setShowFiles(false)}
          onDelete={handleDeleteDocument}
        />
      )}
    </>
  )
}
