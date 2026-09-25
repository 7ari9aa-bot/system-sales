import { z } from 'zod'

/**
 * The v2 error envelope, and the only place the desktop reads it.
 *
 * Server side, `error` carries exactly four keys (backend/core/errors.py:144)
 * and `detail` / `tier` / `retry_after` are added beside it (backend/core/main.py:310
 * and backend/core/middleware.py:241). Anything else — a proxy page, a bare
 * `{"detail": ...}`, a half-written body — is not an error we understand, and
 * an action we do not understand is never retried.
 */
const envelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string(),
    retryable: z.boolean().optional(),
    request_id: z.string().min(1).nullable().optional(),
  }),
  detail: z.unknown().optional(),
  tier: z.string().optional(),
  retry_after: z.number().int().nonnegative().optional(),
})

export interface ApiErrorInit {
  readonly code: string
  readonly message: string
  readonly retryable: boolean
  readonly requestId: string | null
  readonly status: number
  readonly tier?: string | null
  readonly retryAfterSeconds?: number | null
  readonly detail?: unknown
}

export class ApiError extends Error {
  override readonly name = 'ApiError'

  readonly code: string
  readonly retryable: boolean
  readonly requestId: string | null
  readonly status: number
  readonly tier: string | null
  readonly retryAfterSeconds: number | null
  readonly detail: unknown

  constructor(init: ApiErrorInit) {
    super(init.message)
    this.code = init.code
    this.retryable = init.retryable
    this.requestId = init.requestId
    this.status = init.status
    this.tier = init.tier ?? null
    this.retryAfterSeconds = init.retryAfterSeconds ?? null
    this.detail = init.detail
  }

  toJSON(): Record<string, unknown> {
    const json: Record<string, unknown> = {
      code: this.code,
      message: this.message,
      retryable: this.retryable,
      requestId: this.requestId,
      status: this.status,
    }
    if (this.tier !== null) json['tier'] = this.tier
    if (this.retryAfterSeconds !== null) json['retryAfterSeconds'] = this.retryAfterSeconds
    if (this.detail !== undefined) json['detail'] = this.detail

    return json
  }
}

export interface EnvelopeContext {
  readonly status: number
  readonly headerRequestId?: string | null
}

export function parseErrorEnvelope(input: unknown, context: EnvelopeContext): ApiError {
  const parsed = envelopeSchema.safeParse(input)

  if (!parsed.success) return unknownError(context)

  const { error, detail, tier, retry_after: retryAfter } = parsed.data

  return new ApiError({
    code: error.code,
    message: error.message,
    retryable: error.retryable ?? false,
    requestId: error.request_id ?? context.headerRequestId ?? null,
    status: context.status,
    ...(tier === undefined ? {} : { tier }),
    ...(retryAfter === undefined ? {} : { retryAfterSeconds: retryAfter }),
    ...(detail === undefined ? {} : { detail }),
  })
}

/**
 * The body was not the envelope. Synthesising a retryable error from the status
 * code would let a 502 behind a proxy resend a POST whose outcome nobody knows.
 */
function unknownError(context: EnvelopeContext): ApiError {
  return new ApiError({
    code: 'unknown',
    message: `HTTP ${context.status}`,
    retryable: false,
    requestId: context.headerRequestId ?? null,
    status: context.status,
  })
}
