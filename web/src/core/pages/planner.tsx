import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { Button } from '@ui/button'
import { Input } from '@ui/input'
import { Label } from '@ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@ui/select'
import { getPlan, createRun, type PlanSnapshot, type DomainOut } from '@sdk/client'
import { useServerStore } from '@core/store/server'

export default function PlannerPage() {
  const navigate = useNavigate()
  const domains = useServerStore((s) => s.domains)
  const [projectId, setProjectId] = useState('')
  const [plan, setPlan] = useState<PlanSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [domainId, setDomainId] = useState('')
  const [itemsDir, setItemsDir] = useState('')
  const [shards, setShards] = useState(3)
  const [backend, setBackend] = useState('mock')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (domains.length > 0 && !projectId) {
      setProjectId(domains[0].id)
      setDomainId(domains[0].id)
    }
  }, [domains, projectId])

  async function loadPlan(pid: string) {
    setLoading(true)
    setError(null)
    try {
      const r = await getPlan(pid)
      setPlan(r)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (projectId) void loadPlan(projectId)
  }, [projectId])

  async function handleCreateRun() {
    setCreating(true)
    setError(null)
    try {
      const r = await createRun({
        domain_id: domainId,
        items_dir: itemsDir,
        shards,
        backend,
        base_ref: '',
      })
      navigate(`/runs/${encodeURIComponent(r.run_id)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold">规划</h1>
        <p className="text-sm text-slate-400">台账进度 + 分片建议 + 创建 Run</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>领域</CardTitle>
          <CardDescription>选择领域查看 plan</CardDescription>
        </CardHeader>
        <CardContent>
          <Select
            value={projectId}
            onValueChange={(v) => {
              setProjectId(v)
              setDomainId(v)
            }}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="select domain" />
            </SelectTrigger>
            <SelectContent>
              {domains.map((d: DomainOut) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {plan && (
        <Card>
          <CardHeader>
            <CardTitle>进度</CardTitle>
            <CardDescription>
              {plan.total_items} items ·{' '}
              {Object.entries(plan.by_status ?? {})
                .map(([k, v]) => `${k}:${v}`)
                .join(' · ')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(plan.milestones ?? []).length > 0 && (
              <div>
                <div className="text-xs text-slate-500 mb-1">Milestones</div>
                <div className="flex flex-wrap gap-1">
                  {plan.milestones!.map((m) => (
                    <Badge key={m.id} variant={m.status === 'closed' ? 'secondary' : 'outline'}>
                      {m.name}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div>
              <div className="text-xs text-slate-500 mb-1">分片建议</div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>建议</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(plan.suggestions ?? []).map((s, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">{i + 1}</TableCell>
                      <TableCell>
                        <pre className="text-xs font-mono text-slate-300">
                          {JSON.stringify(s, null, 2)}
                        </pre>
                      </TableCell>
                    </TableRow>
                  ))}
                  {(plan.suggestions ?? []).length === 0 && (
                    <TableRow>
                      <TableCell colSpan={2} className="text-slate-500 text-sm">
                        无建议
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>创建 Run</CardTitle>
          <CardDescription>从当前领域 + 配置创建一次批量作业</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>domain</Label>
              <Input value={domainId} onChange={(e) => setDomainId(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>items_dir</Label>
              <Input
                value={itemsDir}
                onChange={(e) => setItemsDir(e.target.value)}
                placeholder="./data"
              />
            </div>
            <div className="space-y-1">
              <Label>shards</Label>
              <Input
                type="number"
                min={1}
                value={shards}
                onChange={(e) => setShards(Number(e.target.value))}
              />
            </div>
            <div className="space-y-1">
              <Label>backend</Label>
              <Select value={backend} onValueChange={setBackend}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="mock">mock</SelectItem>
                  <SelectItem value="opencode-http">opencode-http</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <Button onClick={() => void handleCreateRun()} disabled={creating || loading}>
            {creating ? '创建中...' : '创建 Run'}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
