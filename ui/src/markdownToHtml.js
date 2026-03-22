/**
 * Lightweight Markdown → HTML converter for chat bubbles.
 *
 * Handles the most common LLM output patterns:
 *   headings, bold, italic, inline code, fenced code blocks,
 *   links, blockquotes, horizontal rules, tables, and bullet/numbered lists.
 *
 * Raw HTML in the input is escaped before processing so user/LLM content
 * cannot inject arbitrary HTML.
 */

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// Apply inline formatting to an already-escaped string.
function inlineFmt(s) {
  // Bold: **text**
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // Italic: *text* (not preceded/followed by another *)
  s = s.replace(/\*([^*\n]+?)\*/g, '<em>$1</em>')
  // Italic: _text_
  s = s.replace(/_([^_\n]+?)_/g, '<em>$1</em>')
  // Inline code: `code`
  s = s.replace(/`([^`\n]+?)`/g, '<code>$1</code>')
  // Links: [text](url)
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  return s
}

function convertTable(block) {
  const rows = block.trim().split('\n').filter(ln => !/^\|[\s\-:|]+\|$/.test(ln.trim()))
  if (!rows.length) return ''

  const parseRow = ln => ln.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())

  const header = parseRow(rows[0])
  const body = rows.slice(1)

  const th = header.map(c => `<th>${inlineFmt(escapeHtml(c))}</th>`).join('')
  const trs = body.map(ln => {
    const cells = parseRow(ln)
    const tds = cells.map(c => `<td>${inlineFmt(escapeHtml(c))}</td>`).join('')
    return `<tr>${tds}</tr>`
  }).join('')

  return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`
}

export function markdownToHtml(text) {
  const stash = {}
  let n = 0
  const save = html => { const k = `\x00${n++}\x00`; stash[k] = html; return k }

  // Stash fenced code blocks.
  text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const cls = lang ? ` class="language-${escapeHtml(lang)}"` : ''
    return save(`<pre><code${cls}>${escapeHtml(code.replace(/\n$/, ''))}</code></pre>`)
  })

  // Stash inline code (after fenced, so ``` wins).
  text = text.replace(/`([^`\n]+?)`/g, (_, c) => save(`<code>${escapeHtml(c)}</code>`))

  // Stash tables (contiguous lines starting with |).
  text = text.replace(/((?:^|\n)(\|[^\n]+\n?)+)/g, (match) => {
    return '\n' + save(convertTable(match)) + '\n'
  })

  // Process line by line for block-level elements.
  const lines = text.split('\n')
  const out = []
  let listStack = [] // tracks open ul/ol tags

  const closeLists = () => {
    while (listStack.length) { out.push(listStack.pop()) }
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const line = raw.trimEnd()

    // Stash placeholder — emit as-is.
    if (line.includes('\x00')) { closeLists(); out.push(line); continue }

    // Horizontal rule.
    if (/^[-*_]{3,}$/.test(line.trim())) { closeLists(); out.push('<hr>'); continue }

    // ATX heading.
    const hm = line.match(/^(#{1,6})\s+(.+)$/)
    if (hm) {
      closeLists()
      const lvl = Math.min(hm[1].length, 4)  // cap at h4 for visual balance
      out.push(`<h${lvl}>${inlineFmt(escapeHtml(hm[2]))}</h${lvl}>`)
      continue
    }

    // Blockquote.
    const bq = line.match(/^>\s*(.*)/)
    if (bq) {
      closeLists()
      out.push(`<blockquote>${inlineFmt(escapeHtml(bq[1]))}</blockquote>`)
      continue
    }

    // Unordered list item: - or * or +
    const ul = line.match(/^(\s*)[*\-+]\s+(.+)$/)
    if (ul) {
      if (!listStack.length || listStack[listStack.length - 1] !== '</ul>') {
        closeLists(); out.push('<ul>'); listStack.push('</ul>')
      }
      out.push(`<li>${inlineFmt(escapeHtml(ul[2]))}</li>`)
      continue
    }

    // Ordered list item: 1.
    const ol = line.match(/^(\s*)\d+\.\s+(.+)$/)
    if (ol) {
      if (!listStack.length || listStack[listStack.length - 1] !== '</ol>') {
        closeLists(); out.push('<ol>'); listStack.push('</ol>')
      }
      out.push(`<li>${inlineFmt(escapeHtml(ol[2]))}</li>`)
      continue
    }

    // Empty line closes lists and adds paragraph break.
    if (line.trim() === '') {
      closeLists()
      // Avoid double <br> — only emit if previous output isn't already blank.
      if (out.length && out[out.length - 1] !== '<br>') out.push('<br>')
      continue
    }

    // Regular paragraph line.
    closeLists()
    out.push(`<p>${inlineFmt(escapeHtml(line))}</p>`)
  }

  closeLists()

  let result = out.join('\n')

  // Restore stashed blocks.
  for (const [k, v] of Object.entries(stash)) {
    result = result.replaceAll(k, v)
  }

  // Collapse multiple consecutive <br> tags.
  result = result.replace(/(<br>\n*){2,}/g, '<br>')

  return result
}
