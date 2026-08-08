import { describe, expect, it, beforeEach } from 'vitest'
import {
  registerDomain,
  getDomain,
  listRegisteredDomains,
  aggregateSlot,
  type DomainModule,
} from '@sdk/domain'

function makeModule(id: string, extra?: Partial<DomainModule>): DomainModule {
  return { id, label: id, ...extra }
}

describe('domain registry', () => {
  beforeEach(() => {
    // Reset registry by re-importing fresh module is hard; instead we just
    // register distinct ids per test.
  })

  it('register + get + list', () => {
    const m = makeModule(`test-a-${Math.random()}`)
    registerDomain(m)
    expect(getDomain(m.id)).toBe(m)
    expect(listRegisteredDomains().map((d) => d.id)).toContain(m.id)
  })

  it('aggregateSlot collects from all domains', () => {
    const id1 = `test-slot-1-${Math.random()}`
    const id2 = `test-slot-2-${Math.random()}`
    const Slot1 = () => null
    const Slot2 = () => null
    registerDomain(makeModule(id1, { slots: { runHeaderExtra: Slot1 } }))
    registerDomain(makeModule(id2, { slots: { runHeaderExtra: Slot2 } }))
    const slots = aggregateSlot('runHeaderExtra')
    expect(slots).toHaveLength(2)
    expect(slots).toContain(Slot1)
    expect(slots).toContain(Slot2)
  })

  it('aggregateSlot returns empty for unregistered slot', () => {
    expect(aggregateSlot('nodeDetailExtra')).toHaveLength(0)
  })
})
