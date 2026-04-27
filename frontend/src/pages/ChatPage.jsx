import { useState, useRef, useEffect } from 'react'
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
  const justCreatedConvRef = useRef(false)

  // Scroll to bottom on new messages
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

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
    if (!activeConversationId) {
      setMessages([])
      setPendingFiles([])
      setTopbarVisible(false)
      setShowFiles(false)
      return
    }

    // NEW: If we just created this conversation, don't reload history
    // We already have the streaming message in state.
    if (justCreatedConvRef.current) {
      justCreatedConvRef.current = false
      return
    }

    // Entering an existing conversation: show topbar immediately
    setMessages([])
    setPendingFiles([])
    setTopbarVisible(true)
    setShowFiles(true)
    if (!localStorage.getItem('forceHistory')) return

    api.get(`/chat/history?conversation_id=${activeConversationId}`)
      .then(r => {
        const flattened = []
        r.data.forEach(c => {
          if (c.query) flattened.push({ id: `q-${c.id}`, role: 'user', text: c.query })
          if (c.answer) flattened.push({ 
            id: `a-${c.id}`, 
            role: 'ai', 
            text: c.answer, 
            thinking: c.thinking || '', 
            isThinkingDone: true,
            sources: c.sources 
          })
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
      let fullContent = ''

      setMessages(m => [...m, { 
        id: aiMessageId, 
        role: 'ai', 
        text: '', 
        thinking: '', 
        sources: [], 
        isStreaming: true,
        isThinkingDone: false 
      }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        fullContent += chunk

        let currentThinking = ''
        let currentAnswer = fullContent
        let isThinkingDone = false

        if (fullContent.includes('<thinking>')) {
          const parts = fullContent.split('<thinking>')
          if (fullContent.includes('</thinking>')) {
            const innerParts = parts[1].split('</thinking>')
            currentThinking = innerParts[0].trim()
            currentAnswer = innerParts[1].trim()
            isThinkingDone = true
          } else {
            currentThinking = parts[1].trim()
            currentAnswer = ''
          }
        }

        setMessages(m => m.map(msg =>
          msg.id === aiMessageId
            ? { ...msg, text: currentAnswer, thinking: currentThinking, isThinkingDone }
            : msg
        ))
      }

      // Mark streaming as finished
      setMessages(m => m.map(msg =>
        msg.id === aiMessageId ? { ...msg, isStreaming: false } : msg
      ))

      // After the first message, refresh conversations to show the new one in sidebar
      // and fetch its scoped documents (the backend links them during this call)
      await fetchConversations()
      
      // If this was a new conversation, the backend just created it.
      // We need to figure out the new conversation ID.
      // Re-fetch conversations and set the latest one as active.
      if (!activeConversationId) {
        const r = await api.get('/chat/conversations')
        if (Array.isArray(r.data) && r.data.length > 0) {
          const newConvId = r.data[0].id
          localStorage.setItem('forceHistory', 'true')
          justCreatedConvRef.current = true
          setActiveConversationId(newConvId)
          // Fetch and merge conversation docs to reflect the newly linked files
          await fetchConversationDocs(newConvId)
          // Clear pending files (they are now officially in the conversation)
          setPendingFiles([])
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
                  : <AIMessage 
                      key={msg.id} 
                      id={msg.id} 
                      text={msg.text} 
                      thinking={msg.thinking} 
                      isThinkingDone={msg.isThinkingDone} 
                      sources={msg.sources} 
                      isStreaming={msg.isStreaming} 
                    />
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
