import { create } from 'zustand'
import type { PipelineOut } from '@sdk/client'

interface PipelineState {
  pipeline: PipelineOut | null
  selectedNodeId: string | null
  setPipeline: (p: PipelineOut | null) => void
  selectNode: (id: string | null) => void
}

export const usePipelineStore = create<PipelineState>((set) => ({
  pipeline: null,
  selectedNodeId: null,
  setPipeline: (p) => set({ pipeline: p }),
  selectNode: (id) => set({ selectedNodeId: id }),
}))
