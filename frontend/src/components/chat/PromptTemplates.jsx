import { Icon } from '../common/Icon'

const PROMPT_TEMPLATES = [
  { id: 'edit', label: 'Edit documents', icon: <Icon.Plus />, color: 'purple', prompt: 'I want to edit this contract. Help me review the terms and suggest improvements or redlines.' },
  { id: 'draft', label: 'Draft from precedent', icon: <Icon.Library />, color: 'green', prompt: 'Based on my past precedents, help me draft a new version of this agreement.' },
  { id: 'table', label: 'Review table', icon: <Icon.Columns />, color: 'blue', prompt: 'Create a summary table of the key terms, obligations, and deadlines found in this contract.' },
  { id: 'summarize', label: 'Summarize redlines', icon: <Icon.Collapse />, color: 'red', prompt: 'Summarize all the redlines and changes made to this document.' },
  { id: 'compare', label: 'Compare substantive differences', icon: <Icon.Copy />, color: 'orange', prompt: 'Compare these documents and identify the substantive legal differences between them.' },
]

export default function PromptTemplates({ onSelect, disabled, variant = 'classic' }) {
  if (variant === 'legal-assistant') {
    return (
      <div className="legal-assistant-chips">
        {PROMPT_TEMPLATES.map(t => (
          <button
            key={t.id}
            className={`legal-assistant-chip ${t.color}`}
            onClick={() => onSelect(t.prompt)}
            disabled={disabled}
          >
            <span className="legal-assistant-chip-icon">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="prompt-templates">
      {PROMPT_TEMPLATES.map(t => (
        <button
          key={t.id}
          className="prompt-template-btn"
          onClick={() => onSelect(t.prompt)}
          disabled={disabled}
          title={t.prompt}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export { PROMPT_TEMPLATES }

