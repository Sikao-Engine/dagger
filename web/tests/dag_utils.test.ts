import { describe, expect, it } from 'vitest'
import { layoutNodes, asNodeStatus } from '@core/components/dag/dag_utils'

describe('layoutNodes', () => {
  it('empty input returns empty positions', () => {
    expect(layoutNodes([])).toEqual({})
  })

  it('single root at (0,0)', () => {
    const p = layoutNodes([{ id: 'a', dependencies: [] }])
    expect(p.a).toEqual({ x: 0, y: 0 })
  })

  it('linear chain increments level', () => {
    const p = layoutNodes([
      { id: 'a', dependencies: [] },
      { id: 'b', dependencies: ['a'] },
      { id: 'c', dependencies: ['b'] },
    ])
    expect(p.a.x).toBe(0)
    expect(p.b.x).toBe(280)
    expect(p.c.x).toBe(560)
  })

  it('parallel siblings stack vertically same x', () => {
    const p = layoutNodes([
      { id: 'a', dependencies: [] },
      { id: 'b', dependencies: [] },
      { id: 'c', dependencies: [] },
    ])
    expect(p.a.x).toBe(p.b.x)
    expect(p.b.x).toBe(p.c.x)
    expect(p.a.y).toBe(0)
    expect(p.b.y).toBe(130)
    expect(p.c.y).toBe(260)
  })

  it('diamond: shared parent same level', () => {
    const p = layoutNodes([
      { id: 'a', dependencies: [] },
      { id: 'b', dependencies: ['a'] },
      { id: 'c', dependencies: ['a'] },
      { id: 'd', dependencies: ['b', 'c'] },
    ])
    expect(p.a.x).toBe(0)
    expect(p.b.x).toBe(p.c.x)
    expect(p.d.x).toBeGreaterThan(p.b.x)
  })

  it('ignores dangling dependency (not in node list)', () => {
    const p = layoutNodes([{ id: 'a', dependencies: ['ghost'] }])
    expect(p.a).toEqual({ x: 0, y: 0 })
  })
})

describe('asNodeStatus', () => {
  it('known status passthrough', () => {
    expect(asNodeStatus('success')).toBe('success')
    expect(asNodeStatus('running')).toBe('running')
  })

  it('unknown status falls back to pending', () => {
    expect(asNodeStatus('weird')).toBe('pending')
    expect(asNodeStatus('')).toBe('pending')
  })
})
