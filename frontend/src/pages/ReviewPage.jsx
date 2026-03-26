import { useState } from 'react'

const Icon = {
  Table: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="9" x2="9" y2="21"/></svg>,
  Chat: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  Lock: () => <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>,
  Share: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>,
  Columns: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="18"/><rect x="14" y="3" width="7" height="18"/></svg>,
  ChevronDown: () => <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>,
}

export default function ReviewPage({ project }) {
  const [activeTab, setActiveTab] = useState('review')
  const projectName = project?.name || 'New Project'

  return (
    <>
      <div className="main-area">
        {/* Topbar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">{projectName}</span>
            <span className="topbar-chevron"><Icon.ChevronDown /></span>
          </div>
          <div className="topbar-right">
            <button className="topbar-btn"><Icon.Share /> Share</button>
            <button className="topbar-icon-btn"><Icon.Columns /></button>
          </div>
        </div>

        {/* Review Table Content */}
        <div className="review-table-wrap">
          <div className="review-empty">
            <div className="review-empty-icon">📊</div>
            <p style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
              Review table — Phase 1E
            </p>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 320, lineHeight: 1.6 }}>
              Once Phase 1E is complete, this table will show detected clauses,
              risk scoring, missing clause warnings, and party identification.
            </p>

            {/* Preview skeleton */}
            <div style={{ marginTop: 32, width: '100%', maxWidth: 520 }}>
              {['Penalty Clause', 'Termination', 'Force Majeure', 'Liability Cap', 'Dispute Resolution'].map((row, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 12, alignItems: 'center',
                  padding: '10px 16px',
                  borderRadius: 6,
                  background: i % 2 === 0 ? '#f8f8f8' : '#fff',
                  border: '1px solid var(--border)',
                  marginBottom: 4,
                  opacity: 0.5,
                }}>
                  <div style={{ flex: 1, height: 10, borderRadius: 4, background: '#e0e0e0' }} />
                  <span style={{
                    padding: '2px 8px', borderRadius: 10, fontSize: '0.7rem', fontWeight: 600,
                    background: i === 0 ? '#fce8e8' : i === 3 ? '#e6f4ea' : '#fff3cd',
                    color: i === 0 ? '#c62828' : i === 3 ? '#1e7e34' : '#856404',
                  }}>
                    {i === 0 ? 'HIGH' : i === 3 ? 'LOW' : 'MEDIUM'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom tabs */}
        <div className="bottom-tabs">
          <a href="/chat" className="bottom-tab" id="tab-chat-link">
            <Icon.Chat /> Chat
          </a>
          <button className={`bottom-tab ${activeTab === 'review' ? 'active' : ''}`} id="tab-review-btn"
            onClick={() => setActiveTab('review')}>
            <Icon.Table /> Review table
          </button>
          <div className="bottom-tab-privacy">
            <Icon.Lock /> Your data is secure and private
          </div>
        </div>
      </div>

      {/* Right panel (placeholder) */}
      <aside className="files-panel">
        <div className="files-panel-header">
          <span>0 Files</span>
        </div>
        <div className="files-panel-body">
          <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: 24 }}>
            No files for review yet
          </p>
        </div>
      </aside>
    </>
  )
}
