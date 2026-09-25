import { describe, expect, it } from 'vitest'

import { ApiError } from '@/platform/contract/envelope'
import { createQueryClient, shouldRetry } from '@/app/query-client'

const err = (over: Partial<ConstructorParameters<typeof ApiError>[0]> = {}) =>
  new ApiError({
    code: 'network_unreachable',
    message: 'شبكة',
    retryable: true,
    requestId: 'r1',
    status: 0,
    ...over,
  })

describe('shouldRetry', () => {
  it('never retries an error the transport could not classify', () => {
    expect(shouldRetry(new TypeError('boom'), 0)).toBe(false)
  })

  it('never retries what the server marked non-retryable, whatever the status', () => {
    expect(shouldRetry(err({ code: 'validation_failed', retryable: false, status: 500 }), 0)).toBe(false)
  })

  it('retries a retryable error twice, then stops', () => {
    expect(shouldRetry(err(), 0)).toBe(true)
    expect(shouldRetry(err(), 1)).toBe(true)
    expect(shouldRetry(err(), 2)).toBe(false)
  })

  it('leaves an unauthorized read to the token layer', () => {
    expect(shouldRetry(err({ code: 'unauthorized', retryable: true, status: 401 }), 0)).toBe(false)
  })

  it('does not hammer a 429 that asked for a long window', () => {
    expect(shouldRetry(err({ code: 'rate_limited', status: 429, retryAfterSeconds: 120 }), 0)).toBe(false)
    expect(shouldRetry(err({ code: 'rate_limited', status: 429, retryAfterSeconds: 5 }), 0)).toBe(true)
  })
})

describe('createQueryClient', () => {
  it('never retries a mutation — an unknown outcome means ask a human, not resend', () => {
    const options = createQueryClient().getDefaultOptions()

    expect(options.mutations?.retry).toBe(false)
  })

  it('wires queries to the same retry rule the unit tests pin', () => {
    const retry = createQueryClient().getDefaultOptions().queries?.retry as (n: number, e: unknown) => boolean

    expect(retry(0, err())).toBe(true)
    expect(retry(0, err({ code: 'forbidden', retryable: false }))).toBe(false)
  })

  it('does not refetch on focus, because a laptop with seven windows is a request storm', () => {
    expect(createQueryClient().getDefaultOptions().queries?.refetchOnWindowFocus).toBe(false)
  })
})
