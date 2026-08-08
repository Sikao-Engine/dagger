import { Link } from 'react-router-dom'
import { X, Clock, Hash, Zap, RotateCcw, ExternalLink, Ban, CheckCheck } from 'lucide-react'
import { cn } from '@lib/utils'
import {
  STATUS_COLOR,
  STATUS_DOT,
  asNodeStatus,
} from './dag_utils'
import { formatDatetime } from '@lib/utils'
import type { NodeRunOut, PipelineNode } from '@sdk/client'

interface Props {
  node: NodeRunOut | PipelineNode
  runId: string
  onClose: () => void
  onResume?: (runId: string, nodeId: string) => Promise<void>
  onBlock?: (nodeId: string, reason?: string) => Promise<void>
  onSuccess?: (nodeId: string, reason?: string) => Promise<void>
}

function isNodeRunOut(n: NodeRunOut | PipelineNode): n is NodeRunOut {
  return 'result' in n || 'error' in n || 'started_at' in n
}

export default function NodeDetailPanel({
  node,
  runId,
  onClose,
  onResume,
  onBlock,
  onSuccess,
}: Props) {
  const status = asNodeStatus(node.status)
  const icon = '\u25C6'
  const isFull = isNodeRunOut(node)

  const startedAt = isFull ? node.started_at : null
  const finishedAt = isFull ? node.finished_at : null
  const result = isFull ? node.result : null
  const error = isFull ? node.error : null

  return (
    <div className="h-full flex flex-col bg-slate-900 border-l border-slate-700 w-80 flex-shrink-0">
      <div className={cn('flex items-center gap-2 px-4 py-3 border-b border-slate-700', STATUS_COLOR[status])}>
        <span className="text-xl">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm truncate">{node.node_type}</div>
          <div className="text-xs opacity-70 font-mono truncate">{node.id}</div>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-white/10 transition-colors">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <Link
          to={`/runs/${encodeURIComponent(runId)}/nodes/${encodeURIComponent(node.id)}`}
          className="w-full flex items-center justify-center gap-2 text-xs text-blue-200 bg-blue-900/30 hover:bg-blue-800/40 border border-blue-700 hover:border-blue-500 px-3 py-2 rounded transition-colors"
          title="Open node detail (attempts, context, contract, log)"
        >
          <ExternalLink size={13} /> 查看节点详情
        </Link>

        {onResume && (
          <button
            onClick={() => {
              if (!window.confirm(`Resume pipeline from ${node.node_type}? This will reset this node and downstream nodes.`)) return
              void onResume(runId, node.id).catch((err: unknown) => {
                window.alert(err instanceof Error ? err.message : String(err))
              })
            }}
            className="w-full flex items-center justify-center gap-2 text-xs text-amber-200 bg-amber-900/30 hover:bg-amber-800/40 border border-amber-700 hover:border-amber-500 px-3 py-2 rounded transition-colors"
            title="Reset this node and downstream nodes, then restart runner"
          >
            <RotateCcw size={13} /> Resume from this node
          </button>
        )}

        {onBlock && (
          <button
            onClick={() => {
              if (!window.confirm(`Force block node ${node.node_type}? Stops pipeline and kills possible runner.`)) return
              void onBlock(node.id, 'Dashboard manual block: human takeover').catch((err: unknown) => {
                window.alert(err instanceof Error ? err.message : String(err))
              })
            }}
            className="w-full flex items-center justify-center gap-2 text-xs text-red-200 bg-red-950/40 hover:bg-red-900/50 border border-red-800 hover:border-red-500 px-3 py-2 rounded transition-colors"
            title="Force this node to BLOCKED, stop pipeline"
          >
            <Ban size={13} /> 手动 Block
          </button>
        )}

        {onSuccess && (
          <button
            onClick={() => {
              const isBlocker = ['failed', 'blocked', 'running', 'waiting'].includes(node.status)
              const confirmMsg = isBlocker
                ? `Mark ${node.node_type} as SUCCESS (human expert took over)? Advances pipeline downstream.`
                : `Node ${node.node_type} is ${node.status}. Force SUCCESS?`
              if (!window.confirm(confirmMsg)) return
              void onSuccess(node.id, 'Dashboard manual success: human expert takeover complete').catch((err: unknown) => {
                window.alert(err instanceof Error ? err.message : String(err))
              })
            }}
            className="w-full flex items-center justify-center gap-2 text-xs text-emerald-200 bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-800 hover:border-emerald-500 px-3 py-2 rounded transition-colors"
            title="Mark this node as SUCCESS — human expert has taken over"
          >
            <CheckCheck size={13} /> 人类接管（标记 SUCCESS）
          </button>
        )}

        <div className="flex items-center gap-2">
          <span className={cn('w-3 h-3 rounded-full flex-shrink-0', STATUS_DOT[status])} />
          <span className="text-sm font-medium capitalize text-slate-200">{node.status}</span>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-slate-800 rounded p-2">
            <div className="flex items-center gap-1 text-slate-500 mb-1">
              <Clock size={11} /> Started
            </div>
            <div className="text-slate-300">{formatDatetime(startedAt)}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="flex items-center gap-1 text-slate-500 mb-1">
              <Clock size={11} /> Finished
            </div>
            <div className="text-slate-300">{formatDatetime(finishedAt)}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="flex items-center gap-1 text-slate-500 mb-1">
              <Hash size={11} /> Node ID
            </div>
            <div className="text-slate-300 font-mono truncate">{node.id}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="flex items-center gap-1 text-slate-500 mb-1">
              <Zap size={11} /> Priority
            </div>
            <div className="text-slate-300">{node.priority}</div>
          </div>
        </div>

        {(node.dependencies ?? []).length > 0 && (
          <div>
            <div className="text-xs text-slate-500 mb-1">Depends on</div>
            <div className="flex flex-wrap gap-1">
              {(node.dependencies ?? []).map((d) => (
                <span
                  key={d}
                  className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded font-mono"
                >
                  {d}
                </span>
              ))}
            </div>
          </div>
        )}

        {result && (
          <div>
            <div className="text-xs text-slate-500 mb-1">Result</div>
            <pre className="bg-slate-950 rounded p-2 text-xs text-slate-300 font-mono overflow-auto max-h-48">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        )}

        {error && (
          <div>
            <div className="text-xs text-red-400 mb-1">Error</div>
            <pre className="bg-red-950/30 border border-red-800 rounded p-2 text-xs text-red-300 font-mono overflow-auto max-h-48">
              {JSON.stringify(error, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
