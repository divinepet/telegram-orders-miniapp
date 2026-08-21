import type { Job, Me, User } from './types'

// declare global { interface Window { Telegram?: { WebApp?: { initData: string; ready: () => void; expand: () => void; showAlert: (text: string) => void; themeParams?: Record<string, string> } } } }

const initData = () => window.Telegram?.WebApp?.initData ?? ''
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
	const response = await fetch(`/api${path}`, {
		...options,
		headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData(), ...(options.headers ?? {}) },
	})
	if (!response.ok) {
		const data = await response.json().catch(() => ({}))
		throw new Error(data.detail ?? 'Ошибка сервера')
	}
	return response.json() as Promise<T>
}

export const api = {
	me: () => request<Me>('/me'),
	jobs: () => request<Job[]>('/jobs'),
	users: () => request<User[]>('/users'),

	createJob: (public_text: string, full_text: string) =>
		request<Job>('/jobs', {
			method: 'POST',
			body: JSON.stringify({ public_text, full_text }),
		}),

	claim: (id: number) =>
		request<Job>(`/jobs/${id}/claim`, {
			method: 'POST',
		}),

	called: (id: number) =>
		request<Job>(`/jobs/${id}/called`, {
			method: 'POST',
		}),

	saveComment: (id: number, text: string) =>
		request<Job>(`/jobs/${id}/comment`, {
			method: 'PUT',
			body: JSON.stringify({ text }),
		}),

	complete: (id: number, amount: number) =>
		request<Job>(`/jobs/${id}/complete`, {
			method: 'POST',
			body: JSON.stringify({ amount }),
		}),

	decline: (id: number) =>
		request<{ ok: boolean }>(`/jobs/${id}/decline`, {
			method: 'POST',
		}),

	addUser: (telegram_id: number) =>
		request<User>('/users', {
			method: 'POST',
			body: JSON.stringify({ telegram_id }),
		}),

	banUser: (telegram_id: number) =>
		request<{ ok: boolean }>(`/users/${telegram_id}/ban`, {
			method: 'POST',
		}),
}
