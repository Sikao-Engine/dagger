/**
 * Artifact slot renderers. Each renderer takes the decoded text of one slot
 * and renders it per the slot's `view`. Renderers are domain-agnostic; the
 * domain only declares `view: "markdown"` etc., and the matching renderer
 * here does the work.
 *
 * Views are a closed set matching the kernel's `KNOWN_VIEWS` (see
 * `divdag_kernel/state/artifact_spec.py`). Adding a new view requires:
 *   1. add it to KNOWN_VIEWS in the kernel
 *   2. add a renderer here
 *   3. wire it in `renderArtifactView`
 */

import type { ComponentType } from 'react'
import { useMemo } from 'react'
import { cn } from '@lib/utils'

export interface ArtifactViewProps {
  content: string
  slotName: string
  className?: string
}

/** prose: plain text, long-form, wrapped. */
export function ProseView({ content, className }: ArtifactViewProps) {
  return (
    <div className={cn('text-sm text-slate-200 whitespace-pre-wrap break-words', className)}>
      {content}
    </div>
  )
}

/** markdown: rendered markdown. Minimal renderer — headings, bold, code, lists. */
export function MarkdownView({ content, className }: ArtifactViewProps) {
  const html = useMemo(() => renderMarkdown(content), [content])
  return (
    <div
      className={cn('prose prose-invert prose-sm max-w-none', className)}
      // content is from a trusted Agent artifact (sha256-pinned); escape happens in renderMarkdown
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

/** code: monospace, no wrap, horizontal scroll for long lines. */
export function CodeView({ content, className }: ArtifactViewProps) {
  return (
    <pre
      className={cn(
        'text-xs font-mono text-slate-300 overflow-auto bg-slate-950/60 rounded p-3',
        className,
      )}
    >
      {content}
    </pre>
  )
}

/** json: pretty-printed JSON object. Falls back to raw text if not parseable. */
export function JsonView({ content, className }: ArtifactViewProps) {
  const pretty = useMemo(() => {
    try {
      return JSON.stringify(JSON.parse(content), null, 2)
    } catch {
      return content
    }
  }, [content])
  return (
    <pre
      className={cn(
        'text-xs font-mono text-emerald-200/90 overflow-auto bg-slate-950/60 rounded p-3',
        className,
      )}
    >
      {pretty}
    </pre>
  )
}

/** json-table: array of objects as a table. Falls back to JsonView if not an array. */
export function JsonTableView({ content, slotName, className }: ArtifactViewProps) {
  const rows = useMemo<Record<string, unknown>[] | null>(() => {
    try {
      const parsed = JSON.parse(content)
      if (Array.isArray(parsed) && parsed.every((r) => r && typeof r === 'object')) {
        return parsed as Record<string, unknown>[]
      }
    } catch {
      /* fall through */
    }
    return null
  }, [content])

  if (rows === null || rows.length === 0) {
    return <JsonView content={content} slotName={slotName} className={className} />
  }

  const cols = Array.from(
    rows.reduce<Set<string>>((acc, r) => {
      for (const k of Object.keys(r)) acc.add(k)
      return acc
    }, new Set()),
  )

  return (
    <div className={cn('overflow-auto rounded border border-slate-800', className)}>
      <table className="w-full text-xs">
        <thead className="bg-slate-900 text-slate-400">
          <tr>
            {cols.map((c) => (
              <th key={c} className="text-left font-mono px-2 py-1 border-b border-slate-800">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-800/50">
              {cols.map((c) => (
                <td key={c} className="px-2 py-1 font-mono text-slate-300 align-top">
                  {cellText(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** list: bullet list of strings. Falls back to prose if not an array. */
export function ListView({ content, slotName, className }: ArtifactViewProps) {
  const items = useMemo<string[] | null>(() => {
    try {
      const parsed = JSON.parse(content)
      if (Array.isArray(parsed) && parsed.every((i) => typeof i === 'string' || typeof i === 'number')) {
        return parsed.map(String)
      }
    } catch {
      /* fall through */
    }
    return null
  }, [content])

  if (items === null) {
    return <ProseView content={content} slotName={slotName} className={className} />
  }

  return (
    <ul className={cn('list-disc pl-5 space-y-1 text-sm text-slate-200', className)}>
      {items.map((i, idx) => (
        <li key={idx}>{i}</li>
      ))}
    </ul>
  )
}

/** diff: two-slot left/right diff. The renderer itself is layout-only; the
 *  EvidenceViewer pairs two slots and passes them here. */
export interface DiffViewProps {
  leftLabel: string
  leftContent: string
  rightLabel: string
  rightContent: string
  className?: string
}

export function DiffView({ leftLabel, leftContent, rightLabel, rightContent, className }: DiffViewProps) {
  const hunks = useMemo(() => computeDiffHunks(leftContent, rightContent), [leftContent, rightContent])
  return (
    <div className={cn('flex flex-col', className)}>
      <div className="grid grid-cols-2 gap-px bg-slate-800 rounded overflow-hidden">
        <div className="bg-slate-900 px-2 py-1 text-xs font-mono text-slate-400 border-b border-slate-800">
          {leftLabel}
        </div>
        <div className="bg-slate-900 px-2 py-1 text-xs font-mono text-slate-400 border-b border-slate-800">
          {rightLabel}
        </div>
        <div className="bg-slate-950/60 col-span-2 max-h-[60vh] overflow-auto font-mono text-xs">
          {hunks.map((h, i) => (
            <div key={i} className="flex">
              <div className="flex-1 px-2 py-0.5 whitespace-pre-wrap break-all">
                {h.left === '' ? '' : h.left}
                {h.left === '' && <span className="text-slate-700">·</span>}
              </div>
              <div className="flex-1 px-2 py-0.5 whitespace-pre-wrap break-all border-l border-slate-800">
                {h.right === '' ? '' : h.right}
                {h.right === '' && <span className="text-slate-700">·</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── dispatch ────────────────────────────────────────────────────────────────

/** Pick the renderer for a `view` string. Returns null for layout hints
 *  (tabs/diff-grid) which are handled by the EvidenceViewer itself. */
export function renderArtifactView(view: string): ComponentType<ArtifactViewProps> | null {
  switch (view) {
    case 'prose':
      return ProseView
    case 'markdown':
      return MarkdownView
    case 'code':
      return CodeView
    case 'json':
      return JsonView
    case 'json-table':
      return JsonTableView
    case 'list':
      return ListView
    // tabs / diff-grid / diff are layout hints handled by EvidenceViewer.
    case 'tabs':
    case 'diff-grid':
    case 'diff':
      return null
    default:
      return null
  }
}

// ── helpers ─────────────────────────────────────────────────────────────────

function cellText(v: unknown): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

/** Minimal, safe markdown renderer. Escapes HTML first, then applies a tiny
 *  subset: headings, bold, inline code, fenced code blocks, unordered lists,
 *  paragraphs. Not a full CommonMark — Agent artifacts are simple and this
 *  avoids pulling a markdown dep with its own XSS surface. */
export function renderMarkdown(src: string): string {
  // Escape first.
  let s = src
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

  // Fenced code blocks ```...```
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, (_match, _lang, code: string) => {
    return `<pre><code>${code.replace(/\n$/, '')}</code></pre>`
  })

  // Headings (1-3 levels).
  s = s.replace(/^###\s+(.*)$/gm, '<h3>$1</h3>')
  s = s.replace(/^##\s+(.*)$/gm, '<h2>$1</h2>')
  s = s.replace(/^#\s+(.*)$/gm, '<h1>$1</h1>')

  // Bold + italic + inline code.
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')

  // Unordered list: group consecutive "- " lines.
  s = s.replace(/(?:^|\n)((?:- [^\n]+\n?)+)/g, (_m, block: string) => {
    const items = block
      .trim()
      .split('\n')
      .map((l) => l.replace(/^[-*]\s+/, '').trim())
      .filter(Boolean)
      .map((i) => `<li>${i}</li>`)
      .join('')
    return `\n<ul>${items}</ul>\n`
  })

  // Paragraphs: blank-line separated blocks not already wrapped.
  s = s
    .split(/\n{2,}/)
    .map((block) => {
      const t = block.trim()
      if (!t) return ''
      if (/^<(h[1-3]|ul|ol|pre|p|blockquote)/.test(t)) return t
      return `<p>${t.replace(/\n/g, '<br/>')}</p>`
    })
    .filter(Boolean)
    .join('\n')

  return s
}

/** Compute a line-by-line diff for the diff view. Returns aligned hunks where
 *  matching lines have identical left/right, and unmatched lines show on one
 *  side only. This is a LCS-based diff — O(n*m) but artifacts are small. */
export function computeDiffHunks(left: string, right: string): Array<{ left: string; right: string }> {
  const la = left.split('\n')
  const ra = right.split('\n')
  const n = la.length
  const m = ra.length
  // dp[i][j] = LCS length of la[i:] and ra[j:]
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (la[i] === ra[j]) dp[i][j] = dp[i + 1][j + 1] + 1
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: Array<{ left: string; right: string }> = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (la[i] === ra[j]) {
      out.push({ left: la[i], right: ra[j] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ left: la[i], right: '' })
      i++
    } else {
      out.push({ left: '', right: ra[j] })
      j++
    }
  }
  while (i < n) {
    out.push({ left: la[i], right: '' })
    i++
  }
  while (j < m) {
    out.push({ left: '', right: ra[j] })
    j++
  }
  return out
}
