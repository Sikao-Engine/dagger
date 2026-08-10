/**
 * Typed API client. Wraps fetch against the Dagger backend (Litestar).
 *
 * All paths are relative to `/api/v1` (see config.ts). Errors are normalized
 * into `ApiError` with a `detail` string pulled from Litestar's error body
 * (`{"detail": "...", "code": "..."}`) so callers can `err.message` uniformly.
 */

import { getApiUrl } from './config'

import type { components } from './types.gen'

type Schemas = components['schemas']
export type AttemptOut = Schemas['AttemptOut']
export type ArtifactRefOut = Schemas['ArtifactRefOut']
export type ArtifactSlotOut = Schemas['ArtifactSlotOut']
export type ArtifactSpecOut = Schemas['ArtifactSpecOut']
export type DomainOut = Schemas['DomainOut']
export type EventOut = Schemas['EventOut']
export type ExecutorOut = Schemas['ExecutorOut']
export type ItemArtifactSlotOut = Schemas['ItemArtifactSlotOut']
export type ItemArtifactsOut = Schemas['ItemArtifactsOut']
export type LedgerItemOut = Schemas['LedgerItemOut']
export type LedgerRefreshResult = Schemas['LedgerRefreshResult']
export type ManagedProcessOut = Schemas['ManagedProcessOut']
export type MilestoneOut = Schemas['MilestoneOut']
export type NodeRunOut = Schemas['NodeRunOut']
export type PipelineNode = Schemas['PipelineNode']
export type PipelineOut = Schemas['PipelineOut']
export type PlanOut = Schemas['PlanOut']
export type PlanSnapshot = Schemas['PlanSnapshot']
export type RunCreate = Schemas['RunCreate']
export type RunOut = Schemas['RunOut']
export type RunResult = Schemas['RunResult']
export type ShardOut = Schemas['ShardOut']
export type StateIndexEntry = Schemas['StateIndexEntry']
export type StateObjectOut = Schemas['StateObjectOut']
export type TemplateOut = Schemas['TemplateOut']

/** ErrorOut isn't auto-generated as a schema (only inline in error responses). */
export interface ErrorOut {
  detail: string
  code?: string
}

export class ApiError extends Error {
  status: number
  code: string
  constructor(status: number, detail: string, code: string = 'error') {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function parseError(r: Response): Promise<ApiError> {
  let detail = `HTTP ${r.status}`
  let code = 'error'
  try {
    const body = (await r.json()) as Partial<ErrorOut> & { detail?: string }
    if (typeof body.detail === 'string') detail = body.detail
    if (typeof body.code === 'string') code = body.code
  } catch {
    try {
      const text = await r.text()
      if (text) detail = text.slice(0, 500)
    } catch {
      /* keep default */
    }
  }
  return new ApiError(r.status, detail, code)
}

/** Generic JSON GET. */
export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(getApiUrl(path), {
    headers: { Accept: 'application/json' },
  })
  if (!r.ok) throw await parseError(r)
  return (await r.json()) as T
}

/** Generic JSON POST. `body` is sent as JSON; pass `null` for empty body. */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(getApiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? '{}' : JSON.stringify(body),
  })
  if (!r.ok) throw await parseError(r)
  return (await r.json()) as T
}

// ── Catalog ────────────────────────────────────────────────────────────────

export const listDomains = () => apiGet<DomainOut[]>('/domains')
export const listExecutors = () => apiGet<ExecutorOut[]>('/executors')
export const listTemplates = (domain?: string) =>
  apiGet<TemplateOut[]>(`/templates${domain ? `?domain=${encodeURIComponent(domain)}` : ''}`)

// ── Runs ───────────────────────────────────────────────────────────────────

export const createRun = (body: RunCreate) => apiPost<RunResult>('/runs', body)
export const listRuns = () => apiGet<RunOut[]>('/runs')
export const getRun = (runId: string) => apiGet<RunOut>(`/runs/${encodeURIComponent(runId)}`)
export const getPipeline = (runId: string) =>
  apiGet<PipelineOut>(`/runs/${encodeURIComponent(runId)}/pipeline`)
export const listRunEvents = (runId: string) =>
  apiGet<EventOut[]>(`/runs/${encodeURIComponent(runId)}/events`)

// ── Nodes & Attempts ────────────────────────────────────────────────────────

export const getNodeRun = (nodeRunId: string) =>
  apiGet<NodeRunOut>(`/nodes/${encodeURIComponent(nodeRunId)}`)
export const listAttempts = (nodeRunId: string) =>
  apiGet<AttemptOut[]>(`/nodes/${encodeURIComponent(nodeRunId)}/attempts`)

/** Node lifecycle actions. These endpoints are defined in §13 but may not yet be
 *  implemented on the server — callers should handle ApiError(404) gracefully. */
export const retryNode = (nodeRunId: string) =>
  apiPost<NodeRunOut>(`/nodes/${encodeURIComponent(nodeRunId)}/retry`)
export const skipNode = (nodeRunId: string) =>
  apiPost<NodeRunOut>(`/nodes/${encodeURIComponent(nodeRunId)}/skip`)
export const blockNode = (nodeRunId: string, reason?: string) =>
  apiPost<NodeRunOut>(`/nodes/${encodeURIComponent(nodeRunId)}/block`, { reason })
export const forceSuccessNode = (nodeRunId: string, reason?: string) =>
  apiPost<NodeRunOut>(`/nodes/${encodeURIComponent(nodeRunId)}/force-success`, { reason })
export const resumeRunFromNode = (runId: string, nodeId: string) =>
  apiPost<PipelineOut>(`/runs/${encodeURIComponent(runId)}/resume-from/${encodeURIComponent(nodeId)}`)

// ── State ───────────────────────────────────────────────────────────────────

export const getStateIndex = (runId: string) =>
  apiGet<StateIndexEntry[]>(`/runs/${encodeURIComponent(runId)}/state`)

export interface StateObjectQuery {
  layer: string
  node_run_id?: string
  shard_id?: string
  attempt?: number
  slot?: string
}

export function getStateObject(runId: string, q: StateObjectQuery): Promise<StateObjectOut> {
  const params = new URLSearchParams()
  params.set('layer', q.layer)
  if (q.node_run_id) params.set('node_run_id', q.node_run_id)
  if (q.shard_id) params.set('shard_id', q.shard_id)
  if (q.attempt !== undefined) params.set('attempt', String(q.attempt))
  if (q.slot) params.set('slot', q.slot)
  return apiGet<StateObjectOut>(
    `/runs/${encodeURIComponent(runId)}/state/object?${params.toString()}`,
  )
}

// ── Item artifacts (T7.1 review surface) ───────────────────────────────────

/** Per-item artifacts grouped by the domain's ArtifactSpec slots. */
export function getItemArtifacts(runId: string, itemId: string): Promise<ItemArtifactsOut> {
  return apiGet<ItemArtifactsOut>(
    `/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/artifacts`,
  )
}

/** Raw bytes of one artifact slot. Used by EvidenceViewer renderers. */
export async function getItemArtifactBytes(
  runId: string,
  itemId: string,
  slot: string,
): Promise<{ bytes: Uint8Array; sha256: string; size: number }> {
  const r = await fetch(
    getApiUrl(
      `/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/artifacts/${encodeURIComponent(slot)}`,
    ),
    { headers: { Accept: 'application/octet-stream' } },
  )
  if (!r.ok) throw await parseError(r)
  const buf = await r.arrayBuffer()
  return {
    bytes: new Uint8Array(buf),
    sha256: r.headers.get('X-Dagger-Sha256') ?? '',
    size: Number(r.headers.get('Content-Length') ?? buf.byteLength),
  }
}

// ── Ledger & Planning ──────────────────────────────────────────────────────

export interface LedgerQuery {
  status?: string
  limit?: number
  offset?: number
}

export function listLedger(projectId: string, q: LedgerQuery = {}): Promise<LedgerItemOut[]> {
  const params = new URLSearchParams()
  if (q.status) params.set('status', q.status)
  if (q.limit !== undefined) params.set('limit', String(q.limit))
  if (q.offset !== undefined) params.set('offset', String(q.offset))
  const qs = params.toString()
  return apiGet<LedgerItemOut[]>(
    `/projects/${encodeURIComponent(projectId)}/ledger${qs ? `?${qs}` : ''}`,
  )
}

export const refreshLedger = (projectId: string, body: { items_dir?: string; run_id?: string }) =>
  apiPost<LedgerRefreshResult>(`/projects/${encodeURIComponent(projectId)}/ledger/refresh`, body)

export const getPlan = (projectId: string) =>
  apiGet<PlanSnapshot>(`/projects/${encodeURIComponent(projectId)}/plan`)

// ── Agent processes ─────────────────────────────────────────────────────────

export const listProcesses = () => apiGet<ManagedProcessOut[]>('/agents/processes')
export const getProcessesStatus = () =>
  apiGet<{ status: string }>('/agents/processes/status')
export const stopProcess = (key: string) =>
  apiPost<{ key: string; message: string }>(`/agents/processes/${encodeURIComponent(key)}/stop`)
export const stopAllProcesses = () =>
  apiPost<{ stopped: number }>('/agents/processes/stop-all')
