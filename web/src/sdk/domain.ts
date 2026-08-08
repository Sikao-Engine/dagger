/**
 * Domain module registry. A domain plugin declares the UI surface it wants to
 * extend (extra routes, slot components, table columns, artifact views).
 *
 * At startup `initDomains()` fetches `GET /domains`, reads each domain's
 * `web_manifest`, and dynamically `import()`s the matching bundle under
 * `web/src/domains/<id>/`. Uninstalled domains are zero-cost (never imported).
 *
 * Mirrors §11.2 of the architecture design.
 */

import type { ComponentType, FC } from 'react'
import type { RouteObject } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'

import { listDomains, type AttemptOut, type RunOut, type NodeRunOut, type LedgerItemOut } from './client'

export interface WorkItem {
  id: string
  seq: number
  title: string
  payload?: Record<string, unknown>
  labels?: string[]
}

export interface ReviewTab {
  id: string
  label: string
  render: FC<{ itemId: string; runId: string }>
}

export interface ArtifactRef {
  slot: string
  path: string
  label?: string
  meta?: Record<string, unknown>
}

export interface DomainModule {
  id: string
  label: string
  routes?: RouteObject[]
  slots?: {
    runHeaderExtra?: FC<{ run: RunOut }>
    nodeDetailExtra?: FC<{ node: NodeRunOut }>
    itemRowExtra?: FC<{ item: WorkItem }>
    attemptDetailExtra?: FC<{ attempt: AttemptOut }>
    reviewDetailTabs?: ReviewTab[]
    plannerPanel?: FC<{ ledger: LedgerItemOut[]; projectId: string }>
  }
  itemColumns?: ColumnDef<WorkItem>[]
  artifactViews?: Record<string, ComponentType<{ artifact: ArtifactRef }>>
}

interface RegisteredDomain {
  module: DomainModule
  manifest: Record<string, unknown>
}

const registry = new Map<string, RegisteredDomain>()

export function registerDomain(module: DomainModule): void {
  registry.set(module.id, { module, manifest: {} })
}

export function getDomain(id: string): DomainModule | undefined {
  return registry.get(id)?.module
}

export function listRegisteredDomains(): DomainModule[] {
  return Array.from(registry.values()).map((d) => d.module)
}

export function getDomainRoutes(): RouteObject[] {
  return listRegisteredDomains().flatMap((m) => m.routes ?? [])
}

/** Hook: aggregate slot components across all installed domains. */
export function aggregateSlot<K extends keyof NonNullable<DomainModule['slots']>>(
  slotName: K,
): NonNullable<NonNullable<DomainModule['slots']>[K]>[] {
  const out: NonNullable<NonNullable<DomainModule['slots']>[K]>[] = []
  for (const { module } of registry.values()) {
    const slot = module.slots?.[slotName]
    if (slot) {
      // slot is a single component (FC) or array (reviewDetailTabs)
      if (Array.isArray(slot)) {
        out.push(...(slot as unknown[] as NonNullable<NonNullable<DomainModule['slots']>[K]>[]))
      } else {
        out.push(slot as NonNullable<NonNullable<DomainModule['slots']>[K]>)
      }
    }
  }
  return out
}

/** Fetch domain manifests from server and dynamically import installed ones. */
export async function initDomains(): Promise<DomainModule[]> {
  let manifests: Array<{ id: string; web_manifest?: Record<string, unknown> }>
  try {
    manifests = await listDomains()
  } catch (err) {
    // Server not running during dev: log and proceed with whatever was statically imported.
    console.warn('[domain] failed to fetch /domains:', err instanceof Error ? err.message : err)
  return listRegisteredDomains()
}

  // Use Vite's glob import to discover domain bundles. Each domain module under
  // src/domains/<id>/index.ts default-exports a DomainModule.
  const glob = import.meta.glob<{ default: DomainModule }>('./../domains/*/index.ts')
  for (const m of manifests) {
    const key = `./../domains/${m.id}/index.ts`
    const importer = glob[key]
    if (!importer) continue
    try {
      const mod = await importer()
      const module = mod.default
      const existing = registry.get(module.id)
      if (existing) {
        // Already statically registered; just update manifest
        existing.manifest = m.web_manifest ?? {}
      } else {
        registry.set(module.id, { module, manifest: m.web_manifest ?? {} })
      }
    } catch (err) {
      console.error(`[domain] failed to load domain '${m.id}':`, err)
    }
  }
  return listRegisteredDomains()
}
