import { useParams, Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@ui/button'
import { Badge } from '@ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@ui/tabs'
import { getNodeRun, listAttempts, type NodeRunOut, type AttemptOut } from '@sdk/client'

export default function NodeDetailPage() {
  const { runId = '', nodeId = '' } = useParams<{ runId: string; nodeId: string }>()
  const [node, setNode] = useState<NodeRunOut | null>(null)
  const [attempts, setAttempts] = useState<AttemptOut[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [n, a] = await Promise.all([getNodeRun(nodeId), listAttempts(nodeId)])
        if (!cancelled) {
          setNode(n)
          setAttempts(a)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [nodeId])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 p-3 border-b border-slate-800 bg-slate-900">
        <Link to={`/runs/${encodeURIComponent(runId)}`}>
          <Button variant="ghost" size="icon">
            <ArrowLeft size={16} />
          </Button>
        </Link>
        <h1 className="font-mono text-sm flex-1 truncate">{nodeId}</h1>
        {node && <Badge>{node.status}</Badge>}
      </div>

      {error && <div className="px-3 py-1 text-xs text-red-400">{error}</div>}

      <div className="flex-1 overflow-y-auto p-4">
        {node && (
          <Tabs defaultValue="attempts">
            <TabsList>
              <TabsTrigger value="attempts">Attempts ({attempts.length})</TabsTrigger>
              <TabsTrigger value="result">Result</TabsTrigger>
              <TabsTrigger value="error">Error</TabsTrigger>
            </TabsList>
            <TabsContent value="attempts">
              <div className="space-y-1">
                {attempts.length === 0 && (
                  <p className="text-sm text-slate-500">无 Attempt</p>
                )}
                {attempts.map((a) => (
                  <Link
                    key={a.id}
                    to={`/attempts/${encodeURIComponent(a.id)}`}
                    className="flex items-center gap-2 hover:bg-slate-800/50 rounded px-2 py-1.5"
                  >
                    <span className="font-mono text-xs">#{a.attempt}</span>
                    <span className="font-mono text-xs text-slate-400 flex-1 truncate">
                      {a.id}
                    </span>
                    <Badge variant="secondary">{a.backend}</Badge>
                    <Badge>{a.status}</Badge>
                  </Link>
                ))}
              </div>
            </TabsContent>
            <TabsContent value="result">
              <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap">
                {node.result ? JSON.stringify(node.result, null, 2) : '(empty)'}
              </pre>
            </TabsContent>
            <TabsContent value="error">
              <pre className="text-xs font-mono text-red-300 whitespace-pre-wrap">
                {node.error ? JSON.stringify(node.error, null, 2) : '(empty)'}
              </pre>
            </TabsContent>
          </Tabs>
        )}
      </div>
    </div>
  )
}
