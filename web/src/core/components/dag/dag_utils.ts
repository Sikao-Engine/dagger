/**
 * DAG canvas helpers — ported from cube-claw dashboard `dag/dag_utils.ts`,
 * with the hardcoded `NODE_TYPE_ICON` table removed (node_type is a free-form
 * string registered by domain plugins; we render it as text, not a fixed emoji).
 *
 * `layoutNodes` does a layered topological layout: each node at depth = max
 * (parent depths) + 1. Parallel-ready nodes stack vertically per layer.
 */

import type { PipelineNode } from '@sdk/client'

export type NodeStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'waiting'
  | 'skipped'
  | 'blocked'

export const STATUS_COLOR: Record<NodeStatus, string> = {
  pending: 'bg-slate-700 border-slate-500 text-slate-300',
  running: 'bg-blue-900/60 border-blue-400 text-blue-200',
  success: 'bg-emerald-900/60 border-emerald-400 text-emerald-200',
  failed: 'bg-red-900/60 border-red-400 text-red-200',
  waiting: 'bg-amber-900/60 border-amber-400 text-amber-200',
  skipped: 'bg-slate-800 border-slate-600 text-slate-500',
  blocked: 'bg-orange-950/60 border-orange-500 text-orange-200',
}

export const STATUS_DOT: Record<NodeStatus, string> = {
  pending: 'bg-slate-500',
  running: 'bg-blue-400 animate-pulse',
  success: 'bg-emerald-400',
  failed: 'bg-red-400',
  waiting: 'bg-amber-400 animate-pulse',
  skipped: 'bg-slate-600',
  blocked: 'bg-orange-400',
}

export function asNodeStatus(s: string): NodeStatus {
  if (s in STATUS_COLOR) return s as NodeStatus
  return 'pending'
}

export interface LayoutInput {
  id: string
  dependencies: readonly string[]
}

export function layoutNodes(
  nodeDefs: readonly LayoutInput[],
): Record<string, { x: number; y: number }> {
  const levels: Record<string, number> = {}
  const resolved = new Set<string>()
  const allIds = nodeDefs.map((n) => n.id)

  function getLevel(id: string): number {
    if (levels[id] !== undefined) return levels[id]
    const node = nodeDefs.find((n) => n.id === id)
    if (!node || node.dependencies.length === 0) {
      levels[id] = 0
      return 0
    }
    const parentLevels = node.dependencies
      .filter((d) => allIds.includes(d))
      .map((d) => getLevel(d))
    levels[id] = parentLevels.length ? Math.max(...parentLevels) + 1 : 0
    return levels[id]
  }
  for (const id of allIds) {
    if (!resolved.has(id)) {
      getLevel(id)
      resolved.add(id)
    }
  }

  const byLevel: Record<number, string[]> = {}
  for (const [id, lvl] of Object.entries(levels)) {
    const level = Number(lvl)
    if (!byLevel[level]) byLevel[level] = []
    byLevel[level].push(id)
  }

  const positions: Record<string, { x: number; y: number }> = {}
  const NODE_W = 220
  const NODE_H = 90
  const GAP_X = 60
  const GAP_Y = 40

  for (const [lvl, ids] of Object.entries(byLevel)) {
    const level = Number(lvl)
    ids.forEach((id, idx) => {
      positions[id] = {
        x: level * (NODE_W + GAP_X),
        y: idx * (NODE_H + GAP_Y),
      }
    })
  }

  return positions
}

export function statusFromNode(n: PipelineNode): NodeStatus {
  return asNodeStatus(n.status)
}
