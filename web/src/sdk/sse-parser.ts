/**
 * SSE event parser for opencode-compatible streaming.
 * Ported from cube-claw dashboard `lib/sse/parser.ts` — protocol normalization
 * is shared between the agentcli backend and loom_agent's opencode-http.
 *
 * Loom's LoomEvent (run/node lifecycle) arrives via the run-level stream as a
 * JSON `data:` line whose shape mirrors `events.to_dict()` (seq/type/data/...).
 * This parser only normalizes Attempt Agent events (transcript lines).
 */

export type ParsedEventType =
  | 'text'
  | 'reasoning'
  | 'tool'
  | 'permission'
  | 'step-start'
  | 'step-finish'
  | 'session-idle'
  | 'stream-error'
  | 'skip'

export interface ParsedEvent {
  type: ParsedEventType
  text: string
  delta: string
  toolName: string
  toolStatus: string
  toolTitle: string
  toolInput: string
  toolOutput: string
  finished: boolean
  raw: Record<string, unknown>
}

function emptyParsed(type: ParsedEventType): ParsedEvent {
  return {
    type,
    text: '',
    delta: '',
    toolName: '',
    toolStatus: '',
    toolTitle: '',
    toolInput: '',
    toolOutput: '',
    finished: false,
    raw: {},
  }
}

export function parseSSEData(dataStr: string): ParsedEvent {
  if (!dataStr) return emptyParsed('skip')

  let data: Record<string, unknown>
  try {
    data = JSON.parse(dataStr) as Record<string, unknown>
  } catch {
    return emptyParsed('skip')
  }

  const eventType = (data?.type as string) ?? ''

  if (eventType === 'stream.error') {
    const p = emptyParsed('stream-error')
    p.text = (data.error as string) ?? 'Unknown stream error'
    p.raw = data
    return p
  }

  if (eventType === 'server.connected' || eventType === 'server.heartbeat') {
    return emptyParsed('skip')
  }

  if (eventType === 'message.part.updated') return parsePartUpdated(data)
  if (eventType === 'message.part.delta') return parsePartDelta(data)
  if (eventType === 'session.idle') {
    const p = emptyParsed('session-idle')
    p.finished = true
    p.raw = data
    return p
  }
  if (eventType === 'session.status') {
    const status = (data as { properties?: { status?: unknown } }).properties?.status
    const statusType = typeof status === 'object' && status ? (status as { type?: string }).type : ''
    if (statusType === 'idle') {
      const p = emptyParsed('session-idle')
      p.finished = true
      p.raw = data
      return p
    }
    return emptyParsed('skip')
  }
  if (eventType === 'session.permission' || eventType === 'permission' || eventType === 'permission.asked') {
    const p = emptyParsed('permission')
    p.raw = data
    return p
  }

  return emptyParsed('skip')
}

type Part = {
  type?: string
  text?: string
  tool?: string
  state?: {
    status?: string
    title?: string
    input?: unknown
    output?: unknown
  }
  reason?: string
}

function parsePartUpdated(data: Record<string, unknown>): ParsedEvent {
  const props = (data.properties ?? {}) as { delta?: string; part?: Part }
  const part = props.part ?? {}
  const delta: string = props.delta ?? ''
  const partType: string = part.type ?? ''

  if (partType === 'text') {
    const p = emptyParsed('text')
    p.delta = delta
    p.text = part.text ?? ''
    p.raw = data
    return p
  }
  if (partType === 'reasoning') {
    const p = emptyParsed('reasoning')
    p.delta = delta
    p.text = part.text ?? ''
    p.raw = data
    return p
  }
  if (partType === 'tool') {
    const state = part.state ?? {}
    const toolName: string = part.tool ?? 'unknown'
    const status: string = state.status ?? ''
    const title: string = state.title ?? toolName
    let input = ''
    if (state.input && typeof state.input === 'object') {
      input = JSON.stringify(state.input, null, 2)
    } else if (typeof state.input === 'string') {
      input = state.input
    }
    let output = ''
    if (state.output && typeof state.output === 'object') {
      output = JSON.stringify(state.output, null, 2)
    } else if (typeof state.output === 'string') {
      output = state.output
    }

    if (
      (toolName === 'permission' || toolName === 'question' || toolName === 'ask') &&
      (status === 'pending' || status === 'running')
    ) {
      const p = emptyParsed('permission')
      p.toolName = toolName
      p.toolStatus = status
      p.toolTitle = title
      p.raw = data
      return p
    }

    const p = emptyParsed('tool')
    p.toolName = toolName
    p.toolStatus = status
    p.toolTitle = title
    p.toolInput = input
    p.toolOutput = output
    p.raw = data
    return p
  }
  if (partType === 'step-start') {
    const p = emptyParsed('step-start')
    p.raw = data
    return p
  }
  if (partType === 'step-finish') {
    const reason: string = part.reason ?? ''
    const p = emptyParsed('step-finish')
    p.text = reason
    p.finished = reason !== 'tool-calls' && reason !== 'tool_calls'
    p.raw = data
    return p
  }

  return emptyParsed('skip')
}

function parsePartDelta(data: Record<string, unknown>): ParsedEvent {
  const props = (data.properties ?? {}) as { delta?: string; field?: string }
  const delta: string = props.delta ?? ''
  const field: string = props.field ?? ''
  if (delta && (field === 'text' || field === 'reasoning')) {
    const p = emptyParsed(field === 'reasoning' ? 'reasoning' : 'text')
    p.delta = delta
    p.raw = data
    return p
  }
  return emptyParsed('skip')
}

/** Shared SSE line reader: yields `data:` payloads from a ReadableStream. */
export async function* readSSEChunks(
  stream: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<string> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      if (signal.aborted) return
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        let dataStr = ''
        for (const line of block.split('\n')) {
          if (line.startsWith('data:')) {
            dataStr += line.slice(5).trimStart()
          }
        }
        if (dataStr) yield dataStr
      }
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* already released */
    }
  }
}
