import { invoke } from '@tauri-apps/api/core'

export async function syncNow(): Promise<void> {
  await invoke('sync_now')
}
