import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { listRuns, type RunOut, type DomainOut } from '@sdk/client'
import { useServerStore } from '@core/store/server'
import { formatDatetime } from '@lib/utils'

export default function OverviewPage() {
  const [runs, setRuns] = useState<RunOut[]>([])
  const domains = useServerStore((s) => s.domains)
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
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">概览</h1>
        <p className="text-sm text-slate-400">全部 Run 状态 + 已安装领域</p>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>已安装领域</CardTitle>
            <CardDescription>{domains.length} 个领域插件</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {domains.length === 0 && <p className="text-sm text-slate-500">无</p>}
            {domains.map((d: DomainOut) => (
              <div key={d.id} className="flex items-center justify-between">
                <span className="font-mono text-sm">{d.id}</span>
                <Badge variant="secondary">{d.version}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>近期 Runs</CardTitle>
            <CardDescription>{runs.length} 个 Run</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-sm text-slate-500">加载中...</p>
            ) : runs.length === 0 ? (
              <p className="text-sm text-slate-500">无 Run</p>
            ) : (
              <div className="space-y-2">
                {runs.slice(0, 10).map((r) => (
                  <Link
                    key={r.id}
                    to={`/runs/${encodeURIComponent(r.id)}`}
                    className="flex items-center justify-between hover:bg-slate-800/50 rounded px-2 py-1.5 transition-colors"
                  >
                    <span className="font-mono text-xs truncate flex-1">{r.id}</span>
                    <Badge>{r.status}</Badge>
                    <span className="text-xs text-slate-500 ml-2">
                      {formatDatetime(r.created_at)}
                    </span>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
