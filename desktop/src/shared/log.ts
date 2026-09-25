export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogRecord {
  readonly level: LogLevel
  readonly message: string
  readonly fields: Record<string, unknown>
  readonly requestId: string | null
  readonly sink: string
  readonly ts: string
}

export type LogSink = (record: LogRecord) => void

export interface LoggerOptions {
  readonly level: LogLevel
  readonly sink: string
  readonly requestId?: string | null
}

export interface RedactOptions {
  readonly maxStringChars?: number
  readonly maxDepth?: number
}

export interface Logger {
  readonly debug: (message: string, fields?: Record<string, unknown>) => void
  readonly info: (message: string, fields?: Record<string, unknown>) => void
  readonly warn: (message: string, fields?: Record<string, unknown>) => void
  readonly error: (message: string, fields?: Record<string, unknown>) => void
}

const ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 }

/**
 * A laptop log is a copy of production data outside the perimeter. Everything
 * that is a credential, or is customer PII the API only redacts because the
 * actor lacked `pii:read`, is dropped before it reaches a file — and the
 * fields support needs to trace a request (`request_id`, `code`) survive.
 */
const SECRET_KEYS =
  /^(?:authorization|proxyauthorization|cookie|setcookie|.*(?:token|secret|password|passwd|credential|apikey|signature|jwt|bearer|privatekey|clientsecret))$/

const PII_KEYS =
  /^(?:.*(?:email|mobile|phone|nationalid|taxid|taxnumber|iban|bic|cardnumber|cardexp|cvv|ssn|routingnumber|address|passportid))$/

const CREDENTIAL_IN_VALUE =
  /(?:bearer\s+[a-z0-9._-]+|authorization\s*:|x-api-key\s*:|eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.)/i

const DEFAULT_MAX_STRING_CHARS = 400
const DEFAULT_MAX_DEPTH = 6

export function redact(value: unknown, options: RedactOptions = {}): unknown {
  const maxStringChars = options.maxStringChars ?? DEFAULT_MAX_STRING_CHARS
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH

  return walk(value, new WeakSet<object>(), maxStringChars, maxDepth)
}

export function createLogger(sink: LogSink, options: LoggerOptions): Logger {
  const write = (level: LogLevel, message: string, fields?: Record<string, unknown>): void => {
    if (ORDER[level] < ORDER[options.level]) return

    try {
      sink({
        level,
        message: String(message),
        fields: redact(fields ?? {}, { maxDepth: DEFAULT_MAX_DEPTH }) as Record<string, unknown>,
        requestId: options.requestId ?? null,
        sink: options.sink,
        ts: new Date().toISOString(),
      })
    } catch {
      // A log call that throws would take a screen down with it. Swallowing is
      // deliberate: the worst outcome is a missing line, not a lost draft.
    }
  }

  return {
    debug: (m, f) => write('debug', m, f),
    info: (m, f) => write('info', m, f),
    warn: (m, f) => write('warn', m, f),
    error: (m, f) => write('error', m, f),
  }
}

function walk(
  value: unknown,
  seen: WeakSet<object>,
  maxStringChars: number,
  depthRemaining: number,
): unknown {
  if (value === null) return null

  if (typeof value === 'string') return redactString(value, maxStringChars)
  if (typeof value === 'bigint') return `${value.toString()}n`
  if (typeof value === 'number' || typeof value === 'boolean') return value
  if (typeof value === 'undefined') return 'undefined'
  if (typeof value === 'function') return `[function ${value.name || 'anonymous'}]`
  if (typeof value === 'symbol') return String(value)

  if (depthRemaining <= 0 || seen.has(value)) return '[max depth]'
  seen.add(value)

  if (Array.isArray(value)) {
    return value.map((item) =>
      isKeyedName(item)
        ? redactPair(item, seen, maxStringChars, depthRemaining)
        : walk(item, seen, maxStringChars, depthRemaining - 1),
    )
  }

  const out: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    out[key] = redactPair(item, seen, maxStringChars, depthRemaining, key)
  }
  return out
}

/** A `[{key, value}]` shape carries its secret in the key field, not the path. */
function isKeyedName(item: unknown): item is { key?: unknown; value?: unknown } {
  return (
    typeof item === 'object' &&
    item !== null &&
    !Array.isArray(item) &&
    'key' in item &&
    'value' in item
  )
}

function redactPair(
  item: unknown,
  seen: WeakSet<object>,
  maxStringChars: number,
  depthRemaining: number,
  key?: string,
): unknown {
  const implicitKey = (item as { key?: unknown }).key
  const name = key ?? (typeof implicitKey === 'string' ? implicitKey : '')

  if (isSecretName(name)) return REDACTED

  return walk(item, seen, maxStringChars, depthRemaining - 1)
}

function redactString(value: string, maxStringChars: number): string {
  if (CREDENTIAL_IN_VALUE.test(value)) return REDACTED
  if (value.length <= maxStringChars) return value

  const dropped = value.length - maxStringChars
  return `${value.slice(0, maxStringChars)}…[truncated ${dropped} chars]`
}

function isSecretName(name: string): boolean {
  const normalised = name.toLowerCase().replace(/[^a-z]/g, '')

  return SECRET_KEYS.test(normalised) || PII_KEYS.test(normalised)
}

const REDACTED = '[redacted]'
