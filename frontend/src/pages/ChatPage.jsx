import { useState, useRef, useEffect, useCallback } from 'react'
import api from '../api/client'
import { Icon } from '../components/common/Icon'
import { useAuth } from '../contexts/AuthContext'
import { useProjects } from '../contexts/ProjectContext'
import ChatInput from '../components/chat/ChatInput'
import { UserMessage, AIMessage } from '../components/chat/ChatMessages'
import { FilesPanel } from '../components/documents/FilesPanel'
import PromptTemplates from '../components/chat/PromptTemplates'

/* ── Greeting helper ─────────────────────────────────────────── */
function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

export default function ChatPage() {
  const { user } = useAuth()
  const { 
    activeProject: project, setActiveProject: setProject, 
    projects, setProjects, 
    fetchProjects, fetchChatSessions 
  } = useProjects()

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [pendingFiles, setPendingFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [showFiles, setShowFiles] = useState(false)
  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)

  // Scroll to bottom on messages
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Global Polling for processing documents
  useEffect(() => {
    const hasProcessing = projects.some(f => f.status === 'processing' || f.status === 'uploading')
    if (!hasProcessing) return

    const interval = setInterval(fetchProjects, 3000)
    return () => clearInterval(interval)
  }, [projects, fetchProjects])

  // Load chat history when project changes
  useEffect(() => {
    setMessages([])
    
    const isGlobal = !project || String(project.id).startsWith('temp-')
    const docId = isGlobal ? 'global' : project.id

    if (isGlobal && !localStorage.getItem('forceHistory')) return

    api.get(`/chat/history?document_id=${docId}`)
      .then(r => {
        const flattened = []
        r.data.forEach(c => {
          if (c.query) flattened.push({ id: `q-${c.id}`, role: 'user', text: c.query })
          if (c.answer) flattened.push({ id: `a-${c.id}`, role: 'ai', text: c.answer, sources: c.sources })
        })
        setMessages(flattened)
      })
      .catch(err => console.error('Failed to load history', err))
  }, [project?.id])

  const sendMessage = async (overrideInput) => {
    const text = (overrideInput || input).trim()
    if ((!text && pendingFiles.length === 0) || sending) return
    
    const attachedFiles = [...pendingFiles]
    const currentDocId = project?.id && !String(project.id).startsWith('temp-') ? project.id : null

    setInput('')
    setPendingFiles([])
    setMessages(m => [...m, { id: Date.now(), role: 'user', text, files: attachedFiles }])
    setSending(true)

    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`${api.defaults.baseURL}/chat/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          query: text,
          document_id: currentDocId
        })
      })

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      
      let aiMessageId = Date.now() + 1
      let fullContent = ""
      
      setMessages(m => [...m, { id: aiMessageId, role: 'ai', text: '', thinking: '', sources: [] }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        fullContent += chunk

        let currentThinking = ""
        let currentAnswer = fullContent

        if (fullContent.includes('<thinking>')) {
          const parts = fullContent.split('<thinking>')
          if (fullContent.includes('</thinking>')) {
            const innerParts = parts[1].split('</thinking>')
            currentThinking = innerParts[0].trim()
            currentAnswer = innerParts[1].trim()
          } else {
            currentThinking = parts[1].trim()
            currentAnswer = "" 
          }
        }

        setMessages(m => m.map(msg => 
          msg.id === aiMessageId 
            ? { ...msg, text: currentAnswer, thinking: currentThinking }
            : msg
        ))
      }

      fetchChatSessions()

    } catch (err) {
      console.error('Streaming error:', err)
      setMessages(m => [...m, { 
        id: Date.now() + 2, 
        role: 'ai', 
        text: `Sorry, I encountered an error while connecting to the AI server. (${err.message})` 
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
      setProjects(p => [newDoc, ...p])
    } catch (e) {
      console.error('Upload failed', e)
      setPendingFiles(p => p.filter(f => f.id !== tempFile.id))
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteMessage = async (mid) => {
    if (!window.confirm("Delete this message?")) return
    try {
      await api.delete(`/chat/${mid}`)
      setMessages(m => m.filter(msg => !msg.id.toString().endsWith(mid)))
    } catch (e) {
      alert('Failed to delete message')
    }
  }

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`Delete "${doc.filename}"?`)) return
    try {
      await api.delete(`/documents/${doc.id}`)
      setProjects(p => p.filter(f => f.id !== doc.id))
      setPendingFiles(p => p.filter(f => f.id !== doc.id))
    } catch (e) {
      alert('Failed to delete document')
    }
  }

  const triggerFileUpload = () => fileInputRef.current?.click()
  
  const activeDoc = projects.find(f => f.id === project?.id)
  const isProcessing = activeDoc ? (activeDoc.status === 'processing' || activeDoc.status === 'uploading') : pendingFiles.length > 0
  const hasError = activeDoc?.status === 'error'

  const projectName = project?.filename || project?.name || 'General Chat'

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

        {/* Chat Area */}
        <div className="chat-area">
          {!project && messages.length === 0 ? (
            <div className="home-screen">
              <h1 className="home-greeting">{getGreeting()} {user?.name || 'there'}, let's get to work</h1>
              <div className="home-input-box">
                <ChatInput 
                  input={input} setInput={setInput} onSend={() => sendMessage()} 
                  onUploadClick={triggerFileUpload} pendingFiles={pendingFiles}
                  onRemoveFile={f => setPendingFiles(p => p.filter(x => x.id !== f.id))}
                  sending={sending} disabled={isProcessing} idPrefix="home"
                />
              </div>
              <div className="home-footer">
                <Icon.Lock /> Your data is secure and private
              </div>
            </div>
          ) : (
            <div className="messages-wrapper">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <div className="chat-empty-icon">📁</div>
                  <p>Discuss the files in this project</p>
                  <p style={{ fontSize: '0.78rem', color: '#bbb' }}>Upload a contract to get started</p>
                  {hasError && <div style={{ marginTop: 20, color: '#d63031' }}>Error processing document.</div>}
                </div>
              )}
              {messages.map(msg =>
                msg.role === 'user'
                  ? <UserMessage key={msg.id} id={msg.id} text={msg.text} onDelete={handleDeleteMessage} />
                  : <AIMessage key={msg.id} id={msg.id} text={msg.text} thinking={msg.thinking} sources={msg.sources} onDelete={handleDeleteMessage} />
              )}
              {sending && (
                <div className="msg-ai">
                  <div className="thinking-block" style={{ pointerEvents: 'none' }}>
                    <div className="thinking-toggle" style={{ cursor: 'default' }}>
                      <span className="thinking-dot-anim"></span>
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
          <PromptTemplates onSelect={sendMessage} disabled={isProcessing || sending} />
          <ChatInput 
            input={input} setInput={setInput} onSend={() => sendMessage()} 
            onUploadClick={triggerFileUpload} pendingFiles={pendingFiles}
            onRemoveFile={f => setPendingFiles(p => p.filter(x => x.id !== f.id))}
            sending={sending} disabled={isProcessing || hasError}
            idPrefix="chat"
          />
        </div>

        <div className="bottom-privacy">
          <Icon.Lock /> {hasError ? "Processing failed. Check file errors." : "Your data is secure and private"}
        </div>
      </div>

      {showFiles && (
        <FilesPanel
          files={projects} onUpload={handleUpload} onUploadClick={triggerFileUpload}
          uploading={uploading} dragOver={dragOver} setDragOver={setDragOver}
          onClose={() => setShowFiles(false)} onDelete={handleDeleteDocument}
        />
      )}
    </>
  )
}
