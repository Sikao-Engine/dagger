import { useEffect, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { useServerStore } from '@core/store/server'
import { PAGE_ROUTES } from '@core/config/routes'
import { initDomains } from '@sdk/domain'
import AppShell from '@core/components/app-shell'

const AppRoutes = () => {
  const checkHealth = useServerStore((s) => s.checkHealth)
  const loadDomains = useServerStore((s) => s.loadDomains)

  useEffect(() => {
    void checkHealth()
    void loadDomains()
    void initDomains()
    const timer = setInterval(() => void checkHealth(), 30_000)
    return () => clearInterval(timer)
  }, [checkHealth, loadDomains])

  return (
    <AppShell>
      <Routes>
        {PAGE_ROUTES.map((route) => {
          const Component = route.component
          return <Route key={route.path} path={route.path} element={<Component />} />
        })}
      </Routes>
    </AppShell>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-screen bg-slate-950 text-slate-400">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p>Loading Dagger...</p>
            </div>
          </div>
        }
      >
        <AppRoutes />
      </Suspense>
    </BrowserRouter>
  )
}

export default App
