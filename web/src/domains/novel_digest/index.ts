/**
 * novel_digest domain module (acceptance §5 frontend starting point).
 *
 * Registered via the plugin's web_manifest (`domains/novel_digest/index.ts`)
 * and loaded by `initDomains()` through Vite's glob import. Provides:
 * - ledger item columns (卷 / 字数, read from WorkItem.payload)
 * - a `/timeline` route placeholder (global timeline page; data wiring is M5+)
 * - a review detail tab pointing at the item's timeline slot
 *
 * Note: this file is intentionally `.ts` (the glob import in sdk/domain.ts
 * matches `domains/*​/index.ts` exactly), so components use createElement.
 */

import { createElement as h } from 'react'
import type { RouteObject } from 'react-router-dom'
import type { ColumnDef } from '@tanstack/react-table'

import type { DomainModule, WorkItem } from '@sdk/domain'

function TimelinePage(): React.ReactElement {
  return h(
    'div',
    { className: 'p-6 space-y-2' },
    h('h1', { className: 'text-xl font-semibold' }, '全局时间线'),
    h(
      'p',
      { className: 'text-sm text-muted-foreground' },
      '跨片累积的全局时间线将在此展示（数据接线属 M5+ 全流程范畴）。',
    ),
  )
}

function TimelineTab(): React.ReactElement | null {
  return h(
    'div',
    { className: 'p-4 text-sm text-muted-foreground' },
    '该工作项的时间线增量见 Evidence 的 timeline slot（json-table 视图）。',
  )
}

const itemColumns: ColumnDef<WorkItem>[] = [
  {
    id: 'volume',
    header: '卷',
    accessorFn: (item) => (item.payload?.volume as number | undefined) ?? '-',
  },
  {
    id: 'word_count',
    header: '字数',
    accessorFn: (item) => (item.payload?.word_count as number | undefined) ?? '-',
  },
]

const routes: RouteObject[] = [{ path: '/timeline', element: h(TimelinePage) }]

const module: DomainModule = {
  id: 'novel_digest',
  label: 'Novel Digest',
  routes,
  slots: {
    reviewDetailTabs: [{ id: 'timeline', label: '时间线', render: TimelineTab }],
  },
  itemColumns,
}

export default module
