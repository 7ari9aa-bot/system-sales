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
  readonly list_printers: undefined
  readonly print_raw: { readonly data: number[] }
  readonly open_cash_drawer: { readonly printerName?: string }
  readonly check_update: undefined
  readonly install_update: undefined
  readonly read_settings: undefined
  readonly write_settings: { readonly webAppUrl: string }
}

export interface CommandResults {
  readonly app_info: unknown
  readonly log_write: null
  readonly list_printers: unknown
  readonly print_raw: unknown
  readonly open_cash_drawer: unknown
  readonly check_update: unknown
  readonly install_update: unknown
  readonly read_settings: string | null
  readonly write_settings: string
}

export type CommandName = keyof CommandArgs

export function call<Name extends CommandName>(
  name: Name,
  ...args: CommandArgs[Name] extends undefined ? [] : [CommandArgs[Name]]
): Promise<CommandResults[Name]> {
  return invoke<CommandResults[Name]>(name, args[0] === undefined ? undefined : { ...args[0] })
}
