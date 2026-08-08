import { useMemo, useState, useCallback, useEffect } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  applyNodeChanges,
  type Node,
  type Edge,
  type NodeChange,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { PipelineOut } from '@sdk/client'
import { layoutNodes, asNodeStatus } from './dag_utils'
import PipelineNode, { type PipelineNodeData } from './PipelineNode'

const nodeTypes = { pipelineNode: PipelineNode }

interface Props {
  pipeline: PipelineOut
  selectedNodeId: string | null
  onSelectNode: (id: string | null) => void
}

export default function DAGCanvas({ pipeline, selectedNodeId, onSelectNode }: Props) {
  const nodes = useMemo(() => pipeline.nodes ?? [], [pipeline.nodes])
  const nodeKey = nodes.map((n) => n.id).join(',')

  const positions = useMemo(
    () =>
      layoutNodes(
        nodes.map((n) => ({ id: n.id, dependencies: n.dependencies ?? [] })),
      ),
    [nodeKey],
  )

  const canonicalNodes: Node[] = useMemo(() => {
    return nodes.map((n) => {
      const pos = positions[n.id] ?? { x: 0, y: 0 }
      const nodeData: PipelineNodeData = {
        node: n,
        selected: selectedNodeId === n.id,
        onClick: () => onSelectNode(selectedNodeId === n.id ? null : n.id),
      }
      return {
        id: n.id,
        type: 'pipelineNode',
        position: pos,
        data: nodeData as unknown as Record<string, unknown>,
      }
    })
  }, [nodes, selectedNodeId, positions, onSelectNode])

  const [nodesState, setNodesState] = useState<Node[]>(canonicalNodes)

  // Sync external pipeline changes into ReactFlow's controlled node state while
  // preserving user-dragged positions (xyflow needs a stable node array reference).
  useEffect(() => {
    setNodesState((prev) => {
      const prevMap = new Map(prev.map((n) => [n.id, n]))
      return canonicalNodes.map((canonical) => {
        const existing = prevMap.get(canonical.id)
        if (existing) {
          return { ...existing, data: canonical.data, position: canonical.position }
        }
        return canonical
      })
    })
  }, [canonicalNodes])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodesState((nds) => applyNodeChanges(changes, nds))
  }, [])

  const edges: Edge[] = useMemo(() => {
    const result: Edge[] = []
    const byId = new Map(nodes.map((n) => [n.id, n]))
    for (const n of nodes) {
      for (const dep of n.dependencies ?? []) {
        if (!byId.has(dep)) continue
        result.push({
          id: `${dep}->${n.id}`,
          source: dep,
          target: n.id,
          markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
          style: { stroke: '#475569', strokeWidth: 1.5 },
          animated: asNodeStatus(n.status) === 'running',
        })
      }
    }
    return result
  }, [nodes])

  return (
    <div
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      className="bg-slate-950"
    >
      <ReactFlow
        style={{ width: '100%', height: '100%' }}
        nodes={nodesState}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        colorMode="dark"
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1e293b" gap={20} />
        <Controls className="!bg-slate-800 !border-slate-600 !text-slate-200" />
        <MiniMap
          nodeColor={(n) => {
            const data = n.data as unknown as PipelineNodeData
            const status = asNodeStatus(data.node.status)
            switch (status) {
              case 'success':
                return '#10b981'
              case 'failed':
                return '#ef4444'
              case 'running':
                return '#3b82f6'
              case 'waiting':
                return '#f59e0b'
              case 'blocked':
                return '#f97316'
              default:
                return '#475569'
            }
          }}
          className="!bg-slate-900 !border-slate-700"
        />
      </ReactFlow>
    </div>
  )
}
