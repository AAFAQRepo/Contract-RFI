/**
 * Pre-built legal prompt templates for quick actions.
 */
const PROMPT_TEMPLATES = [
  { id: 'summarize', label: 'Summarize', prompt: 'Provide a concise executive summary of this contract, including key terms, obligations, and important provisions.' },
  { id: 'risks', label: 'Find Risks', prompt: 'Identify all risk factors, penalty clauses, liability provisions, and unfavorable terms in this contract.' },
  { id: 'compare', label: 'Compare', prompt: 'Compare the key terms, obligations, and conditions across the attached documents. Highlight differences.' },
  { id: 'dates', label: 'Key Dates', prompt: 'Extract all important dates, deadlines, renewal periods, and time-sensitive clauses from this contract.' },
  { id: 'parties', label: 'Parties', prompt: 'Identify all parties mentioned in this contract, their roles, rights, and obligations.' },
  { id: 'missing', label: 'Missing Clauses', prompt: 'Analyze this contract and identify any standard legal clauses that are missing or inadequately addressed.' },
]

export default function PromptTemplates({ onSelect, disabled }) {
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
