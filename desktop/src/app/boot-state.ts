export type BootState =
  | { readonly status: 'checking' }
  | { readonly status: 'ok'; readonly apiBaseUrl: string }
  | { readonly status: 'missing' | 'invalid' | 'insecure' }
