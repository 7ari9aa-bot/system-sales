import type { BootState } from '@/app/boot-state'
import { message } from '@/shared/i18n'

export function BootScreen({ state }: { readonly state: BootState }) {
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

  return (
    <main className={blocked ? 'boot boot--blocked' : 'boot'}>
      <p className="boot__brand">{message('app.name')}</p>
      <p className="boot__state">{copy[state.status]}</p>
      {state.status === 'ok' ? (
        <>
          <p className="boot__addressLabel">{message('boot.address')}</p>
          <code className="boot__address">{state.apiBaseUrl}</code>
        </>
      ) : null}
    </main>
  )
}
