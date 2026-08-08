import { create } from 'zustand'
import type { DomainOut } from '@sdk/client'
import { listDomains } from '@sdk/client'

interface ServerState {
  health: 'ok' | 'down' | 'checking'
  canRun: boolean
  domains: DomainOut[]
  lastFetch: number
  checkHealth: () => Promise<void>
  loadDomains: () => Promise<void>
}

export const useServerStore = create<ServerState>((set) => ({
  health: 'checking',
  canRun: true,
  domains: [],
  lastFetch: 0,
  checkHealth: async () => {
    try {
      await listDomains()
      set({ health: 'ok' })
    } catch {
      set({ health: 'down' })
    }
  },
  loadDomains: async () => {
    try {
      const domains = await listDomains()
      set({ domains, lastFetch: Date.now(), health: 'ok' })
    } catch {
      set({ health: 'down' })
    }
  },
}))
