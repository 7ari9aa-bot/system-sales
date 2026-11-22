import { useState, type FC, type FormEvent } from 'react'
import type { AuthSession, Platform } from '@/platform'

export const LoginView: FC<{
  readonly platform: Platform
  readonly onAuthenticated: (session: AuthSession) => void
  readonly onConfigureServer?: () => void
}> = ({ platform, onAuthenticated, onConfigureServer }) => {
  const [subdomain, setSubdomain] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = (e: FormEvent): void => {
    e.preventDefault()
    if (!email.trim() || !password.trim()) {
      setError('يرجى إدخال البريد الإلكتروني وكلمة المرور')
      return
    }

    setIsLoading(true)
    setError(null)

    void platform.auth
      .login({
        subdomain: subdomain.trim() || undefined,
        email: email.trim(),
        password,
      })
      .then((session) => {
        onAuthenticated(session)
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : 'فشل تسجيل الدخول، يرجى التحقق من البيانات'
        setError(msg)
      })
      .finally(() => {
        setIsLoading(false)
      })
  }

  return (
    <div className="boot" dir="rtl">
      <div className="boot__card" style={{ maxWidth: '420px', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>🛒</div>
          <h1 className="boot__title" style={{ fontSize: '1.5rem', margin: 0 }}>
            فهرس FIHRIST
          </h1>
          <p style={{ color: 'var(--fh-ink-muted)', fontSize: '0.85rem', marginTop: '0.25rem' }}>
            تسجيل الدخول إلى محطة العمل ونقطة البيع
          </p>
        </div>

        {error && (
          <div
            style={{
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid #ef4444',
              color: '#ef4444',
              padding: '0.75rem',
              borderRadius: '6px',
              fontSize: '0.85rem',
              marginBottom: '1rem',
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label
              htmlFor="subdomain"
              style={{ display: 'block', fontSize: '0.85rem', color: 'var(--fh-ink)', marginBottom: '0.35rem' }}
            >
              اسم نطاق المتجر (Subdomain)
            </label>
            <input
              id="subdomain"
              type="text"
              className="pos-search-input"
              placeholder="مثال: my-store (اختياري)"
              value={subdomain}
              onChange={(e) => setSubdomain(e.target.value)}
              disabled={isLoading}
              style={{ width: '100%', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <label
              htmlFor="email"
              style={{ display: 'block', fontSize: '0.85rem', color: 'var(--fh-ink)', marginBottom: '0.35rem' }}
            >
              البريد الإلكتروني <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              id="email"
              type="email"
              required
              className="pos-search-input"
              placeholder="cashier@store.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
              style={{ width: '100%', boxSizing: 'border-box', direction: 'ltr', textAlign: 'right' }}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              style={{ display: 'block', fontSize: '0.85rem', color: 'var(--fh-ink)', marginBottom: '0.35rem' }}
            >
              كلمة المرور <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input
              id="password"
              type="password"
              required
              className="pos-search-input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              style={{ width: '100%', boxSizing: 'border-box', direction: 'ltr', textAlign: 'right' }}
            />
          </div>

          <button
            type="submit"
            className="boot__button"
            disabled={isLoading}
            style={{
              width: '100%',
              justifyContent: 'center',
              padding: '0.75rem',
              fontSize: '1rem',
              fontWeight: 600,
              marginTop: '0.5rem',
            }}
          >
            {isLoading ? 'جاري التحقق...' : 'دخول إلى المحطة'}
          </button>
        </form>

        {onConfigureServer && (
          <div style={{ textAlign: 'center', marginTop: '1.5rem', borderTop: '1px solid var(--fh-line)', paddingTop: '1rem' }}>
            <button
              type="button"
              onClick={onConfigureServer}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--fh-ink-muted)',
                fontSize: '0.8rem',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              ⚙️ تغيير عنوان خادم المنظومة (Server URL)
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
