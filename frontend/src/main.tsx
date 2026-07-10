import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import RunBuilder from './pages/RunBuilder'
import Runs from './pages/Runs'
import RunLive from './pages/RunLive'
import RunResults from './pages/RunResults'
import Datasets from './pages/Datasets'
import Prompts from './pages/Prompts'
import Catalog from './pages/Catalog'
import Settings from './pages/Settings'
import NotFound from './pages/NotFound'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RunBuilderProvider } from './context/RunBuilderContext'
import './styles.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <RunBuilder /> },
      { path: 'runs', element: <Runs /> },
      { path: 'runs/:id', element: <RunLive /> },
      { path: 'runs/:id/results', element: <RunResults /> },
      { path: 'datasets', element: <Datasets /> },
      { path: 'prompts', element: <Prompts /> },
      { path: 'catalog', element: <Catalog /> },
      { path: 'settings', element: <Settings /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RunBuilderProvider>
          <RouterProvider router={router} />
        </RunBuilderProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
