import { Icon } from '../common/Icon'

export function ProgressRing({ percent = 0, size = 16, stroke = 2 }) {
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

const STATUS_MAP = {
  uploading: ['Uploading', 'badge-uploading'],
  processing: ['Processing', 'badge-processing'],
  ready: ['Ready', 'badge-ready'],
  error: ['Error', 'badge-error']
}

export function StatusBadge({ status, step, progress }) {
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

export function DocIcon({ name = '' }) {
  const ext = name.split('.').pop()?.toLowerCase()
  const colors = { pdf: '#e53935', docx: '#1e88e5', doc: '#1e88e5' }
  const bg = colors[ext] || '#757575'
  const label = ext?.toUpperCase().slice(0, 3) || 'DOC'
  return <div className="file-card-icon" style={{ background: bg }}>{label}</div>
}

export function FilesPanel({ files, onUpload, onUploadClick, uploading, dragOver, setDragOver, onClose, onDelete }) {
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
            <button className="file-card-delete-btn" title="Delete document" onClick={() => onDelete(f)}>
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
          <div className="upload-drop-text">{uploading ? 'Uploading...' : 'Add files'}</div>
        </div>
      </div>
    </aside>
  )
}
