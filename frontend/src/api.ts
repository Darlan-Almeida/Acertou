export const API = import.meta.env.VITE_API_URL || location.origin
export const wsUrl = API.replace(/^http/, 'ws')
export const teacherToken = () => localStorage.getItem('teacher_token') || ''
export const participantToken = (id: number) => localStorage.getItem(`participant_${id}`) || ''
export async function request<T = any>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `Erro ${response.status}`)
  }
  return response.json()
}
export const get = <T = any>(path: string, token = teacherToken()) => request<T>(path, {}, token)
export const post = <T = any>(path: string, body: unknown, token = teacherToken()) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }, token)
export const put = <T = any>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }, teacherToken())
export const del = (path: string) => request(path, { method: 'DELETE' }, teacherToken())
