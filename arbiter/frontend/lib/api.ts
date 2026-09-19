// lib/api.ts — Typed API client for the Arbiter backend

import type {
  AskRequest,
  FinalResponse,
  SimulationChange,
  SimulationResult,
  ScanResult,
  IdentityContext,
} from './types'

// Call FastAPI from the browser rather than routing long-running model calls
// through the Next.js development proxy.  The proxy can close a healthy
// connection after ~30 seconds, producing ECONNRESET even when the backend
// has completed the ruling.  FastAPI permits this origin and credentialed
// cookies through its CORS middleware.
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const API_BASE = `${API_ORIGIN}/api`
const TOKEN_STORAGE_KEY = 'arbiter_session_token'

function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

function setStoredToken(token: string | null) {
  if (typeof window === 'undefined') return
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token)
      sessionStorage.setItem(TOKEN_STORAGE_KEY, token)
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      sessionStorage.removeItem(TOKEN_STORAGE_KEY)
    }
  } catch {
    // Browser storage may be unavailable in strict privacy modes.
  }
}

function authHeaders(): Record<string, string> {
  const token = getStoredToken()
  return token ? { Authorization: `Bearer ${token}`, 'X-Session-Token': token } : {}
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function login(
  username: string,
  password: string,
  vendor: string
): Promise<IdentityContext> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, vendor }),
  })
  const identity = await handleResponse<IdentityContext>(res)
  if (identity.session_token) setStoredToken(identity.session_token)
  return identity
}

export async function currentIdentity(): Promise<IdentityContext | null> {
  const res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include', headers: authHeaders() })
  if (res.status === 401) {
    setStoredToken(null)
    return null
  }
  const identity = await handleResponse<IdentityContext>(res)
  if (identity.session_token) setStoredToken(identity.session_token)
  return identity
}

export async function logout(): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers: authHeaders(),
    })
    if (!res.ok) throw new Error('Could not sign out')
  } finally {
    setStoredToken(null)
  }
}

export async function askQuestion(request: AskRequest): Promise<FinalResponse> {
  const res = await fetch(`${API_BASE}/ask`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(request),
  })
  return handleResponse<FinalResponse>(res)
}

export async function runSimulation(
  change: SimulationChange,
  testQuestions?: string[]
): Promise<SimulationResult> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 120_000) // 2 min timeout
  try {
    const res = await fetch(`${API_BASE}/simulate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ change, test_questions: testQuestions }),
      signal: controller.signal,
    })
    return handleResponse<SimulationResult>(res)
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      throw new Error('Simulation timed out (>2 min). Try fewer questions or a simpler change.')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export async function getGraph(
  policyId?: string
): Promise<{ nodes: unknown[]; edges: unknown[] }> {
  const url = policyId
    ? `${API_BASE}/graph?policy_id=${encodeURIComponent(policyId)}`
    : `${API_BASE}/graph`
  const res = await fetch(url)
  return handleResponse(res)
}

export async function runScan(): Promise<ScanResult> {
  const res = await fetch(`${API_BASE}/scan`, { method: 'POST' })
  return handleResponse<ScanResult>(res)
}

export async function checkHealth(): Promise<{ status: string; version: string }> {
  const res = await fetch(`${API_BASE}/health`)
  return handleResponse(res)
}

export async function initData(): Promise<{
  status: string
  policies_loaded: number
  precedents_loaded: number
  message: string
}> {
  const res = await fetch(`${API_BASE}/init`, { method: 'POST' })
  return handleResponse(res)
}
