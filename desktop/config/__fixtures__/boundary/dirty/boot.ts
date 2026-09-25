export async function healthz(): Promise<Response> {
  return await fetch('/api/v1/healthz')
}
