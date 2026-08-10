/**
 * React hooks for Dagger's two SSE channels.
 *
 * `useRunStream(runId)` — run-level DaggerEvents (node started/succeeded/failed,
 * run started/completed). Backed by `/api/v1/runs/{id}/events/stream`.
 *   1. REST snapshot via `getPipeline(runId)` (node states + counts)
 *   2. SSE live updates with `Last-Event-ID` resume
 *   3. Auto-reconnect on drop
 *
 * `useAttemptStream(attemptId)` — Agent transcript events.
 *   1. REST history via `GET /attempts/{id}/transcript` (jsonl array)
 *   2. SSE tail via `GET /attempts/{id}/stream` (only if attempt is running)
 *   3. Parsed into `TranscriptMessage[]` with text/reasoning/tool/step parts
 *
 * Both hooks share a drop-oldest backpressure model: if the consumer can't keep
 * up, oldest events are dropped (live feed semantics — newest wins).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { getApiUrl, getStreamUrl } from './config'
import { parseSSEData, readSSEChunks, type ParsedEvent } from './sse-parser'

import type { PipelineOut, EventOut } from './client'

// ── useRunStream ─────────────────────────────────────────────────────────────

export interface RunStreamState {
  pipeline: PipelineOut | null
  events: EventOut[]
  connected: boolean
  error: string | null
  lastSeq: number
}

const RECONNECT_DELAY_MS = 3000

export function useRunStream(
  runId: string | null,
  options: { onEvent?: (ev: EventOut) => void } = {},
): RunStreamState & { disconnect: () => void; reconnect: () => void } {
  const [state, setState] = useState<RunStreamState>({
    pipeline: null,
    events: [],
    connected: false,
    error: null,
    lastSeq: 0,
  })
  const abortRef = useRef<AbortController | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSeqRef = useRef(0)
  const onEventRef = useRef(options.onEvent)
  onEventRef.current = options.onEvent

  const connect = useCallback(async () => {
    if (!runId) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    // Phase 1: REST snapshot
    try {
      const r = await fetch(getApiUrl(`/runs/${encodeURIComponent(runId)}/pipeline`))
      if (ctrl.signal.aborted) return
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: string }
        setState((s) => ({ ...s, error: body.detail ?? `HTTP ${r.status}` }))
        return
      }
      const pipeline = (await r.json()) as PipelineOut
      if (ctrl.signal.aborted) return
      setState((s) => ({ ...s, pipeline, error: null }))
    } catch (err) {
      if (ctrl.signal.aborted) return
      setState((s) => ({ ...s, error: err instanceof Error ? err.message : String(err) }))
      scheduleReconnect()
      return
    }

    // Phase 2: SSE live
    const url = getStreamUrl(`/runs/${encodeURIComponent(runId)}/events/stream`)
    try {
      const resp = await fetch(url, {
        signal: ctrl.signal,
        headers: {
          Accept: 'text/event-stream',
          'Last-Event-ID': String(lastSeqRef.current),
        },
      })
      if (ctrl.signal.aborted) return
      if (!resp.ok || !resp.body) {
        const body = (await resp.json().catch(() => ({}))) as { detail?: string }
        setState((s) => ({ ...s, error: body.detail ?? `Stream HTTP ${resp.status}` }))
        return
      }
      setState((s) => ({ ...s, connected: true, error: null }))

      for await (const dataStr of readSSEChunks(resp.body, ctrl.signal)) {
        if (ctrl.signal.aborted) return
        let ev: EventOut
        try {
          ev = JSON.parse(dataStr) as EventOut
        } catch {
          continue
        }
        if (ev.id !== undefined && ev.id > lastSeqRef.current) {
          lastSeqRef.current = ev.id
        }
        setState((s) => ({
          ...s,
          events: appendBounded(s.events, ev, 500),
          lastSeq: lastSeqRef.current,
        }))
        onEventRef.current?.(ev)
      }
      // Stream closed naturally
      setState((s) => ({ ...s, connected: false }))
      scheduleReconnect()
    } catch (err) {
      if (ctrl.signal.aborted) return
      if (err instanceof DOMException && err.name === 'AbortError') return
      setState((s) => ({
        ...s,
        connected: false,
        error: err instanceof Error ? err.message : String(err),
      }))
      scheduleReconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimer.current) return
    reconnectTimer.current = setTimeout(() => {
      reconnectTimer.current = null
      void connect()
    }, RECONNECT_DELAY_MS)
  }, [connect])

  useEffect(() => {
    void connect()
    return () => {
      abortRef.current?.abort()
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
    }
  }, [connect])

  const disconnect = useCallback(() => {
    abortRef.current?.abort()
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
    }
    setState((s) => ({ ...s, connected: false }))
  }, [])

  return { ...state, disconnect, reconnect: connect }
}

// ── useAttemptStream ────────────────────────────────────────────────────────

export interface TranscriptPart {
  type: 'text' | 'reasoning' | 'tool' | 'step-start' | 'step-finish'
  text?: string
  tool?: string
  callID?: string
  state?: {
    status?: string
    title?: string
    input?: unknown
    output?: unknown
  }
}

export interface TranscriptMessage {
  info: {
    id?: string
    role: string
    agent?: string
    modelID?: string
    cost?: number
    tokens?: Record<string, unknown>
    time?: Record<string, unknown>
  }
  parts: TranscriptPart[]
}

export interface AttemptStreamState {
  historyLoaded: boolean
  connected: boolean
  finished: boolean
  error: string | null
  messages: TranscriptMessage[]
  events: ParsedEvent[]
  sessionId: string
}

export function useAttemptStream(
  attemptId: string | null,
  enabled = true,
): AttemptStreamState & { disconnect: () => void; reconnect: () => void } {
  const [state, setState] = useState<AttemptStreamState>({
    historyLoaded: false,
    connected: false,
    finished: false,
    error: null,
    messages: [],
    events: [],
    sessionId: '',
  })
  const abortRef = useRef<AbortController | null>(null)
  const accRef = useRef<{
    historyMessages: TranscriptMessage[]
    liveMessages: TranscriptMessage[]
    events: ParsedEvent[]
    currentAssistantMsg: TranscriptMessage | null
  }>({ historyMessages: [], liveMessages: [], events: [], currentAssistantMsg: null })

  const connect = useCallback(async () => {
    if (!attemptId || !enabled) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    accRef.current = {
      historyMessages: [],
      liveMessages: [],
      events: [],
      currentAssistantMsg: null,
    }
    setState({
      historyLoaded: false,
      connected: false,
      finished: false,
      error: null,
      messages: [],
      events: [],
      sessionId: '',
    })

    // Phase 1: transcript history
    try {
      const r = await fetch(
        getApiUrl(`/attempts/${encodeURIComponent(attemptId)}/transcript`),
        { signal: ctrl.signal },
      )
      if (ctrl.signal.aborted) return
      if (!r.ok) {
        const body = (await r.json().catch(() => ({}))) as { detail?: string }
        setState((s) => ({ ...s, error: body.detail ?? `HTTP ${r.status}`, historyLoaded: true }))
      } else {
        const lines = (await r.json()) as Array<Record<string, unknown>>
        const historyMsgs = lines.map(rawToTranscriptMessage)
        accRef.current.historyMessages = historyMsgs
        setState((s) => ({
          ...s,
          historyLoaded: true,
          messages: historyMsgs,
          error: null,
        }))
      }
    } catch (err) {
      if (ctrl.signal.aborted) return
      setState((s) => ({
        ...s,
        historyLoaded: true,
        error: `History: ${err instanceof Error ? err.message : String(err)}`,
      }))
    }

    // Phase 2: SSE tail (works whether attempt is running or not — server closes
    // gracefully after replay if not running)
    const url = getStreamUrl(`/attempts/${encodeURIComponent(attemptId)}/stream`)
    try {
      const resp = await fetch(url, {
        signal: ctrl.signal,
        headers: { Accept: 'text/event-stream' },
      })
      if (ctrl.signal.aborted) return
      if (!resp.ok || !resp.body) {
        const body = (await resp.json().catch(() => ({}))) as { detail?: string }
        // 404 = no active stream; history is still shown
        if (resp.status !== 404) {
          setState((s) => ({ ...s, error: body.detail ?? `Stream HTTP ${resp.status}` }))
        }
        setState((s) => ({ ...s, finished: true }))
        return
      }
      setState((s) => ({ ...s, connected: true, error: null }))

      for await (const dataStr of readSSEChunks(resp.body, ctrl.signal)) {
        if (ctrl.signal.aborted) return
        const parsed = parseSSEData(dataStr)
        if (parsed.type === 'skip') continue

        accRef.current.events.push(parsed)
        applyEvent(accRef.current, parsed)

        const allMessages = [...accRef.current.historyMessages, ...accRef.current.liveMessages]
        setState((s) => ({
          ...s,
          connected: true,
          finished:
            parsed.finished &&
            (parsed.type === 'session-idle' || parsed.type === 'step-finish'),
          error: parsed.type === 'stream-error' ? parsed.text : null,
          messages: allMessages,
          events: [...accRef.current.events],
        }))
      }
      // Stream ended naturally
      setState((s) => ({ ...s, connected: false, finished: true }))
    } catch (err) {
      if (ctrl.signal.aborted) return
      if (err instanceof DOMException && err.name === 'AbortError') return
      setState((s) => ({
        ...s,
        connected: false,
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }, [attemptId, enabled])

  useEffect(() => {
    void connect()
    return () => {
      abortRef.current?.abort()
    }
  }, [connect])

  const disconnect = useCallback(() => {
    abortRef.current?.abort()
    setState((s) => ({ ...s, connected: false }))
  }, [])

  return { ...state, disconnect, reconnect: connect }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function appendBounded<T>(arr: readonly T[], item: T, max: number): T[] {
  if (arr.length < max) return [...arr, item]
  // Drop oldest
  return [...arr.slice(arr.length - max + 1), item]
}

function rawToTranscriptMessage(raw: Record<string, unknown>): TranscriptMessage {
  const info = (raw.info as Record<string, unknown>) || raw || {}
  const parts = (raw.parts as Array<Record<string, unknown>>) || []
  return {
    info: {
      id: info.id != null ? String(info.id) : undefined,
      role: String(info.role ?? 'assistant'),
      agent: info.agent as string | undefined,
      modelID: info.modelID as string | undefined,
      cost: info.cost as number | undefined,
      tokens: info.tokens as Record<string, unknown> | undefined,
      time: info.time as Record<string, unknown> | undefined,
    },
    parts: parts.map((p) => ({
      type: String(p.type ?? 'unknown') as TranscriptPart['type'],
      text: p.text as string | undefined,
      tool: p.tool as string | undefined,
      callID: p.callID as string | undefined,
      state: p.state as TranscriptPart['state'],
    })),
  }
}

type Accumulator = {
  historyMessages: TranscriptMessage[]
  liveMessages: TranscriptMessage[]
  events: ParsedEvent[]
  currentAssistantMsg: TranscriptMessage | null
}

function ensureAssistantMsg(acc: Accumulator): TranscriptMessage {
  if (!acc.currentAssistantMsg) {
    acc.currentAssistantMsg = {
      info: { role: 'assistant', time: { created: Date.now() } },
      parts: [],
    }
    acc.liveMessages.push(acc.currentAssistantMsg)
  }
  return acc.currentAssistantMsg
}

function applyEvent(acc: Accumulator, evt: ParsedEvent): void {
  switch (evt.type) {
    case 'text': {
      const msg = ensureAssistantMsg(acc)
      const lastPart = msg.parts[msg.parts.length - 1]
      if (lastPart?.type === 'text') {
        if (evt.delta) {
          lastPart.text = (lastPart.text ?? '') + evt.delta
        } else if (evt.text) {
          lastPart.text = evt.text
        }
      } else {
        msg.parts.push({ type: 'text', text: evt.delta || evt.text || '' })
      }
      break
    }
    case 'reasoning': {
      const msg = ensureAssistantMsg(acc)
      const lastPart = msg.parts[msg.parts.length - 1]
      if (lastPart?.type === 'reasoning') {
        if (evt.delta) {
          lastPart.text = (lastPart.text ?? '') + evt.delta
        } else if (evt.text) {
          lastPart.text = evt.text
        }
      } else {
        msg.parts.push({ type: 'reasoning', text: evt.delta || evt.text || '' })
      }
      break
    }
    case 'tool': {
      const msg = ensureAssistantMsg(acc)
      const existingIdx = msg.parts.findIndex(
        (p) => p.type === 'tool' && p.tool === evt.toolName && p.state?.status !== 'completed',
      )
      const toolPart: TranscriptPart = {
        type: 'tool',
        tool: evt.toolName,
        state: {
          status: evt.toolStatus,
          title: evt.toolTitle,
          input: evt.toolInput ? tryParse(evt.toolInput) : undefined,
          output: evt.toolOutput ? tryParse(evt.toolOutput) : undefined,
        },
      }
      if (existingIdx >= 0) {
        msg.parts[existingIdx] = toolPart
      } else {
        msg.parts.push(toolPart)
      }
      break
    }
    case 'step-start': {
      const msg = ensureAssistantMsg(acc)
      msg.parts.push({ type: 'step-start' })
      break
    }
    case 'step-finish': {
      const msg = ensureAssistantMsg(acc)
      msg.parts.push({ type: 'step-finish', text: evt.text })
      if (evt.finished) {
        acc.currentAssistantMsg = null
      }
      break
    }
    case 'session-idle': {
      acc.currentAssistantMsg = null
      break
    }
  }
}

function tryParse(s: string): unknown {
  try {
    return JSON.parse(s)
  } catch {
    return s
  }
}
