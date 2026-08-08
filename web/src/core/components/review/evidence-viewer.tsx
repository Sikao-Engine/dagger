/**
 * EvidenceViewer: the production-grade review surface.
 *
 * Given a runId + itemId, fetches the domain's `ArtifactSpec` + the per-item
 * `ItemArtifactSlotOut[]` (T7.1) and renders every declared slot via its
 * declared `view`. The component only knows the spec — it does not know the
 * domain. Domains that declare new slots get them rendered for free.
 *
 * Layout modes (from `spec.default_view`):
 *   - `tabs`       : one slot per tab (default for sparse specs like tiny's summary)
 *   - `diff-grid`  : side-by-side grid (for evidence-style prev/incoming/local/...)
 *   - any other    : fall back to a vertical stack
 *
 * The viewer also flags `undeclared` slots (the Agent wrote a slot the spec
 * doesn't list) — these are appended at the end with an amber border so
 * reviewers see spec drift immediately.
 *
 * Bytes fetching is lazy: each slot fetches its raw bytes on first render,
 * caches by sha256, and shows a spinner until ready. A slot with no written
 * artifact (ref: null) shows a "missing" placeholder.
 */

import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, FileQuestion, Loader2 } from 'lucide-react'
import { Badge } from '@ui/badge'
import { Button } from '@ui/button'
import { ScrollArea } from '@ui/scroll-area'
import { cn } from '@lib/utils'
import { getItemArtifactBytes, getItemArtifacts } from '@sdk/client'
import type { ArtifactSpecOut, ItemArtifactSlotOut } from '@sdk/client'
import {
  CodeView,
  DiffView,
  JsonView,
  JsonTableView,
  ListView,
  MarkdownView,
  ProseView,
} from './artifact-views'

interface EvidenceViewerProps {
  runId: string
  itemId: string
  className?: string
}

/** Decode raw bytes to text. Artifacts are UTF-8 text (markdown/prose/json/code);
 *  binary artifacts fall back to a size-only placeholder. */
function decodeText(bytes: Uint8Array): string {
  try {
    return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  } catch {
    return `(binary, ${bytes.byteLength} bytes)`
  }
}

/** Hook: fetch + cache the spec + slot list for one run/item. */
function useItemArtifacts(runId: string, itemId: string) {
  const [spec, setSpec] = useState<ArtifactSpecOut | null>(null)
  const [slots, setSlots] = useState<ItemArtifactSlotOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const r = await getItemArtifacts(runId, itemId)
        if (cancelled) return
        setSpec(r.spec ?? null)
        // The generated type is readonly; copy to a mutable array so downstream
        // filter/map produce a type-compatible list.
        setSlots([...(r.slots ?? [])])
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId, itemId])

  return { spec, slots, loading, error }
}

/** Hook: fetch + cache raw bytes for one slot. Cache key is sha256 so a slot
 *  that re-renders across re-mounts doesn't refetch. */
const bytesCache = new Map<string, string>()

function useSlotBytes(runId: string, itemId: string, slot: ItemArtifactSlotOut) {
  const ref = slot.ref
  const cacheKey = ref ? `${runId}/${itemId}/${slot.slot.name}#${ref.sha256}` : ''
  const cached = ref ? bytesCache.get(cacheKey) : undefined
  const [content, setContent] = useState<string | null>(cached ?? null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!ref) {
      setContent(null)
      return
    }
    if (cached !== undefined) {
      setContent(cached)
      return
    }
    let cancelled = false
    setErr(null)
    void (async () => {
      try {
        const { bytes } = await getItemArtifactBytes(runId, itemId, slot.slot.name)
        if (cancelled) return
        const text = decodeText(bytes)
        bytesCache.set(cacheKey, text)
        setContent(text)
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ref identity covers sha256 changes
  }, [cacheKey, runId, itemId, slot.slot.name])

  return { content, err, missing: !ref }
}

function SlotContent({ content, slot }: { content: string; slot: ItemArtifactSlotOut }) {
  switch (slot.slot.view) {
    case 'prose':
      return <ProseView content={content} slotName={slot.slot.name} />
    case 'markdown':
      return <MarkdownView content={content} slotName={slot.slot.name} />
    case 'code':
      return <CodeView content={content} slotName={slot.slot.name} />
    case 'json':
      return <JsonView content={content} slotName={slot.slot.name} />
    case 'json-table':
      return <JsonTableView content={content} slotName={slot.slot.name} />
    case 'list':
      return <ListView content={content} slotName={slot.slot.name} />
    case 'tabs':
    case 'diff-grid':
    case 'diff':
      return (
        <div className="text-xs text-slate-400">
          (layout view "{slot.slot.view}" — handled by viewer)
        </div>
      )
    default:
      return (
        <div className="text-xs text-slate-400">
          unknown view "{slot.slot.view}"
        </div>
      )
  }
}

// ── SlotCard: one slot's renderer + chrome ─────────────────────────────────

function SlotCard({ runId, itemId, slot }: { runId: string; itemId: string; slot: ItemArtifactSlotOut }) {
  const { content, err, missing } = useSlotBytes(runId, itemId, slot)
  const label = slot.slot.label || slot.slot.name
  const isUndeclared = slot.undeclared

  return (
    <div
      className={cn(
        'rounded-lg border bg-slate-900/50',
        isUndeclared ? 'border-amber-700/60' : 'border-slate-800',
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
        <div className="text-sm font-medium text-slate-200 flex-1 truncate">{label}</div>
        <span className="text-[10px] font-mono text-slate-500">{slot.slot.view}</span>
        {missing && (
          <Badge variant="outline" className="text-amber-400 border-amber-700">
            missing
          </Badge>
        )}
        {isUndeclared && (
          <Badge variant="outline" className="text-amber-400 border-amber-700">
            <AlertTriangle size={10} className="mr-1" />
            undeclared
          </Badge>
        )}
        {slot.ref && (
          <span className="text-[10px] font-mono text-slate-600" title={slot.ref.sha256}>
            {slot.ref.sha256.slice(0, 8)}
          </span>
        )}
      </div>
      <div className="p-3 min-h-[2rem]">
        {err ? (
          <div className="text-xs text-red-400">{err}</div>
        ) : missing ? (
          <div className="flex items-center gap-2 text-xs text-slate-500 italic">
            <FileQuestion size={12} />
            slot not written
          </div>
        ) : content === null ? (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 size={12} className="animate-spin" />
            loading…
          </div>
        ) : (
          <SlotContent content={content} slot={slot} />
        )}
      </div>
    </div>
  )
}

// ── DiffPair: two slots compared side-by-side ──────────────────────────────

function DiffPair({
  runId,
  itemId,
  leftSlot,
  rightSlot,
}: {
  runId: string
  itemId: string
  leftSlot: ItemArtifactSlotOut
  rightSlot: ItemArtifactSlotOut
}) {
  const left = useSlotBytes(runId, itemId, leftSlot)
  const right = useSlotBytes(runId, itemId, rightSlot)
  const leftLabel = leftSlot.slot.label || leftSlot.slot.name
  const rightLabel = rightSlot.slot.label || rightSlot.slot.name
  const leftContent = left.content ?? ''
  const rightContent = right.content ?? ''

  if (left.missing && right.missing) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs text-slate-500 italic">
        both slots missing
      </div>
    )
  }
  if (left.err || right.err) {
    return <div className="text-xs text-red-400">{left.err ?? right.err}</div>
  }
  if (left.content === null || right.content === null) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Loader2 size={12} className="animate-spin" />
        loading diff…
      </div>
    )
  }
  return (
    <DiffView
      leftLabel={leftLabel}
      leftContent={leftContent}
      rightLabel={rightLabel}
      rightContent={rightContent}
    />
  )
}

// ── Main viewer ────────────────────────────────────────────────────────────

export default function EvidenceViewer({ runId, itemId, className }: EvidenceViewerProps) {
  const { spec, slots, loading, error } = useItemArtifacts(runId, itemId)
  const [activeTab, setActiveTab] = useState(0)
  const [layout, setLayout] = useState<string>(spec?.default_view ?? 'tabs')

  // Update layout when spec arrives / changes.
  useEffect(() => {
    if (spec) setLayout(spec.default_view)
  }, [spec])

  // Pair up slots for diff-grid layout: consecutive pairs.
  const diffPairs = useMemo(() => {
    const declared = slots.filter((s) => !s.undeclared)
    const pairs: Array<[ItemArtifactSlotOut, ItemArtifactSlotOut]> = []
    for (let i = 0; i + 1 < declared.length; i += 2) {
      pairs.push([declared[i], declared[i + 1]])
    }
    if (declared.length % 2 === 1) {
      // Trailing odd slot renders alone.
      pairs.push([declared[declared.length - 1], declared[declared.length - 1]])
    }
    return pairs
  }, [slots])

  const declared = slots.filter((s) => !s.undeclared)
  const undeclared = slots.filter((s) => s.undeclared)
  const activeSlot = declared[Math.min(activeTab, declared.length - 1)]

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center p-8 text-slate-500 text-sm', className)}>
        <Loader2 size={14} className="animate-spin mr-2" />
        loading evidence…
      </div>
    )
  }

  if (error) {
    return (
      <div className={cn('p-4 text-sm text-red-400 bg-red-950/30 rounded', className)}>
        {error}
      </div>
    )
  }

  if (!spec) {
    return (
      <div className={cn('p-4 text-sm text-slate-500', className)}>
        This domain declares no <code className="font-mono text-xs">ArtifactSpec</code>. Available
        artifacts:
        {slots.length === 0 ? (
          <span className="ml-1 italic">none.</span>
        ) : (
          <ul className="mt-2 list-disc pl-5">
            {slots.map((s) => (
              <li key={s.slot.name} className="font-mono text-xs text-slate-400">
                {s.slot.name}
                {s.ref && <span className="ml-2 text-slate-600">({s.ref.size} bytes)</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header: spec label + layout switcher + slot count */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800 bg-slate-900">
        <div className="text-sm font-medium text-slate-200 flex-1 truncate">
          {spec.label || `${itemId} evidence`}
        </div>
        <Badge variant="secondary" className="font-mono text-[10px]">
          {declared.length} declared
        </Badge>
        {undeclared.length > 0 && (
          <Badge variant="outline" className="text-amber-400 border-amber-700 font-mono text-[10px]">
            {undeclared.length} undeclared
          </Badge>
        )}
        {declared.length > 1 && (
          <div className="flex items-center gap-1">
            {(['tabs', 'diff-grid', 'stack'] as const).map((m) => (
              <Button
                key={m}
                size="sm"
                variant={layout === m ? 'default' : 'ghost'}
                className="h-7 px-2 text-[11px] font-mono"
                onClick={() => setLayout(m)}
              >
                {m}
              </Button>
            ))}
          </div>
        )}
      </div>

      {/* Body: layout-dependent */}
      <ScrollArea className="flex-1">
        <div className="p-3">
          {declared.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-8">
              No slots declared in this domain's <code className="font-mono text-xs">ArtifactSpec</code>.
            </div>
          ) : layout === 'tabs' && declared.length > 1 ? (
            <div>
              <div className="flex gap-1 border-b border-slate-800 mb-3 overflow-x-auto">
                {declared.map((s, i) => (
                  <button
                    key={s.slot.name}
                    onClick={() => setActiveTab(i)}
                    className={cn(
                      'px-3 py-1.5 text-xs font-medium border-b-2 -mb-px whitespace-nowrap',
                      i === activeTab
                        ? 'border-blue-500 text-blue-300'
                        : 'border-transparent text-slate-400 hover:text-slate-200',
                    )}
                  >
                    {s.slot.label || s.slot.name}
                  </button>
                ))}
              </div>
              {activeSlot && <SlotCard runId={runId} itemId={itemId} slot={activeSlot} />}
            </div>
          ) : layout === 'diff-grid' && declared.length > 1 ? (
            <div className="space-y-4">
              {diffPairs.map(([l, r], i) => (
                <div key={i}>
                  <div className="text-[10px] text-slate-500 mb-1 font-mono">
                    {l.slot.label || l.slot.name} ↔ {r.slot.label || r.slot.name}
                  </div>
                  <DiffPair runId={runId} itemId={itemId} leftSlot={l} rightSlot={r} />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid gap-3">
              {declared.map((s) => (
                <SlotCard key={s.slot.name} runId={runId} itemId={itemId} slot={s} />
              ))}
            </div>
          )}

          {/* Undeclared slots always show at the bottom as a warning band. */}
          {undeclared.length > 0 && (
            <div className="mt-6 pt-3 border-t border-amber-900/40">
              <div className="flex items-center gap-2 text-xs text-amber-400 mb-2">
                <AlertTriangle size={12} />
                Spec drift — Agent wrote to slots the spec doesn't declare:
              </div>
              <div className="grid gap-3">
                {undeclared.map((s) => (
                  <SlotCard key={s.slot.name} runId={runId} itemId={itemId} slot={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
