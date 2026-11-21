import { useState } from 'react'

import type { BootState } from '@/app/boot-state'
import { message } from '@/shared/i18n'

export function BootScreen({
  state,
  onSave,
}: {
  readonly state: BootState
  readonly onSave?: (url: string) => void
}) {
  const [urlInput, setUrlInput] = useState('')

  if (state.status === 'checking') {
    return (
      <main className="boot">
        <p className="boot__brand">{message('app.name')}</p>
        <p className="boot__checking" role="status">
          {message('boot.checking')}
        </p>
      </main>
    )
  }

  const blocked = state.status !== 'ok'
  const copy: Record<'missing' | 'invalid' | 'insecure' | 'ok', string> = {
    missing: message('boot.unconfigured'),
    invalid: message('boot.invalid'),
    insecure: message('boot.insecure'),
    ok: message('boot.ready'),
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (urlInput.trim() && onSave) {
      onSave(urlInput.trim())
    }
  }

  return (
    <main className={blocked ? 'boot boot--blocked' : 'boot'}>
      <p className="boot__brand">{message('app.name')}</p>
      <p className="boot__state">{copy[state.status]}</p>
      {state.status === 'ok' ? (
        <>
          <p className="boot__addressLabel">{message('boot.address')}</p>
          <code className="boot__address">{state.apiBaseUrl}</code>
        </>
      ) : onSave ? (
        <form className="boot__form" onSubmit={handleSubmit}>
          <label htmlFor="server-url-input" className="boot__addressLabel">
            {message('boot.configureTitle')}
          </label>
          <input
            id="server-url-input"
            className="boot__input"
            type="text"
            placeholder={message('boot.serverUrlPlaceholder')}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
          />
          <button type="submit" className="boot__button">
            {message('boot.saveAndConnect')}
          </button>
        </form>
      ) : null}
    </main>
  )
}
