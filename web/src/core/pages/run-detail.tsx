import { useParams, Link } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, Database, FileSearch } from 'lucide-react'
import { Badge } from '@ui/badge'
import { Button } from '@ui/button'
import { useRunStream } from '@sdk/sse'
import { usePipelineStore } from '@core/store/pipeline'
import DAGCanvas from '@core/components/dag/DAGCanvas'
import NodeDetailPanel from '@core/components/dag/NodeDetailPanel'
import { blockNode, forceSuccessNode, resumeRunFromNode } from '@sdk/client'

export default function RunDetailPage() {
  const { runId = '' } = useParams<{ runId: string }>()
  const { pipeline, connected, error } = useRunStream(runId)
  const { selectedNodeId, selectNode } = usePipelineStore()
  const [actionError, setActionError] = useState<string | null>(null)

  const selectedNode = pipeline?.nodes?.find((n) => n.id === selectedNodeId) ?? null

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 p-3 border-b border-slate-800 bg-slate-900">
        <Link to="/runs">
          <Button variant="ghost" size="icon">
            <ArrowLeft size={16} />
          </Button>
        </Link>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="font-mono text-sm truncate">{runId}</h1>
            {pipeline && <Badge>{pipeline.status}</Badge>}
            <span
              className={`text-xs ${connected ? 'text-emerald-400' : 'text-slate-500'}`}
            >
              {connected ? '● live' : '○ disconnected'}
            </span>
          </div>
          {pipeline && (
            <div className="text-xs text-slate-400">
              {pipeline.completed} success / {pipeline.failed} failed / {pipeline.skipped} skipped
              {' · '}
              template: <span className="font-mono">{pipeline.template_id}</span>
            </div>
          )}
        </div>
        <Link to={`/runs/${encodeURIComponent(runId)}/state`}>
          <Button variant="outline" size="sm">
            <Database size={14} /> State
          </Button>
        </Link>
        <Link to={`/runs/${encodeURIComponent(runId)}/items/_/evidence`}>
          <Button variant="outline" size="sm">
            <FileSearch size={14} /> Evidence
          </Button>
        </Link>
      </div>

      {error && <div className="px-3 py-1 text-xs text-red-400 bg-red-950/30">{error}</div>}
      {actionError && (
        <div className="px-3 py-1 text-xs text-amber-400 bg-amber-950/30">
          {actionError}
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 relative">
          {pipeline ? (
            <DAGCanvas
              pipeline={pipeline}
              selectedNodeId={selectedNodeId}
              onSelectNode={selectNode}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-500 text-sm">
              加载 pipeline...
            </div>
          )}
        </div>
        {selectedNode && pipeline && (
          <NodeDetailPanel
            node={selectedNode}
            runId={runId}
            onClose={() => selectNode(null)}
            onResume={async (rid, nid) => {
              setActionError(null)
              await resumeRunFromNode(rid, nid)
            }}
            onBlock={async (nid, reason) => {
              setActionError(null)
              await blockNode(nid, reason)
            }}
            onSuccess={async (nid, reason) => {
              setActionError(null)
              await forceSuccessNode(nid, reason)
            }}
          />
        )}
      </div>
    </div>
  )
}
