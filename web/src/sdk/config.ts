/**
 * Loom API Configuration
 *
 * 同域生产 (server 静态托管前端): VITE_SERVER_URL 为空，路径以 / 开头
 * 开发 (vite dev): VITE_SERVER_URL = "http://localhost:8000"，走 vite proxy 或直连
 */

const _serverUrl: string =
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_SERVER_URL) || ''

export const SERVER_URL: string = _serverUrl.endsWith('/')
  ? _serverUrl.slice(0, -1)
  : _serverUrl

export const API_BASE = '/api/v1'

export function getApiUrl(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  const p = path.startsWith('/') ? path : `/${path}`
  return `${SERVER_URL}${API_BASE}${p}`
}

/** SSE stream URL (no API_BASE prefix — streams live under /api/v1 too). */
export function getStreamUrl(path: string): string {
  return getApiUrl(path)
}
