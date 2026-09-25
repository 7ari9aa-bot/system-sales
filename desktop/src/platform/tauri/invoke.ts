import { invoke } from '@tauri-apps/api/core'

import type { LogRecord } from '@/shared/log'

/**
 * The only module in the app that is allowed to know `invoke` exists, and the
 * only place a command name is written down. Everything above it calls a named
 * function on a port; everything below it is a Rust service.
 *
 * Results come back typed `unknown` on purpose. A Rust struct that changes shape
 * must fail at the adapter's schema, not silently retype a component's props.
 */
export interface LogRecordPayload {
  readonly level: LogRecord['level']
  readonly message: string
  readonly fields: Record<string, unknown>
  readonly requestId: string | null
  readonly sink: string
  readonly ts: string
}

export interface CommandArgs {
  readonly app_info: undefined
  readonly log_write: { readonly record: LogRecordPayload }
}

export interface CommandResults {
  readonly app_info: unknown
  readonly log_write: null
}

export type CommandName = keyof CommandArgs

export function call<Name extends CommandName>(
  name: Name,
  ...args: CommandArgs[Name] extends undefined ? [] : [CommandArgs[Name]]
): Promise<CommandResults[Name]> {
  return invoke<CommandResults[Name]>(name, args[0] === undefined ? undefined : { ...args[0] })
}
