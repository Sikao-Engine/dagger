import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@ui/card'
import { Badge } from '@ui/badge'
import { ScrollArea } from '@ui/scroll-area'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@ui/table'
import { listTemplates, listDomains, type TemplateOut, type DomainOut } from '@sdk/client'
import { useServerStore } from '@core/store/server'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@ui/select'

export default function TemplatesPage() {
  const domains = useServerStore((s) => s.domains)
  const [domainFilter, setDomainFilter] = useState<string>('')
  const [templates, setTemplates] = useState<TemplateOut[]>([])
  const [selected, setSelected] = useState<TemplateOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const r = await listTemplates(domainFilter || undefined)
        setTemplates(r)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    })()
  }, [domainFilter])

  useEffect(() => {
    void listDomains().catch(() => {})
  }, [])

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-bold">模板</h1>
        <p className="text-sm text-slate-400">DAG 模板（只读浏览）</p>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      <Card>
        <CardHeader>
          <CardTitle>筛选</CardTitle>
        </CardHeader>
        <CardContent>
          <Select
            value={domainFilter || 'all'}
            onValueChange={(v) => setDomainFilter(v === 'all' ? '' : v)}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="domain" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">all domains</SelectItem>
              {domains.map((d: DomainOut) => (
                <SelectItem key={d.id} value={d.id}>
                  {d.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Templates ({templates.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="max-h-[70vh]">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>id</TableHead>
                    <TableHead>domain</TableHead>
                    <TableHead>nodes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {templates.map((t) => (
                    <TableRow
                      key={t.id}
                      onClick={() => setSelected(t)}
                      className="cursor-pointer"
                    >
                      <TableCell className="font-mono text-xs text-blue-300">
                        {t.id}
                      </TableCell>
                      <TableCell className="text-xs">{t.domain_id}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">{t.nodes.length}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>

        {selected && (
          <Card>
            <CardHeader>
              <CardTitle className="font-mono text-sm">{selected.id}</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap overflow-auto max-h-[60vh]">
                {JSON.stringify(
                  { nodes: selected.nodes, edges: selected.edges },
                  null,
                  2,
                )}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
