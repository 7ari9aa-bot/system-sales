import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/app/App'
import { applyDocumentLocale, pickLocale } from '@/app/document'
import { ErrorBoundary } from '@/app/error-boundary'
import { createQueryClient } from '@/app/query-client'
import { resolvePlatform } from '@/platform'
import { createLogger } from '@/shared/log'

import '@/styles/app.css'

const container = document.getElementById('root')

if (!container) throw new Error('index.html lost the #root element')

const locale = pickLocale(navigator.language)
applyDocumentLocale(locale)

const platform = await resolvePlatform()
const logger = createLogger(
  (record) => {
    platform.log.write(record)
  },
  { level: import.meta.env.DEV ? 'debug' : 'info', sink: 'ui' },
)

// Mounted once, above everything, so a failure inside the shell still has a
// screen to land on and a request id to hand to support.
createRoot(container).render(
  <StrictMode>
    <ErrorBoundary
      onFatal={(info) => {
        logger.error('render failed', { code: info.code, request_id: info.requestId })
      }}
    >
      <QueryClientProvider client={createQueryClient()}>
        <App platform={platform} />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
