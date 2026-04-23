import { useState, useRef, useEffect, useCallback } from 'react'
import api from '../api/client'
import { Icon } from '../components/common/Icon'
import { useAuth } from '../contexts/AuthContext'
import { useProjects } from '../contexts/ProjectContext'
import { useSubscription } from '../contexts/SubscriptionContext'
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
    fetchProjects, conversations, fetchConversations,
    activeConversationId, setActiveConversationId
  } = useProjects()
  const { refreshUsage } = useSubscription()

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

  // Load chat history when project or conversation changes
  useEffect(() => {
    setMessages([])
    
    const isGlobal = (!project || String(project.id).startsWith('temp-')) && !activeConversationId
    const docId = project?.id && !String(project.id).startsWith('temp-') ? project.id : null

    if (isGlobal && !localStorage.getItem('forceHistory')) return

    const url = activeConversationId 
      ? `/chat/history?conversation_id=${activeConversationId}`
      : `/chat/history?document_id=${docId || 'global'}`

    api.get(url)
      .then(r => {
        const flattened = []
        r.data.forEach(c => {
          if (c.query) flattened.push({ id: `q-${c.id}`, role: 'user', text: c.query })
          if (c.answer) flattened.push({ id: `a-${c.id}`, role: 'ai', text: c.answer, sources: c.sources })
        })
        setMessages(flattened)
      })
      .catch(err => console.error('Failed to load history', err))
  }, [project?.id, activeConversationId])

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
          document_id: currentDocId,
          conversation_id: activeConversationId
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

      fetchConversations()
      refreshUsage()

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
    const tempId = `uploading-${Date.now()}`
    const tempFile = { id: tempId, filename: file.name, status: 'uploading', progress: 0 }
    setPendingFiles(p => [...p, tempFile])
    setUploading(true)

    const form = new FormData()
    form.append('file', file)

    try {
      // Use XMLHttpRequest so we get real upload progress
      const token = localStorage.getItem('token')
      const uploadResult = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${api.defaults.baseURL}/documents/upload`)
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            // Upload counts as first 60% of the overall progress
            const pct = Math.round((e.loaded / e.total) * 60)
            setPendingFiles(p => p.map(f => f.id === tempId ? { ...f, progress: pct } : f))
          }
        }

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText))
          } else {
            reject(new Error(`Upload failed: ${xhr.status}`))
          }
        }
        xhr.onerror = () => reject(new Error('Network error'))
        xhr.send(form)
      })

      const newDoc = {
        id: uploadResult.document_id,
        filename: uploadResult.filename || file.name,
        status: 'processing',
        size_mb: uploadResult.size_mb,
        progress: 60
      }
      setPendingFiles(p => p.map(f => f.id === tempId ? newDoc : f))
      setProjects(p => [newDoc, ...p])

      // Poll for real backend processing progress every 2 seconds
      let currentPct = 60
      const processingInterval = setInterval(async () => {
        try {
          const res = await api.get(`/documents/${newDoc.id}/status`)
          // Use real progress_percent if available, otherwise creep up
          if (res.data.progress_percent != null) {
            // Map backend 0–100 to frontend 60–99 range during processing
            const backendPct = res.data.progress_percent
            currentPct = Math.max(currentPct, Math.round(60 + (backendPct / 100) * 39))
          } else if (currentPct < 99) {
            currentPct = Math.min(99, currentPct + Math.floor(Math.random() * 4) + 1)
          }
          setPendingFiles(p => p.map(f =>
            f.id === newDoc.id ? { ...f, progress: currentPct } : f
          ))

          if (res.data.status === 'ready') {
            clearInterval(processingInterval)
            setPendingFiles(p => p.map(f =>
              f.id === newDoc.id ? { ...f, status: 'ready', progress: 100 } : f
            ))
            setProjects(p => p.map(f =>
              f.id === newDoc.id ? { ...f, status: 'ready' } : f
            ))
          } else if (res.data.status === 'error') {
            clearInterval(processingInterval)
            setPendingFiles(p => p.filter(f => f.id !== newDoc.id))
          }
        } catch (_) { /* silently continue polling */ }
      }, 2000)

    } catch (e) {
      console.error('Upload failed', e)
      setPendingFiles(p => p.filter(f => f.id !== tempId))
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
              <h1 className="home-greeting">{getGreeting()} {user?.name?.split(' ')[0] || 'there'}, let's get to work</h1>
              
              <div className="home-input-box">
                <ChatInput 
                  input={input} setInput={setInput} onSend={() => sendMessage()} 
                  onUploadClick={triggerFileUpload} pendingFiles={pendingFiles}
                  onRemoveFile={f => setPendingFiles(p => p.filter(x => x.id !== f.id))}
                  sending={sending} disabled={isProcessing} idPrefix="home"
                  variant="spellbook"
                />
              </div>

              <PromptTemplates onSelect={sendMessage} disabled={isProcessing || sending} variant="spellbook" />

              <div className="home-secondary-actions">
                <div className="secondary-action-link"><Icon.Workflows /> Explore workflows</div>
                <div className="secondary-action-link"><Icon.Help /> Try an example</div>
              </div>
            </div>
          ) : (
            <div className="messages-wrapper">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <div className="chat-empty-icon">📁</div>
                  <p>Discuss the files in this project</p>
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

        {/* Input area - only show if there's an active project or messages */}
        {(project || messages.length > 0) && (
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
        )}

        <div className="bottom-privacy">
          <Icon.Lock /> {hasError ? "Processing failed. Check file errors." : "Your data is secure and private in Contract RFI"}
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
