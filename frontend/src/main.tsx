import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AuthBootstrap from './components/AuthBootstrap.tsx'
import { ThemeProvider } from './lib/theme.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthBootstrap>
        <App />
      </AuthBootstrap>
    </ThemeProvider>
  </StrictMode>,
)
