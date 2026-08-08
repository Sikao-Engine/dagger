import { describe, expect, it } from 'vitest'

import {
  CodeView,
  DiffView,
  JsonView,
  JsonTableView,
  ListView,
  MarkdownView,
  ProseView,
  computeDiffHunks,
  renderArtifactView,
  renderMarkdown,
} from '@core/components/review/artifact-views'

describe('renderArtifactView dispatch', () => {
  it('maps known content views to their component', () => {
    expect(renderArtifactView('prose')).toBe(ProseView)
    expect(renderArtifactView('markdown')).toBe(MarkdownView)
    expect(renderArtifactView('code')).toBe(CodeView)
    expect(renderArtifactView('json')).toBe(JsonView)
    expect(renderArtifactView('json-table')).toBe(JsonTableView)
    expect(renderArtifactView('list')).toBe(ListView)
  })

  it('returns null for layout hints handled by the viewer', () => {
    expect(renderArtifactView('tabs')).toBeNull()
    expect(renderArtifactView('diff-grid')).toBeNull()
    expect(renderArtifactView('diff')).toBeNull()
  })

  it('returns null for unknown views', () => {
    expect(renderArtifactView('hologram')).toBeNull()
  })
})

describe('renderMarkdown', () => {
  it('escapes HTML first so agent artifacts cannot inject markup', () => {
    const out = renderMarkdown('<script>alert(1)</script>')
    expect(out).toContain('&lt;script&gt;')
    expect(out).not.toContain('<script>')
  })

  it('renders headings, bold, italic, and inline code', () => {
    const out = renderMarkdown('# Title\n\n**bold** and *italic* and `code`')
    expect(out).toContain('<h1>Title</h1>')
    expect(out).toContain('<strong>bold</strong>')
    expect(out).toContain('<em>italic</em>')
    expect(out).toContain('<code>code</code>')
  })

  it('renders fenced code blocks without interpreting inner markdown', () => {
    const out = renderMarkdown('```js\nconst x = 1\n```')
    expect(out).toContain('<pre><code>const x = 1</code></pre>')
    expect(out).not.toContain('<p>const x = 1</p>')
  })

  it('groups consecutive "- " lines into a <ul>', () => {
    const out = renderMarkdown('- one\n- two\n- three')
    expect(out).toContain('<ul>')
    expect(out).toContain('<li>one</li>')
    expect(out).toContain('<li>three</li>')
  })

  it('wraps untagged paragraphs in <p>', () => {
    const out = renderMarkdown('hello\n\nworld')
    expect(out).toContain('<p>hello</p>')
    expect(out).toContain('<p>world</p>')
  })
})

describe('computeDiffHunks', () => {
  it('aligns identical lines and emits deletions/additions on each side', () => {
    const hunks = computeDiffHunks('a\nb\nc', 'a\nB\nc')
    // a, a (match); b left-only (deletion); B right-only (addition); c, c (match).
    expect(hunks).toHaveLength(4)
    expect(hunks[0]).toEqual({ left: 'a', right: 'a' })
    expect(hunks[1]).toEqual({ left: 'b', right: '' })
    expect(hunks[2]).toEqual({ left: '', right: 'B' })
    expect(hunks[3]).toEqual({ left: 'c', right: 'c' })
  })

  it('pure addition shows on the right side only', () => {
    const hunks = computeDiffHunks('a\nb', 'a\nb\nc')
    const added = hunks.find((h) => h.left === '' && h.right === 'c')
    expect(added).toBeDefined()
  })

  it('pure deletion shows on the left side only', () => {
    const hunks = computeDiffHunks('a\nb\nc', 'a\nc')
    const removed = hunks.find((h) => h.left === 'b' && h.right === '')
    expect(removed).toBeDefined()
  })

  it('empty + empty yields a single empty pair', () => {
    expect(computeDiffHunks('', '')).toEqual([{ left: '', right: '' }])
  })
})

describe('DiffView', () => {
  it('is exported as a component', () => {
    expect(typeof DiffView).toBe('function')
  })
})
