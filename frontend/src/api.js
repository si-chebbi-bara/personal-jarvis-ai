// Where the FastAPI backend lives. Override with a VITE_API_BASE entry in
// frontend/.env when testing from another device (e.g. your phone on WiFi).
// Shared by every component that talks to the backend, so there is exactly
// one place to change it.
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
