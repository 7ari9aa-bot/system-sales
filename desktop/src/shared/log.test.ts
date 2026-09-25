import { describe, expect, it, vi } from 'vitest'

import { createLogger, redact } from '@/shared/log'

const sink = () => vi.fn()

describe('redact', () => {
  it('drops anything credential-shaped by key name', () => {
    const out = redact({
      access_token: 'abc',
      refresh_token: 'abc',
      Authorization: 'Bearer abc',
      api_key: 'sk-abc',
      password: 'hunter2',
      client_secret: 'abc',
      cookie: 'session=abc',
    }) as Record<string, unknown>

    expect(Object.values(out).every((v) => v === '[redacted]')).toBe(true)
  })

  it('drops customer PII that must never reach a laptop log', () => {
    const out = redact({
      email: 'sara@example.com',
      mobile: '+201000000000',
      national_id: '29001011234567',
      iban: 'EG0000000000000000000000',
      card_number: '4111111111111111',
      name: 'سارة',
    }) as Record<string, unknown>

    expect(out['email']).toBe('[redacted]')
    expect(out['mobile']).toBe('[redacted]')
    expect(out['national_id']).toBe('[redacted]')
    expect(out['iban']).toBe('[redacted]')
    expect(out['card_number']).toBe('[redacted]')
    expect(out['name']).toBe('سارة')
  })

  it('redacts a JWT-looking string wherever it hides, including inside a message', () => {
    const out = redact({ detail: 'decode failed for eyJhbGciOi.eyJzdWIi.YS1zaWdu' }) as Record<string, string>

    expect(out['detail']).not.toContain('eyJ')
  })

  it('walks arrays and nested objects', () => {
    const out = redact({ rows: [{ token: 'a', id: 7 }], tags: ['x', 'authorization: y'] }) as {
      rows: Array<Record<string, unknown>>
      tags: string[]
    }

    expect(out.rows[0]?.['token']).toBe('[redacted]')
    expect(out.rows[0]?.['id']).toBe(7)
    expect(out.tags[1]).toBe('[redacted]')
  })

  it('keeps the fields support needs to trace a request', () => {
    const out = redact({ request_id: 'a1b2c3d4', code: 'rate_limited', total: '12.50' }) as Record<
      string,
      unknown
    >

    expect(out).toEqual({ request_id: 'a1b2c3d4', code: 'rate_limited', total: '12.50' })
  })

  it('truncates a long string instead of letting a payload balloon the log file', () => {
    const out = redact({ body: 'x'.repeat(5_000) }, { maxStringChars: 100 }) as Record<string, string>

    expect(out['body']).toHaveLength(100 + '…[truncated 4900 chars]'.length)
    expect(out['body']).toMatch(/\[truncated \d+ chars\]$/)
  })

  it('survives a circular structure by cutting at a depth limit', () => {
    const cyclic: Record<string, unknown> = { level: 1 }
    cyclic['self'] = cyclic

    expect(() => redact(cyclic)).not.toThrow()
    expect((redact(cyclic) as Record<string, unknown>)['self']).toBe('[max depth]')
  })
})

describe('createLogger', () => {
  it('drops records below the configured level', () => {
    const write = sink()
    const log = createLogger(write, { level: 'info', sink: 'test' })

    log.debug('cache warm', { rows: 12 })
    log.info('booted')

    expect(write).toHaveBeenCalledTimes(1)
    expect(write.mock.calls[0]?.[0]).toMatchObject({ level: 'info', message: 'booted', sink: 'test' })
  })

  it('redacts before the sink is ever called', () => {
    const write = sink()
    const log = createLogger(write, { level: 'debug', sink: 'test' })

    log.error('refresh failed', { refresh_token: 'rt-secret', code: 'invalid_grant' })

    const record = write.mock.calls[0]?.[0] as { fields: Record<string, unknown> }
    expect(record.fields['refresh_token']).toBe('[redacted]')
    expect(record.fields['code']).toBe('invalid_grant')
  })

  it('carries a request id through without ever reading it from a token', () => {
    const write = sink()
    const log = createLogger(write, { level: 'error', sink: 'test', requestId: 'req-42' })

    log.error('gateway 502', { status: 502 })

    expect(write.mock.calls[0]?.[0]).toMatchObject({ requestId: 'req-42', level: 'error' })
  })

  it('never throws out of a log call, whatever the payload', () => {
    const throwing = vi.fn(() => {
      throw new Error('sink down')
    })
    const log = createLogger(throwing, { level: 'info', sink: 'test' })

    expect(() => log.info('anything')).not.toThrow()
  })
})
