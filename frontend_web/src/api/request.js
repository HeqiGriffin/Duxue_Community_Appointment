const SESSION_KEY = 'duxue_web_session'
const DUTY_TOKEN_KEY = 'duxue_duty_terminal_token'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/$/, '')

export function getSession() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null') } catch { return null }
}

export function setSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY)
}

export function getDutyTerminalToken() {
  return localStorage.getItem(DUTY_TOKEN_KEY) || import.meta.env.VITE_DUTY_TERMINAL_TOKEN || ''
}

export function setDutyTerminalToken(token) {
  if (token) localStorage.setItem(DUTY_TOKEN_KEY, token)
  else localStorage.removeItem(DUTY_TOKEN_KEY)
}

function headers(extra = {}) {
  const h = { ...extra }
  const session = getSession()
  if (session?.access_token) h.Authorization = `Bearer ${session.access_token}`
  const duty = getDutyTerminalToken()
  if (duty) h['X-Duty-Terminal-Token'] = duty
  return h
}

async function parseError(response) {
  try {
    const data = await response.json()
    if (Array.isArray(data?.detail)) return data.detail.map(x => x.msg).join('；')
    return data?.detail || data?.message || `请求失败（${response.status}）`
  } catch {
    return `请求失败（${response.status}）`
  }
}

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: headers(options.headers || {}),
  })
  if (response.status === 401) {
    clearSession()
    if (!location.pathname.endsWith('/login')) location.assign('/login')
  }
  if (!response.ok) throw new Error(await parseError(response))
  if (response.status === 204) return null
  return response.json()
}

export function jsonApi(path, { method = 'GET', body, ...rest } = {}) {
  return api(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', ...(rest.headers || {}) },
    ...rest,
  })
}

export async function blobApi(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers: headers(options.headers || {}) })
  if (response.status === 401) {
    clearSession()
    location.assign('/login')
  }
  if (!response.ok) throw new Error(await parseError(response))
  return { blob: await response.blob(), headers: response.headers }
}

export function qs(params = {}) {
  const s = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) s.set(key, value)
  })
  const text = s.toString()
  return text ? `?${text}` : ''
}
