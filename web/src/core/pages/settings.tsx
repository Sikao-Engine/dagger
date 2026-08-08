import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { useServerStore } from '@core/store/server'

export default function SettingsPage() {
  const health = useServerStore((s) => s.health)
  const domains = useServerStore((s) => s.domains)

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold">设置</h1>
        <p className="text-sm text-slate-400">部署能力 + 领域插件</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>服务</CardTitle>
          <CardDescription>后端健康状态</CardDescription>
        </CardHeader>
        <CardContent>
          <Badge variant={health === 'ok' ? 'default' : 'destructive'}>{health}</Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>领域插件</CardTitle>
          <CardDescription>{domains.length} 个</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {domains.length === 0 && <p className="text-sm text-slate-500">无</p>}
          {domains.map((d) => (
            <div key={d.id} className="flex items-center justify-between">
              <span className="font-mono text-sm">{d.id}</span>
              <Badge variant="secondary">{d.version}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
