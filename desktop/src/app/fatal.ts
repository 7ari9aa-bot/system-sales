import { ApiError } from '@/platform/contract/envelope'

export interface FatalInfo {
  readonly code: string
  readonly requestId: string | null
}

/**
 * A component that threw is not necessarily a failed request. Whatever came out,
 * the user sees a code they can quote and a request id support can look up —
 * never the exception text, which is written for engineers.
 */
export function toFatalInfo(error: unknown): FatalInfo {
  if (error instanceof ApiError) return { code: error.code, requestId: error.requestId }

  return { code: 'unknown', requestId: null }
}
