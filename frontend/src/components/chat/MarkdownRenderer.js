import DOMPurify from 'dompurify'

/**
 * Convert AI markdown text to sanitized HTML.
 * Handles: code blocks, tables, headings, bold, italic, lists, horizontal rules.
 * All output is sanitized via DOMPurify to prevent XSS.
 */
export function formatAIText(text) {
  if (!text) return ''

  // Replace code blocks
  text = text.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
    `<pre class="ai-code-block"><code>${code.replace(/</g, '&lt;').replace(/>/g, '&gt;').trim()}</code></pre>`
  )

  // Parse markdown tables
  text = text.replace(/((?:\|.+\|\n?){3,})/g, (tableBlock) => {
    const lines = tableBlock.trim().split('\n').filter(l => l.trim())
    const isTable = lines.length >= 2 && lines.every(l => l.trim().startsWith('|'))
    if (!isTable) return tableBlock

    const parseRow = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
    const headers = parseRow(lines[0])
    const isAlignRow = (l) => /^\|[\s\-:|\s]+\|$/.test(l.trim())
    const bodyLines = lines.slice(1).filter(l => !isAlignRow(l))

    const head = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`
    const body = `<tbody>${bodyLines.map(l => `<tr>${parseRow(l).map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`
    return `<div class="ai-table-wrapper"><table class="ai-table">${head}${body}</table></div>`
  })

  // Headings
  text = text.replace(/^### (.+)$/gm, '<h3 class="ai-h3">$1</h3>')
  text = text.replace(/^## (.+)$/gm, '<h2 class="ai-h2">$1</h2>')
  text = text.replace(/^# (.+)$/gm, '<h1 class="ai-h1">$1</h1>')

  // Bold, italic
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Lists (gather consecutive - lines into a <ul>)
  text = text.replace(/((?:^[-•] .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^[-•] /, '')}</li>`)
    return `<ul class="ai-list">${items.join('')}</ul>`
  })

  // Numbered lists
  text = text.replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
    const items = block.trim().split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`)
    return `<ol class="ai-list">${items.join('')}</ol>`
  })

  // Horizontal rules
  text = text.replace(/^[=\-]{3,}$/gm, '<hr class="ai-hr">')

  // Paragraphs (remaining lines)
  const lines = text.split('\n')
  const out = []
  for (const line of lines) {
    const t = line.trim()
    if (!t) continue
    if (/^<(h[1-3]|ul|ol|pre|div|hr|table)/.test(t)) {
      out.push(t)
    } else {
      out.push(`<p>${t}</p>`)
    }
  }

  const rawHtml = out.join('\n')

  // Sanitize to prevent XSS — allows safe HTML tags only
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'h1', 'h2', 'h3',
      'ul', 'ol', 'li', 'hr', 'pre', 'code',
      'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span',
    ],
    ALLOWED_ATTR: ['class'],
  })
}
