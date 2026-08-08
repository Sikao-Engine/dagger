import React from 'react'

export interface PageMeta {
  path: string
  label: string
  icon: string
  component: React.LazyExoticComponent<React.FC>
  hideFromNav?: boolean
}

export const PAGE_ROUTES: PageMeta[] = [
  {
    path: '/',
    label: '概览',
    icon: 'LayoutDashboard',
    component: React.lazy(() => import('@core/pages/overview')),
  },
  {
    path: '/runs',
    label: 'Runs',
    icon: 'GitBranch',
    component: React.lazy(() => import('@core/pages/runs')),
  },
  {
    path: '/runs/:runId',
    label: 'Run',
    icon: 'GitBranch',
    component: React.lazy(() => import('@core/pages/run-detail')),
    hideFromNav: true,
  },
  {
    path: '/runs/:runId/nodes/:nodeId',
    label: 'Node',
    icon: 'Box',
    component: React.lazy(() => import('@core/pages/node-detail')),
    hideFromNav: true,
  },
  {
    path: '/runs/:runId/state',
    label: 'State',
    icon: 'Database',
    component: React.lazy(() => import('@core/pages/state-browser')),
    hideFromNav: true,
  },
  {
    path: '/runs/:runId/items/:itemId/evidence',
    label: 'Evidence',
    icon: 'FileSearch',
    component: React.lazy(() => import('@core/pages/item-evidence')),
    hideFromNav: true,
  },
  {
    path: '/attempts/:attemptId',
    label: 'Attempt',
    icon: 'FileJson',
    component: React.lazy(() => import('@core/pages/attempt-detail')),
    hideFromNav: true,
  },
  {
    path: '/ledger',
    label: '台账',
    icon: 'ListChecks',
    component: React.lazy(() => import('@core/pages/ledger')),
  },
  {
    path: '/planner',
    label: '规划',
    icon: 'Target',
    component: React.lazy(() => import('@core/pages/planner')),
  },
  {
    path: '/templates',
    label: '模板',
    icon: 'Boxes',
    component: React.lazy(() => import('@core/pages/templates')),
  },
  {
    path: '/agents',
    label: '进程',
    icon: 'ServerCog',
    component: React.lazy(() => import('@core/pages/agents')),
  },
  {
    path: '/settings',
    label: '设置',
    icon: 'Settings',
    component: React.lazy(() => import('@core/pages/settings')),
  },
]

export const NAV_ROUTES = PAGE_ROUTES.filter((r) => !r.hideFromNav)
