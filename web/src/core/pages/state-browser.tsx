import { useParams, Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Database } from 'lucide-react'
import { useEffect, useState, useMemo } from 'react'
import { Button } from '@ui/button'
import { Badge } from '@ui/badge'
import { Input } from '@ui/input'
import { ScrollArea } from '@ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@ui/table'
import { getStateIndex, getStateObject, type StateIndexEntry } from '@sdk/client'
import { cn } from '@lib/utils'

const LAYERS = ['control', 'contract', 'scratch', 'artifact', 'log'] as const

export default function StateBrowserPage() {
  const { runId = '' } = useParams<{ runId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<StateIndexEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<StateIndexEntry | null>(null)
  const [body, setBody] = useState<unknown>(null)
  const [bodyLoading, setBodyLoading] = useState(false)

  const layerFilter = searchParams.get('layer') || ''
  const kindFilter = searchParams.get('kind') || ''
  const textFilter = searchParams.get('q') || ''

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await getStateIndex(runId)
        if (!cancelled) setEntries(r)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runId])

  const kinds = useMemo(() => {
    const s = new Set<string>()
    for (const e of entries) s.add(e.kind)
    return Array.from(s).sort()
  }, [entries])

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (layerFilter && e.layer !== layerFilter) return false
      if (kindFilter && e.kind !== kindFilter) return false
      if (textFilter) {
        const hay = `${e.path} ${e.kind} ${e.node_run_id} ${e.shard_id} ${e.item_id} ${e.slot}`
        if (!hay.toLowerCase().includes(textFilter.toLowerCase())) return false
      }
      return true
    })
  }, [entries, layerFilter, kindFilter, textFilter])

  async function selectEntry(e: StateIndexEntry) {
    setSelected(e)
    setBody(null)
    setBodyLoading(true)
    try {
      const obj = await getStateObject(runId, {
        layer: e.layer,
        node_run_id: e.node_run_id || undefined,
        shard_id: e.shard_id || undefined,
        attempt: e.attempt || undefined,
        slot: e.slot || undefined,
      })
      setBody(obj.body)
    } catch (err) {
      setBody({ error: err instanceof Error ? err.message : String(err) })
    } finally {
      setBodyLoading(false)
    }
  }

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 p-3 border-b border-slate-800 bg-slate-900">
        <Link to={`/runs/${encodeURIComponent(runId)}`}>
          <Button variant="ghost" size="icon">
            <ArrowLeft size={16} />
          </Button>
        </Link>
        <h1 className="text-sm font-mono flex-1">State · {runId}</h1>
        <Database size={14} className="text-slate-500" />
      </div>

      {error && <div className="px-3 py-1 text-xs text-red-400">{error}</div>}

      <div className="flex items-center gap-2 p-2 border-b border-slate-800 bg-slate-900/50 flex-wrap">
        <Select value={layerFilter} onValueChange={(v) => updateParam('layer', v === 'all' ? '' : v)}>
          <SelectTrigger className="w-32" size="sm">
            <SelectValue placeholder="layer" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">all layers</SelectItem>
            {LAYERS.map((l) => (
              <SelectItem key={l} value={l}>
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={kindFilter || 'all'} onValueChange={(v) => updateParam('kind', v === 'all' ? '' : v)}>
          <SelectTrigger className="w-40" size="sm">
            <SelectValue placeholder="kind" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">all kinds</SelectItem>
            {kinds.map((k) => (
              <SelectItem key={k} value={k}>
                {k}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          placeholder="filter path/kind/id..."
          className="w-56"
          value={textFilter}
          onChange={(e) => updateParam('q', e.target.value)}
        />

        <Badge variant="secondary" className="ml-auto">
          {filtered.length}/{entries.length}
        </Badge>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-hidden">
          {loading ? (
            <div className="p-4 text-sm text-slate-500">加载 index...</div>
          ) : (
            <ScrollArea className="h-full">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20">layer</TableHead>
                    <TableHead className="w-28">kind</TableHead>
                    <TableHead>path</TableHead>
                    <TableHead className="w-20">size</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((e, i) => (
                    <TableRow
                      key={i}
                      onClick={() => void selectEntry(e)}
                      className={cn('cursor-pointer', selected === e && 'bg-slate-800')}
                    >
                      <TableCell>
                        <span className="text-xs font-mono text-slate-400">{e.layer}</span>
                      </TableCell>
                      <TableCell>
                        <span className="text-xs font-mono text-blue-300">{e.kind}</span>
                      </TableCell>
                      <TableCell className="font-mono text-xs truncate max-w-md">
                        {e.path}
                      </TableCell>
                      <TableCell className="text-xs text-slate-500">{e.size}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          )}
        </div>

        {selected && (
          <div className="w-96 border-l border-slate-800 bg-slate-900 flex flex-col">
            <div className="p-3 border-b border-slate-800">
              <div className="text-xs text-slate-500">kind</div>
              <div className="font-mono text-sm text-blue-300">{selected.kind}</div>
              <div className="text-xs text-slate-500 mt-2">path</div>
              <div className="font-mono text-xs text-slate-300 break-all">{selected.path}</div>
            </div>
            <div className="flex-1 overflow-auto p-3">
              {bodyLoading ? (
                <div className="text-sm text-slate-500">加载...</div>
              ) : (
                <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap break-all">
                  {body === null ? '(binary)' : JSON.stringify(body, null, 2)}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
