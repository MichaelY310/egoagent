import { createRoot } from 'react-dom/client'
import App from './App'
import WorkbenchErrorBoundary from './components/WorkbenchErrorBoundary'
import './index.css'
import './workbench-theme-overrides.css'

createRoot(document.getElementById('root')!).render(
  <WorkbenchErrorBoundary>
    <App />
  </WorkbenchErrorBoundary>,
)
