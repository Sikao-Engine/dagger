import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Search } from 'lucide-react'
import { Button } from '@ui/button'
import { Badge } from '@ui/badge'
import { Input } from '@ui/input'
import { cn } from '@lib/utils'
import EvidenceViewer from '@core/components/review/evidence-viewer'
import { getRun, type RunOut } from '@sdk/client'

/** Item-evidence review page. This is the primary review entry — pick an item,
 *  see the Agent's evidence + decisions for that one item. */
export default function ItemEvidencePage() {
  const { runId = '', itemId: routeItemId = '' } = useParams<{
    runId: string
    itemId: string
  }>()
  const [run, setRun] = useState<RunOut | null>(null)
  const [filter, setFilter] = useState('')
  // `_` is the "no item selected yet" sentinel from the Evidence entry button.
  const hasItem = routeItemId && routeItemId !== '_'
  const selected = hasItem ? routeItemId : ''

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await getRun(runId)
        if (!cancelled) setRun(r)
      } catch {
        /* page-level error handled by EvidenceViewer */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId])

  const items = useMemo(() => {
    if (!run?.items) return []
    const seen = new Set<string>()
    const out: Array<{ id: string; seq: number; title: string }> = []
    for (const raw of run.items) {
      const id = String(raw.id ?? '')
      if (!id || seen.has(id)) continue
      seen.add(id)
      out.push({ id, seq: Number(raw.seq ?? 0), title: String(raw.title ?? id) })
    }
    return out.sort((a, b) => a.seq - b.seq)
  }, [run])

  const filtered = useMemo(() => {
    if (!filter) return items
    const q = filter.toLowerCase()
    return items.filter((i) => i.id.toLowerCase().includes(q) || i.title.toLowerCase().includes(q))
  }, [items, filter])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 p-3 border-b border-slate-800 bg-slate-900">
        <Link to={`/runs/${encodeURIComponent(runId)}`}>
          <Button variant="ghost" size="icon">
            <ArrowLeft size={16} />
          </Button>
        </Link>
        <h1 className="text-sm font-mono flex-1 truncate">
          Evidence · {runId}
          {selected && <span className="text-slate-500"> · {selected}</span>}
        </h1>
        {run && <Badge variant="secondary">{run.domain_id}</Badge>}
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Item picker */}
        <div className="w-64 flex-shrink-0 border-r border-slate-800 bg-slate-900 flex flex-col">
          <div className="p-2 border-b border-slate-800">
            <div className="relative">
              <Search
                size={12}
                className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500"
              />
              <Input
                placeholder="filter items..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="pl-7 h-8 text-xs"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="p-3 text-xs text-slate-500">no items</div>
            ) : (
              filtered.map((i) => (
                <Link
                  key={i.id}
                  to={`/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(i.id)}/evidence`}
                  className={cn(
                    'block px-3 py-2 border-b border-slate-800/50 hover:bg-slate-800/50',
                    selected === i.id && 'bg-blue-900/30 border-l-2 border-l-blue-500',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-slate-500 w-8">{i.seq}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono text-slate-300 truncate">{i.id}</div>
                      <div className="text-[10px] text-slate-500 truncate">{i.title}</div>
                    </div>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Evidence viewer */}
        <div className="flex-1 overflow-hidden">
          {selected ? (
            <EvidenceViewer runId={runId} itemId={selected} />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-500 text-sm">
              Select an item to review its evidence.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
