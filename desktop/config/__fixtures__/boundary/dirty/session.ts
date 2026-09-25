export function rememberToken(token: string): void {
  localStorage.setItem('access_token', token)
  sessionStorage.setItem('refresh_token', token)
}
