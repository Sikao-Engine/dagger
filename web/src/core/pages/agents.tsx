import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@ui/card'
import { Badge } from '@ui/badge'
import { Button } from '@ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@ui/table'
import {
  listProcesses,
  stopProcess,
  stopAllProcesses,
  getProcessesStatus,
  type ManagedProcessOut,
} from '@sdk/client'

export default function AgentsPage() {
  const [procs, setProcs] = useState<ManagedProcessOut[]>([])
  const [statusText, setStatusText] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [p, s] = await Promise.all([listProcesses(), getProcessesStatus()])
      setProcs(p)
      setStatusText(s.status)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function handleStop(key: string) {
    setBusy(key)
    setError(null)
    try {
      await stopProcess(key)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  async function handleStopAll() {
    setBusy('all')
    setError(null)
    try {
      await stopAllProcesses()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold">进程</h1>
        <p className="text-sm text-slate-400">agentcli serve 进程管理</p>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle>状态</CardTitle>
          <CardDescription className="font-mono text-xs">{statusText || '—'}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void refresh()} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </Button>
          <Button
            variant="destructive"
            className="ml-2"
            onClick={() => void handleStopAll()}
            disabled={busy !== null || procs.length === 0}
          >
            Stop all
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>进程列表 ({procs.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {procs.length === 0 ? (
            <p className="text-sm text-slate-500">无进程</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>key</TableHead>
                  <TableHead>port</TableHead>
                  <TableHead>pid</TableHead>
                  <TableHead>status</TableHead>
                  <TableHead>session</TableHead>
                  <TableHead>started</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {procs.map((p) => (
                  <TableRow key={p.key ?? p.path}>
                    <TableCell className="font-mono text-xs text-blue-300">
                      {p.key ?? p.path}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{p.port}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {p.pid ?? '—'}
                    </TableCell>
                    <TableCell>
                      <Badge>{p.status}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-slate-400">
                      {p.session_id ?? '—'}
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">
                      {p.started_at ?? '—'}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => p.key && void handleStop(p.key)}
                        disabled={busy !== null}
                      >
                        stop
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
