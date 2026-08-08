import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { buttonVariants } from '@ui/button'
import { listRuns, type RunOut } from '@sdk/client'
import { formatDatetime } from '@lib/utils'
import { cn } from '@lib/utils'

export default function RunsPage() {
  const [runs, setRuns] = useState<RunOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await listRuns()
        if (!cancelled) setRuns(r)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Runs</h1>
        <Link to="/planner" className={cn(buttonVariants({ variant: 'default' }), 'no-underline')}>
          创建 Run
        </Link>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle>全部 Run</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-slate-500">加载中...</p>
          ) : runs.length === 0 ? (
            <p className="text-sm text-slate-500">无 Run，前往「规划」页创建</p>
          ) : (
            <div className="space-y-1">
              {runs.map((r) => (
                <Link
                  key={r.id}
                  to={`/runs/${encodeURIComponent(r.id)}`}
                  className="flex items-center gap-3 hover:bg-slate-800/50 rounded px-2 py-2 transition-colors"
                >
                  <span className="font-mono text-xs truncate flex-1">{r.id}</span>
                  <span className="text-xs text-slate-400">{r.domain_id}</span>
                  <Badge>{r.status}</Badge>
                  <span className="text-xs text-slate-500">
                    {formatDatetime(r.created_at)}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
