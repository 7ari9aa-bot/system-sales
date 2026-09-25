import { describe, expect, it } from 'vitest'

import { ApiError, parseErrorEnvelope } from '@/platform/contract/envelope'

/**
 * The one envelope the API emits, plus its additive fields (verified against
 * backend/app/core/errors.py::build_error_envelope and docs §5 of the mission).
 */
describe('parseErrorEnvelope', () => {
  it('reads code, message, retryable and request_id out of the v2 envelope', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'validation_failed', message: 'اسم العميل مطلوب', retryable: false, request_id: 'a1b2c3d4' } },
      { status: 422 },
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error?.code).toBe('validation_failed')
    expect(error?.message).toBe('اسم العميل مطلوب')
    expect(error?.retryable).toBe(false)
    expect(error?.requestId).toBe('a1b2c3d4')
    expect(error?.status).toBe(422)
  })

  it('defaults retryable to false when the server omits it', () => {
    const error = parseErrorEnvelope({ error: { code: 'boom', message: 'x' } }, { status: 500 })

    expect(error?.retryable).toBe(false)
  })

  it('takes the request id from the header when the body has none', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'rate_limited', message: 'slow down', retryable: true } },
      { status: 429, headerRequestId: 'req-from-header' },
    )

    expect(error?.requestId).toBe('req-from-header')
  })

  it('prefers the body request id over the header', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'conflict', message: 'x', request_id: 'body-id' } },
      { status: 409, headerRequestId: 'header-id' },
    )

    expect(error?.requestId).toBe('body-id')
  })

  it('keeps the 422 detail array so a form can be marked up field by field', () => {
    const detail = [
      { loc: ['body', 'mobile'], msg: 'string too short', type: 'string_too_short' },
    ]
    const error = parseErrorEnvelope(
      { error: { code: 'validation_failed', message: 'x', retryable: false }, detail },
      { status: 422 },
    )

    expect(error?.detail).toEqual(detail)
  })

  it('reads tier and retry_after off a 429', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'rate_limited', message: 'x', retryable: true }, tier: 'trial', retry_after: 30 },
      { status: 429 },
    )

    expect(error?.tier).toBe('trial')
    expect(error?.retryAfterSeconds).toBe(30)
  })

  it('never retries an unknown outcome: a non-envelope body yields retryable false', () => {
    const error = parseErrorEnvelope('<html>502 Bad Gateway</html>', { status: 502 })

    expect(error?.code).toBe('unknown')
    expect(error?.retryable).toBe(false)
  })

  it('treats a lying retryable value as a non-envelope body instead of guessing', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'timeout', message: 'x', retryable: 'yes please' } },
      { status: 504 },
    )

    expect(error?.code).toBe('unknown')
    expect(error?.retryable).toBe(false)
  })

  it('keeps retryable false on a 500 when the server says so — status never overrides the envelope', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'internal', message: 'x', retryable: false } },
      { status: 500 },
    )

    expect(error?.retryable).toBe(false)
  })

  it('refuses an empty code, because branching happens on it', () => {
    const error = parseErrorEnvelope(
      { error: { code: '', message: 'x', retryable: false } },
      { status: 500 },
    )

    expect(error?.code).toBe('unknown')
  })

  it('carries the machine fields on the Error instance so catch sites never parse again', () => {
    const error = parseErrorEnvelope(
      { error: { code: 'version_conflict', message: 'x', retryable: false, request_id: 'r1' } },
      { status: 409 },
    )

    expect(() => {
      throw error
    }).toThrowError(ApiError)
    expect(error?.toJSON()).toEqual({
      code: 'version_conflict',
      message: 'x',
      retryable: false,
      requestId: 'r1',
      status: 409,
    })
  })
})
