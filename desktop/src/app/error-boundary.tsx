import { Component, Fragment, type ErrorInfo, type ReactNode } from 'react'

import { toFatalInfo, type FatalInfo } from '@/app/fatal'
import { message } from '@/shared/i18n'

export interface ErrorBoundaryProps {
  readonly children: ReactNode
  readonly onFatal: (info: FatalInfo) => void
}

interface ErrorBoundaryState {
  readonly fatal: FatalInfo | null
  readonly attempt: number
}

/**
 * One boundary at the root. Phase 4 puts a second one around each feature region
 * so a broken analytics card cannot take the inbox down with it.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { fatal: null, attempt: 0 }

  static getDerivedStateFromError(error: unknown): Pick<ErrorBoundaryState, 'fatal'> {
    return { fatal: toFatalInfo(error) }
  }

  override componentDidCatch(error: unknown, _info: ErrorInfo): void {
    this.props.onFatal(toFatalInfo(error))
  }

  private readonly retry = (): void => {
    this.setState((current) => ({ fatal: null, attempt: current.attempt + 1 }))
  }

  override render(): ReactNode {
    const { fatal, attempt } = this.state
    if (fatal) return <FatalPanel info={fatal} onRetry={this.retry} />

    return (
      <Fragment key={attempt}>{this.props.children}</Fragment>
    )
  }
}

interface FatalPanelProps {
  readonly info: FatalInfo
  readonly onRetry: () => void
}

function FatalPanel({ info, onRetry }: FatalPanelProps) {
  return (
    <section className="fatal" dir="rtl" role="region" aria-label={message('fatal.aria')} data-code={info.code}>
      <p className="fatal__brand">{message('app.name')}</p>
      <h1 className="fatal__title">{message('fatal.title')}</h1>
      <p className="fatal__body">{message('fatal.body')}</p>

      <dl className="fatal__meta">
        <div className="fatal__metaRow">
          <dt>{message('fatal.code')}</dt>
          <dd>{info.code}</dd>
        </div>
        {info.requestId === null ? null : (
          <div className="fatal__metaRow">
            <dt>{message('fatal.request')}</dt>
            <dd className="fatal__requestId">{info.requestId}</dd>
          </div>
        )}
      </dl>

      <button type="button" className="fatal__retry" onClick={onRetry}>
        {message('fatal.retry')}
      </button>
    </section>
  )
}
