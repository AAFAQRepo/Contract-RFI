import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api, { getValidToken } from '../api/client'
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
  const { id } = useParams()
  const navigate = useNavigate()
  const {
    conversations, fetchConversations,
    activeConversationId, setActiveConversationId,
    conversationDocs, setConversationDocs, fetchConversationDocs,
    resetForNewChat,
  } = useProjects()
  const { refreshUsage } = useSubscription()

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  // pendingFiles: files uploaded in the current session before a conversation exists
  const [pendingFiles, setPendingFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [showFiles, setShowFiles] = useState(false)
  const [topbarVisible, setTopbarVisible] = useState(false)
  const messagesEndRef = useRef(null)
  const fileInputRef = useRef(null)

  // Scroll to bottom on new messages
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Sync URL ID to activeConversationId
  useEffect(() => {
    if (id && id !== activeConversationId) {
      localStorage.setItem('forceHistory', 'true')
      setActiveConversationId(id)
    } else if (!id && activeConversationId) {
      resetForNewChat()
    }
  }, [id, activeConversationId, setActiveConversationId, resetForNewChat])

  // Poll for processing status on pending files
  useEffect(() => {
    const hasProcessing = pendingFiles.some(f => f.status === 'processing' || f.status === 'uploading')
    if (!hasProcessing) return
    const interval = setInterval(async () => {
      for (const f of pendingFiles.filter(f => f.status === 'processing')) {
        try {
          const res = await api.get(`/documents/${f.id}/status`)
          if (res.data.status === 'ready') {
            setPendingFiles(p => p.map(x => x.id === f.id ? { ...x, status: 'ready', progress: 100 } : x))
            setConversationDocs(d => d.map(x => x.id === f.id ? { ...x, status: 'ready' } : x))
          } else if (res.data.status === 'error') {
            setPendingFiles(p => p.filter(x => x.id !== f.id))
          }
        } catch { /* silent */ }
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [pendingFiles, setConversationDocs])

  // Load chat history when active conversation changes
  useEffect(() => {
    setMessages([])
    setPendingFiles([])

    if (!activeConversationId) {
      setTopbarVisible(false)
      setShowFiles(false)
      return
    }
    // Entering an existing conversation: show topbar immediately
    setTopbarVisible(true)
    setShowFiles(true)
    if (!localStorage.getItem('forceHistory')) return

    api.get(`/chat/history?conversation_id=${activeConversationId}`)
      .then(r => {
        const flattened = []
        r.data.forEach(c => {
          if (c.query) flattened.push({ id: `q-${c.id}`, role: 'user', text: c.query })
          if (c.answer) flattened.push({ id: `a-${c.id}`, role: 'ai', text: c.answer, sources: c.sources })
        })
        setMessages(flattened)
      })
      .catch(err => console.error('Failed to load history', err))
  }, [activeConversationId])

  // Combined docs for the right panel: confirmed conv docs + current pending files
  const allVisibleDocs = [
    ...conversationDocs,
    ...pendingFiles.filter(pf => !conversationDocs.some(cd => cd.id === pf.id))
  ]

  // All ready document IDs to send in the chat query
  const readyDocumentIds = allVisibleDocs
    .filter(f => f.status === 'ready')
    .map(f => f.id)

  /* ── Send message ─────────────────────────────────────────── */
  const sendMessage = async (overrideInput) => {
    const text = (overrideInput || input).trim()
    if (!text || sending) return

    // Optimistically reveal the topbar + files panel on the very first message
    const isFirstMessage = !activeConversationId && messages.length === 0
    if (isFirstMessage) {
      setTopbarVisible(true)
      setShowFiles(true)
    }

    setInput('')
    setPendingFiles([])
    setMessages(m => [...m, { id: Date.now(), role: 'user', text }])
    setSending(true)

    try {
      const token = await getValidToken()
      const response = await fetch(`${api.defaults.baseURL}/chat/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          query: text,
          document_ids: readyDocumentIds,
          conversation_id: activeConversationId || null
        })
      })

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let aiMessageId = Date.now() + 1
      let partialLine = ''

      setMessages(m => [...m, { id: aiMessageId, role: 'ai', text: '', thinking: '', sources: [] }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = (partialLine + chunk).split('\n\n')
        partialLine = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue
          
          // Parse SSE format:
          // event: thinking\ndata: {"v": "token"}
          const eventMatch = line.match(/^event: (.+)\ndata: (.+)$/m)
          if (!eventMatch) continue

          const event = eventMatch[1]
          const dataStr = eventMatch[2]

          try {
            const data = JSON.parse(dataStr)
            
            setMessages(m => m.map(msg => {
              if (msg.id !== aiMessageId) return msg
              
              if (event === 'thinking') {
                return { ...msg, thinking: (msg.thinking || '') + (data.v || '') }
              } else if (event === 'thinking_end') {
                return { ...msg, thinkingComplete: true }
              } else if (event === 'token') {
                // If we get a token but thinking wasn't marked complete, do it now
                return { ...msg, text: (msg.text || '') + (data.v || ''), thinkingComplete: true }
              } else if (event === 'done') {
                return { ...msg, sources: data.sources || [], thinkingComplete: true }
              }
              return msg
            }))
          } catch (e) {
            console.warn('Failed to parse SSE data', e)
          }
        }
      }

      // After message complete, if it was a new chat, sync the URL
      if (!activeConversationId) {
        await fetchConversations()
        const r = await api.get('/chat/conversations')
        if (Array.isArray(r.data) && r.data.length > 0) {
          const newId = r.data[0].id
          navigate(`/chat/${newId}`, { replace: true })
        }
      }

      refreshUsage()

    } catch (err) {
      console.error('Streaming error:', err)
      setMessages(m => [...m, {
        id: Date.now() + 2,
        role: 'ai',
        text: `Sorry, I encountered an error. (${err.message})`
      }])
    } finally {
      setSending(false)
    }
  }

  /* ── Upload ───────────────────────────────────────────────── */
  const handleUpload = async (file) => {
    const tempId = `uploading-${Date.now()}`
    const tempFile = { id: tempId, filename: file.name, status: 'uploading', progress: 0 }
    setPendingFiles(p => [...p, tempFile])
    setUploading(true)

    const form = new FormData()
    form.append('file', file)
    // If a conversation already exists, scope the doc to it immediately
    if (activeConversationId) form.append('conversation_id', activeConversationId)

    try {
      const token = await getValidToken()
      const uploadResult = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${api.defaults.baseURL}/documents/upload`)
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 60)
            setPendingFiles(p => p.map(f => f.id === tempId ? { ...f, progress: pct } : f))
          }
        }
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
          else reject(new Error(`Upload failed: ${xhr.status}`))
        }
        xhr.onerror = () => reject(new Error('Network error'))
        xhr.send(form)
      })

      const newDoc = {
        id: uploadResult.document_id,
        filename: uploadResult.filename || file.name,
        status: 'processing',
        size_mb: uploadResult.size_mb,
        progress: 60,
        conversation_id: uploadResult.conversation_id || null,
      }
      setPendingFiles(p => p.map(f => f.id === tempId ? newDoc : f))

      // If scoped to an active conversation, also add to conversationDocs
      if (activeConversationId) {
        setConversationDocs(d => [newDoc, ...d])
      }

      // Polling for completion
      let currentPct = 60
      const processingInterval = setInterval(async () => {
        try {
          const res = await api.get(`/documents/${newDoc.id}/status`)
          if (res.data.progress_percent != null) {
            currentPct = Math.max(currentPct, Math.round(60 + (res.data.progress_percent / 100) * 39))
          } else if (currentPct < 99) {
            currentPct = Math.min(99, currentPct + Math.floor(Math.random() * 4) + 1)
          }
          setPendingFiles(p => p.map(f => f.id === newDoc.id ? { ...f, progress: currentPct } : f))

          if (res.data.status === 'ready') {
            clearInterval(processingInterval)
            setPendingFiles(p => p.map(f => f.id === newDoc.id ? { ...f, status: 'ready', progress: 100 } : f))
            if (activeConversationId) {
              setConversationDocs(d => d.map(f => f.id === newDoc.id ? { ...f, status: 'ready' } : f))
            }
          } else if (res.data.status === 'error') {
            clearInterval(processingInterval)
            setPendingFiles(p => p.filter(f => f.id !== newDoc.id))
          }
        } catch { /* silent */ }
      }, 2000)

    } catch (e) {
      console.error('Upload failed', e)
      setPendingFiles(p => p.filter(f => f.id !== tempId))
    } finally {
      setUploading(false)
    }
  }

  /* ── Delete ───────────────────────────────────────────────── */
  const handleDeleteMessage = async (mid) => {
    if (!window.confirm('Delete this message?')) return
    try {
      await api.delete(`/chat/${mid}`)
      setMessages(m => m.filter(msg => !msg.id.toString().endsWith(mid)))
    } catch { alert('Failed to delete message') }
  }

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`Delete "${doc.filename}"?`)) return
    try {
      await api.delete(`/documents/${doc.id}`)
      setPendingFiles(p => p.filter(f => f.id !== doc.id))
      setConversationDocs(d => d.filter(f => f.id !== doc.id))
    } catch { alert('Failed to delete document') }
  }

  const triggerFileUpload = () => fileInputRef.current?.click()

  const isProcessing = allVisibleDocs.some(f => f.status === 'processing' || f.status === 'uploading')
  const hasActiveChat = !!activeConversationId || messages.length > 0

  return (
    <>
      <input ref={fileInputRef} type="file" accept=".pdf,.docx,.doc" style={{ display: 'none' }}
        onChange={e => { const f = e.target.files[0]; if (f) handleUpload(f); e.target.value = '' }} />

      <div className="main-area">
        {/* Topbar — only visible once chat has started */}
        {topbarVisible && (
        <div className={`topbar topbar-slide-in`}>
          <div className="topbar-left">
            <span className="topbar-title">
              {activeConversationId
                ? (conversations.find(c => c.id === activeConversationId)?.title || 'Chat')
                : 'New Chat'}
            </span>
            <span className="topbar-chevron"><Icon.ChevronDown /></span>
          </div>
          <div className="topbar-right">
            <button className="topbar-btn" id="share-btn"><Icon.Share /> Share</button>
          </div>
        </div>
        )}

        {/* Chat Area */}
        <div className="chat-area">
          {!hasActiveChat ? (
            <div className="home-screen">
              <h1 className="home-greeting">{getGreeting()} {user?.name?.split(' ')[0] || 'there'}, let's get to work</h1>

              <div className="home-input-box">
                <ChatInput
                  input={input} setInput={setInput} onSend={() => sendMessage()}
                  onUploadClick={triggerFileUpload} pendingFiles={pendingFiles}
                  onRemoveFile={f => setPendingFiles(p => p.filter(x => x.id !== f.id))}
                  sending={sending} disabled={isProcessing} idPrefix="home"
                  variant="legal-assistant"
                />
              </div>

              <PromptTemplates onSelect={sendMessage} disabled={isProcessing || sending} variant="legal-assistant" />

              <div className="home-secondary-actions">
                <div className="secondary-action-link"><Icon.Workflows /> Explore workflows</div>
                <div className="secondary-action-link"><Icon.Help /> Try an example</div>
              </div>
            </div>
          ) : (
            <div className="messages-wrapper">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <div className="chat-empty-icon">💬</div>
                  <p>Ask anything about your uploaded documents</p>
                </div>
              )}
              {messages.map(msg =>
                msg.role === 'user'
                  ? <UserMessage key={msg.id} id={msg.id} text={msg.text} />
                  : <AIMessage key={msg.id} id={msg.id} text={msg.text} thinking={msg.thinking} sources={msg.sources} />
              )}
              {sending && (
                <div className="msg-ai">
                  <div className="premium-thinking-block active">
                    <div className="premium-thinking-header" style={{ cursor: 'default' }}>
                      <div className="premium-thinking-label">
                        <span className="thinking-status">
                          <span className="thinking-spinner"></span>
                          Thinking...
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input — always shown when chat is active */}
        {hasActiveChat && (
          <div className="chat-input-wrapper">
            <ChatInput
              input={input} setInput={setInput} onSend={() => sendMessage()}
              onUploadClick={triggerFileUpload} pendingFiles={pendingFiles}
              onRemoveFile={f => setPendingFiles(p => p.filter(x => x.id !== f.id))}
              sending={sending} disabled={isProcessing}
              idPrefix="chat"
              variant="legal-assistant"
            />
          </div>
        )}

        <div className="bottom-privacy">
          <Icon.Lock /> Your data is secure and private in Contract RFI
        </div>
      </div>

      {showFiles && (
        <FilesPanel
          files={allVisibleDocs}
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
