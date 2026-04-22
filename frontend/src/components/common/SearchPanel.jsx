import { useState } from 'react'
import { Icon } from '../common/Icon'
import { useProjects } from '../../contexts/ProjectContext'

export default function SearchPanel({ onClose }) {
  const [q, setQ] = useState('')
  const { projects, setActiveProject } = useProjects()
  
  const filtered = projects.filter(p => !q || (p.filename || p.name || '').toLowerCase().includes(q.toLowerCase()))

  const relTime = (iso) => {
    if (!iso) return ''
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000)
    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  const handleSelect = (p) => {
    setActiveProject(p)
    onClose()
  }

  return (
    <div className="search-panel">
      <div className="search-panel-top">
        <Icon.Search />
        <input
          className="search-panel-input"
          autoFocus
          placeholder="Search all projects..."
          value={q}
          onChange={e => setQ(e.target.value)}
          id="search-input"
        />
        <button className="search-panel-back" onClick={onClose}><Icon.ArrowBack /></button>
      </div>
      <div className="search-results-label">{filtered.length} project{filtered.length !== 1 ? 's' : ''}</div>
      {filtered.map(p => (
        <div key={p.id} className="search-result-item" onClick={() => handleSelect(p)}>
          <div className="search-result-title">{p.filename || p.name}</div>
          <div className="search-result-meta">{p.retrieval_chunks ? `${p.retrieval_chunks} chunks` : (p.status || 'ready')} · {relTime(p.created_at)}</div>
        </div>
      ))}
    </div>
  )
}
