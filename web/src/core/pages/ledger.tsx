import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { Button } from '@ui/button'
import { Input } from '@ui/input'
import { ScrollArea } from '@ui/scroll-area'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@ui/table'
import { listLedger, refreshLedger, type LedgerItemOut, type DomainOut } from '@sdk/client'
import { useServerStore } from '@core/store/server'

export default function LedgerPage() {
  const domains = useServerStore((s) => s.domains)
  const [projectId, setProjectId] = useState('')
  const [items, setItems] = useState<LedgerItemOut[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null)

  useEffect(() => {
    if (domains.length > 0 && !projectId) {
      setProjectId(domains[0].id)
    }
  }, [domains, projectId])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const r = await listLedger(projectId, statusFilter ? { status: statusFilter } : {})
        if (!cancelled) setItems(r)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, statusFilter])

  async function loadLedger() {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const r = await listLedger(projectId, statusFilter ? { status: statusFilter } : {})
      setItems(r)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleRefresh() {
    setRefreshing(true)
    setRefreshMsg(null)
    try {
      const r = await refreshLedger(projectId, { items_dir: '' })
      setRefreshMsg(`refreshed: ${r.items_upserted} items, ${r.milestones_upserted} milestones`)
      await loadLedger()
    } catch (err) {
      setRefreshMsg(err instanceof Error ? err.message : String(err))
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold">台账</h1>
        <p className="text-sm text-slate-400">全量工作项</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>筛选</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-2 flex-wrap">
          <select
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            {domains.map((d: DomainOut) => (
              <option key={d.id} value={d.id}>
                {d.id}
              </option>
            ))}
          </select>
          <Input
            placeholder="status filter (unseen/seen/resolved)"
            className="w-56"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          />
          <Button onClick={() => void loadLedger()} disabled={loading}>
            {loading ? '加载中...' : '刷新'}
          </Button>
          <Button variant="outline" onClick={() => void handleRefresh()} disabled={refreshing}>
            {refreshing ? 'refreshing...' : 'Refresh ledger'}
          </Button>
          {refreshMsg && <span className="text-xs text-slate-400">{refreshMsg}</span>}
        </CardContent>
      </Card>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle>Items ({items.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea className="max-h-[70vh]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">seq</TableHead>
                  <TableHead className="w-24">item_id</TableHead>
                  <TableHead>title</TableHead>
                  <TableHead className="w-24">status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((it) => (
                  <TableRow key={it.id}>
                    <TableCell className="font-mono text-xs">{it.seq}</TableCell>
                    <TableCell className="font-mono text-xs text-blue-300">
                      {it.item_id}
                    </TableCell>
                    <TableCell className="text-sm truncate max-w-md">{it.title}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{it.status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}
