/** @file Browser entry point: mounts the app with its theme and error boundary. */

import { CssBaseline, ThemeProvider } from '@mui/material'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { theme } from './theme'

const root = document.getElementById('root')
if (!root) throw new Error('Root element not found')

createRoot(root).render(
    <StrictMode>
        <ErrorBoundary>
            <ThemeProvider theme={theme}>
                <CssBaseline />
                <BrowserRouter>
                    <App />
                </BrowserRouter>
            </ThemeProvider>
        </ErrorBoundary>
    </StrictMode>,
)
