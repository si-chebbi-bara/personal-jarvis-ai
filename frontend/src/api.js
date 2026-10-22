// Where the FastAPI backend lives. Override with a VITE_API_BASE entry in
// frontend/.env when testing from another device (e.g. your phone on WiFi).
// Shared by every component that talks to the backend, so there is exactly
// one place to change it.
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// --- Auth -------------------------------------------------------------------
// Every /api/* route needs the token from the backend's .env (JARVIS_API_TOKEN).
// It is pasted once per device and kept in this browser's localStorage.
const TOKEN_KEY = 'jarvis.token'
export const UNAUTHORIZED_EVENT = 'jarvis:unauthorized'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token.trim())
  } catch {
    // Storage blocked (private mode): the token only lasts until reload.
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Nothing to clear.
  }
}

// fetch() for the backend's /api/* routes: adds the Authorization header and,
// if the backend rejects the token (401), tells the app so it can ask again.
export async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...options.headers, Authorization: `Bearer ${getToken()}` },
  })
  if (res.status === 401) {
    clearToken()
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  return res
}
