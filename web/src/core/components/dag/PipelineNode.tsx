import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { cn } from '@lib/utils'
import { STATUS_COLOR, STATUS_DOT, asNodeStatus } from './dag_utils'
import type { PipelineNode } from '@sdk/client'

export interface PipelineNodeData {
  node: PipelineNode
  selected: boolean
  onClick: () => void
  highlightCounts?: { critical: number; warning: number }
}

function PipelineNode({ data }: NodeProps) {
  const d = data as unknown as PipelineNodeData
  const n = d.node
  const status = asNodeStatus(n.status)

  return (
    <div
      onClick={d.onClick}
      className={cn(
        'relative cursor-pointer rounded-lg border-2 px-3 py-2 w-[210px] transition-all duration-200 select-none',
        STATUS_COLOR[status],
        d.selected ? 'ring-2 ring-white/60 scale-105' : 'hover:scale-[1.02] hover:brightness-110',
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-400 !w-2 !h-2" />

      {(d.highlightCounts?.critical || d.highlightCounts?.warning) ? (
        <div className="absolute -top-2 -right-2 flex gap-1 text-[10px] font-semibold">
          {d.highlightCounts?.critical ? (
            <span className="rounded-full bg-red-700 text-red-50 px-1.5 py-0.5">
              🔴 {d.highlightCounts.critical}
            </span>
          ) : null}
          {d.highlightCounts?.warning ? (
            <span className="rounded-full bg-amber-700 text-amber-50 px-1.5 py-0.5">
              🟡 {d.highlightCounts.warning}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center gap-2 mb-1">
        <span className="font-semibold text-sm truncate flex-1">{n.node_key}</span>
      </div>

      <div className="flex items-center gap-2">
        <span className={cn('w-2 h-2 rounded-full flex-shrink-0', STATUS_DOT[status])} />
        <span className="text-xs capitalize opacity-80">{n.status}</span>
        <span className="ml-auto text-[10px] opacity-60 font-mono">{n.scope}</span>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-slate-400 !w-2 !h-2" />
    </div>
  )
}

export default memo(PipelineNode)
