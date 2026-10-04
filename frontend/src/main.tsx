import { StrictMode, type ErrorInfo } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Surface every React error with its component stack in the console: uncaught ones unmount
// the tree, caught ones are handled by an error boundary, recoverable ones React retried.
function logReactError(kind: string) {
  return (error: unknown, info: ErrorInfo) => {
    console.error(`[react ${kind}]`, error, info.componentStack)
  }
}

createRoot(document.getElementById('root')!, {
  onUncaughtError: logReactError('uncaught'),
  onCaughtError: logReactError('caught'),
  onRecoverableError: logReactError('recoverable'),
}).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
