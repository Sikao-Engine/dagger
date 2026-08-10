import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  GitBranch,
  FileJson,
  FileSearch,
  ListChecks,
  Target,
  Boxes,
  Settings,
  ServerCog,
  Database,
} from 'lucide-react'
import { NAV_ROUTES } from '@core/config/routes'
import { cn } from '@lib/utils'
import { useServerStore } from '@core/store/server'

const iconMap: Record<string, ReactNode> = {
  LayoutDashboard: <LayoutDashboard size={18} />,
  GitBranch: <GitBranch size={18} />,
  FileJson: <FileJson size={18} />,
  FileSearch: <FileSearch size={18} />,
  ListChecks: <ListChecks size={18} />,
  Target: <Target size={18} />,
  Boxes: <Boxes size={18} />,
  Settings: <Settings size={18} />,
  ServerCog: <ServerCog size={18} />,
  Database: <Database size={18} />,
}

interface AppShellProps {
  children: ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const location = useLocation()
  const health = useServerStore((s) => s.health)

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
      <aside className="w-14 lg:w-52 flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="h-14 flex items-center px-3 border-b border-slate-800">
          <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center font-bold text-white text-xs">
            DD
          </div>
          <span className="ml-2 font-bold text-sm text-slate-200 hidden lg:block">DivDag</span>
        </div>

        <nav className="flex-1 py-3 px-2 space-y-1">
          {NAV_ROUTES.map((route) => {
            const isActive =
              route.path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(route.path)
            return (
              <Link
                key={route.path}
                to={route.path}
                className={cn(
                  'flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-all',
                  isActive
                    ? 'bg-blue-900/40 text-blue-400'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
                )}
              >
                {iconMap[route.icon] ?? <LayoutDashboard size={18} />}
                <span className="hidden lg:block">{route.label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="px-3 py-3 border-t border-slate-800">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                health === 'ok' && 'bg-emerald-400',
                health === 'down' && 'bg-red-400',
                health === 'checking' && 'bg-amber-400 animate-pulse',
              )}
            />
            <span className="text-slate-500 hidden lg:block capitalize">{health}</span>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  )
}
