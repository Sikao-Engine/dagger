import { describe, expect, it } from 'vitest'
import { parseSSEData } from '@sdk/sse-parser'

describe('parseSSEData', () => {
  it('empty string returns skip', () => {
    expect(parseSSEData('').type).toBe('skip')
  })

  it('non-json returns skip', () => {
    expect(parseSSEData('not json').type).toBe('skip')
  })

  it('server.connected returns skip', () => {
    expect(parseSSEData('{"type":"server.connected"}').type).toBe('skip')
  })

  it('stream.error returns stream-error with message', () => {
    const p = parseSSEData('{"type":"stream.error","error":"boom"}')
    expect(p.type).toBe('stream-error')
    expect(p.text).toBe('boom')
  })

  it('session.idle returns session-idle with finished=true', () => {
    const p = parseSSEData('{"type":"session.idle"}')
    expect(p.type).toBe('session-idle')
    expect(p.finished).toBe(true)
  })

  it('message.part.updated with text part', () => {
    const p = parseSSEData(
      '{"type":"message.part.updated","properties":{"part":{"type":"text","text":"hello"},"delta":"lo"}}',
    )
    expect(p.type).toBe('text')
    expect(p.text).toBe('hello')
    expect(p.delta).toBe('lo')
  })

  it('message.part.updated with tool part', () => {
    const p = parseSSEData(
      '{"type":"message.part.updated","properties":{"part":{"type":"tool","tool":"edit","state":{"status":"running","title":"Edit file"}}}}',
    )
    expect(p.type).toBe('tool')
    expect(p.toolName).toBe('edit')
    expect(p.toolStatus).toBe('running')
    expect(p.toolTitle).toBe('Edit file')
  })

  it('message.part.delta with text field', () => {
    const p = parseSSEData(
      '{"type":"message.part.delta","properties":{"delta":"hi","field":"text"}}',
    )
    expect(p.type).toBe('text')
    expect(p.delta).toBe('hi')
  })

  it('message.part.delta with reasoning field', () => {
    const p = parseSSEData(
      '{"type":"message.part.delta","properties":{"delta":"think","field":"reasoning"}}',
    )
    expect(p.type).toBe('reasoning')
    expect(p.delta).toBe('think')
  })

  it('permission tool pending', () => {
    const p = parseSSEData(
      '{"type":"message.part.updated","properties":{"part":{"type":"tool","tool":"permission","state":{"status":"pending","title":"Allow?"}}}}',
    )
    expect(p.type).toBe('permission')
    expect(p.toolName).toBe('permission')
  })

  it('unknown type returns skip', () => {
    expect(parseSSEData('{"type":"unknown.event"}').type).toBe('skip')
  })
})
