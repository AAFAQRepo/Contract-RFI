import { useState, useEffect, useRef } from 'react'
import api from '../api/client'

const STATUS_LABELS = {
  uploading: { label: 'Uploading...', color: '#6c5ce7' },
  processing: { label: 'Processing...', color: '#fdcb6e' },
  ready: { label: 'Ready', color: '#00b894' },
  error: { label: 'Error', color: '#d63031' },
}

function StatusBadge({ status }) {
  const s = STATUS_LABELS[status] || { label: status, color: '#636e72' }
  return (
    <span style={{
      padding: '3px 10px',
      borderRadius: '12px',
      fontSize: '0.78rem',
      fontWeight: 600,
      background: s.color + '22',
      color: s.color,
    }}>
      {s.label}
    </span>
  )
}

function DocumentRow({ doc, onSelect, selected }) {
  return (
    <div
      id={`doc-row-${doc.id}`}
      onClick={() => onSelect(doc)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '14px 18px',
        borderRadius: '10px',
        marginBottom: '8px',
        background: selected ? 'rgba(108,92,231,0.1)' : 'var(--bg-card)',
        border: `1px solid ${selected ? '#6c5ce7' : 'var(--border)'}`,
        cursor: 'pointer',
        transition: 'all 0.2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <span style={{ fontSize: '1.4rem' }}>📄</span>
        <div>
          <div style={{ fontWeight: 500, fontSize: '0.9rem' }}>{doc.filename}</div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
            {doc.size_mb} MB
            {doc.page_count ? ` · ${doc.page_count} pages` : ''}
            {doc.language ? ` · ${doc.language.toUpperCase()}` : ''}
          </div>
        </div>
      </div>
      <StatusBadge status={doc.status} />
    </div>
  )
}

function UploadPage() {
  const [documents, setDocuments] = useState([])
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState(null)
  const fileInputRef = useRef(null)
  const pollingRef = useRef({})

  // Load documents on mount
  useEffect(() => {
    fetchDocuments()
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      Object.values(pollingRef.current).forEach(clearInterval)
    }
  }, [])

  const fetchDocuments = async () => {
    try {
      const res = await api.get('/documents/')
      setDocuments(res.data.documents)
      // Start polling for any in-progress docs
      res.data.documents.forEach(doc => {
        if (doc.status === 'processing') startPolling(doc.id)
      })
    } catch (e) {
      console.error('Failed to load documents', e)
    }
  }

  const startPolling = (docId) => {
    if (pollingRef.current[docId]) return
    pollingRef.current[docId] = setInterval(async () => {
      try {
        const res = await api.get(`/documents/${docId}/status`)
        const { status } = res.data
        setDocuments(prev =>
          prev.map(d => d.id === docId ? { ...d, ...res.data } : d)
        )
        if (status === 'ready' || status === 'error') {
          clearInterval(pollingRef.current[docId])
          delete pollingRef.current[docId]
        }
      } catch (e) {
        clearInterval(pollingRef.current[docId])
        delete pollingRef.current[docId]
      }
    }, 3000)
  }

  const handleUpload = async (file) => {
    if (!file) return
    setError(null)
    setUploading(true)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await api.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const newDoc = {
        id: res.data.document_id,
        filename: res.data.filename || file.name,
        status: 'processing',
        size_mb: res.data.size_mb,
        language: null,
        page_count: null,
      }
      setDocuments(prev => [newDoc, ...prev])
      startPolling(newDoc.id)
    } catch (e) {
      const msg = e.response?.data?.detail || 'Upload failed. Please try again.'
      setError(msg)
    } finally {
      setUploading(false)
    }
  }

  const handleFileInput = (e) => {
    const file = e.target.files[0]
    if (file) handleUpload(file)
    e.target.value = ''
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  return (
    <div className="page">
      <h2 className="page-title">Upload Contract</h2>
      <p className="page-subtitle">
        Upload a PDF or DOCX contract for AI-powered analysis and chat
      </p>

      {/* Upload Zone */}
      <div
        id="upload-dropzone"
        className="upload-zone"
        style={{ borderColor: dragOver ? 'var(--accent)' : undefined }}
        onClick={() => !uploading && fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          id="file-input"
          type="file"
          accept=".pdf,.docx,.doc"
          style={{ display: 'none' }}
          onChange={handleFileInput}
        />
        <div className="upload-icon">{uploading ? '⏳' : '📁'}</div>
        <p className="upload-text">
          {uploading
            ? 'Uploading...'
            : 'Drop your contract here or click to browse'}
        </p>
        <p className="upload-hint">PDF, DOCX · up to 50 MB · Arabic, Hindi, English</p>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          marginTop: '12px',
          padding: '12px 16px',
          borderRadius: '8px',
          background: 'rgba(214,48,49,0.1)',
          color: '#d63031',
          fontSize: '0.9rem',
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* Documents List */}
      <div style={{ marginTop: '32px' }}>
        <h3 style={{ marginBottom: '16px', fontSize: '1rem', color: 'var(--text-secondary)' }}>
          Your Documents ({documents.length})
        </h3>

        {documents.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <p className="empty-state-text">No documents uploaded yet</p>
          </div>
        ) : (
          documents.map(doc => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              selected={selectedDoc?.id === doc.id}
              onSelect={setSelectedDoc}
            />
          ))
        )}
      </div>
    </div>
  )
}

export default UploadPage
