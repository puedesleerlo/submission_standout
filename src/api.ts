export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin', ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.map((item: { msg: string }) => item.msg).join(' ') : payload.detail;
    throw new ApiError(detail || 'The request could not be completed.', response.status);
  }
  return payload as T;
}
export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
export async function signIn(token: string) {
  return api('/session', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
}
