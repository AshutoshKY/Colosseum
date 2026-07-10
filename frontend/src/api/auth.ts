/**
 * Auth scaffolding — there is no login flow yet, but the API client is wired
 * so one can be added without touching call sites:
 *
 *   1. Obtain a token (OAuth redirect, login form, …) and call setToken().
 *   2. Every request then carries `Authorization: Bearer <token>`.
 *   3. A 401 response clears the token and emits `colosseum:unauthorized`
 *      on window — a future login screen can listen for it.
 */
const TOKEN_KEY = 'colosseum.authToken'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function handleUnauthorized() {
  clearToken()
  window.dispatchEvent(new CustomEvent('colosseum:unauthorized'))
}
