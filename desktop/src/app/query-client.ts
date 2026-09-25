import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/platform/contract/envelope'

const MAX_ATTEMPTS = 2

/** A 429 that asked for a two-minute window must not be answered with a loop. */
const MAX_ACCEPTABLE_WAIT_SECONDS = 30

/** The token layer owns these; a retry here would only multiply refresh calls. */
const AUTH_CODES = new Set(['unauthorized', 'forbidden', 'insufficient_scope'])

/**
 * Retry is decided by the server's own `retryable` flag, never by the status
 * code: a 500 the backend marked non-retryable is a write whose outcome is
 * unknown, and resending it is how a duplicate order gets made.
 */
export function shouldRetry(error: unknown, attempt: number): boolean {
  if (!(error instanceof ApiError)) return false
  if (!error.retryable) return false
  if (AUTH_CODES.has(error.code)) return false
  if (error.retryAfterSeconds !== null && error.retryAfterSeconds > MAX_ACCEPTABLE_WAIT_SECONDS) return false

  return attempt < MAX_ATTEMPTS
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => shouldRetry(error, failureCount),
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      // Mutations are never resent by a client that cannot see the outcome.
      mutations: { retry: false },
    },
  })
}
