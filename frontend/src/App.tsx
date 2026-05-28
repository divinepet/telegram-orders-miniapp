import { FormEvent, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import type { Job, Me, Status, User } from './types'
import { Calendar, CircleUserRound } from 'lucide-react'

const statusText: Record<Status, string> = { WAITING: 'Ожидает', ACTIVE: 'В работе', COMPLETED: 'Завершено' }
const money = (value?: number) => value === undefined ? '' : `${value.toLocaleString('ru-RU')} ₽`
const date = (value?: string) => value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'medium' }) : '—'

function formatDate(value?: string) {
	if (!value) return '—'

	return new Date(value).toLocaleDateString('ru-RU', {
		day: 'numeric',
		month: 'long',
	})
}

export default function App() {
	const [me, setMe] = useState<Me | null>(null)
	const [jobs, setJobs] = useState<Job[]>([])
	const [users, setUsers] = useState<User[]>([])
	const [tab, setTab] = useState<'jobs' | 'users'>('jobs')
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState('')
	const [createOpen, setCreateOpen] = useState(false)

	const reload = async () => {
		const [identity, jobRows] = await Promise.all([
			api.me(),
			api.jobs(),
		])

		setMe(identity)
		setJobs(jobRows)

		if (identity.is_admin) {
			setUsers(await api.users())
		}
	}

	useEffect(() => {
		; (async () => {
			try {
				await reload()
			} catch (error) {
				setError((error as Error).message)
			} finally {
				setLoading(false)
			}
		})()
	}, [])

	useEffect(() => {
		if (!me || me.is_admin) {
			return
		}

		const intervalId = window.setInterval(() => {
			reload(me).catch(() => {
				// Не показываем ошибку фонового обновления пользователю.
			})
		}, 10000)

		return () => {
			window.clearInterval(intervalId)
		}
	}, [me])

	useEffect(() => {
		const tg = window.Telegram?.WebApp

		if (!tg) {
			return
		}

		tg.ready()

		// Цвет области Telegram вокруг вашего приложения.
		tg.setHeaderColor('#0a0a0a')
		tg.setBackgroundColor('#0a0a0a')

		// Нижняя системная область, например navigation bar на Android.
		if (tg.isVersionAtLeast('7.10')) {
			tg.setBottomBarColor('#0a0a0a')
		}

		// Сначала раскрываем MiniApp на максимально доступную высоту.
		tg.expand()

		// Затем запрашиваем настоящий полноэкранный режим.
		if (tg.isVersionAtLeast('8.0')) {
			tg.requestFullscreen()
		}
	}, [])

	if (loading) return <div className='loader-wrapper'><div className="loader"></div></div>
	if (error || !me) return <ScreenMessage text={error || 'Доступ недоступен'} />

	const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user
	const avatarUrl = tgUser?.photo_url

	return (
		<main className="app">
			<header className="header">
				<div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
					<img
						src={avatarUrl}
						alt={'Пользователь'}
						className="avatar"
					/>
					<div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
						<div className="identity">{me.first_name || me.username || me.telegram_id}</div>
						<div style={{ color: 'gray', fontSize: 14 }}>{me.is_admin ? 'Администратор' : 'Пользователь'}</div>
					</div>
				</div>
				<div className="rating">⭐ {Number(me.rating).toFixed(1)}</div>

			</header>
			{me.is_admin && <nav className="tabs">
				<button className={tab === 'jobs' ? 'active' : ''} onClick={() => setTab('jobs')}>Заявки</button>
				<button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>Пользователи</button>
			</nav>}
			{tab === 'jobs'
				? <JobsView
					jobs={jobs}
					admin={me.is_admin}
					onRefresh={() => reload()}
					onCreate={() => setCreateOpen(true)}
				/>
				: <UsersView
					users={users}
					onRefresh={() => reload()}
				/>
			}
			{createOpen &&
				<CreateJobModal
					onClose={() => setCreateOpen(false)}
					onCreated={async () => { setCreateOpen(false); await reload() }}
				/>
			}
		</main>
	)
}

function ScreenMessage({ text }: { text: string }) { return <div className="screen-message">{text}</div> }

function JobsView({ jobs, admin, onRefresh, onCreate }: { jobs: Job[]; admin: boolean; onRefresh: () => Promise<void>; onCreate: () => void }) {
	const groups = useMemo(() => ({
		WAITING: jobs.filter(j => j.status === 'WAITING'), ACTIVE: jobs.filter(j => j.status === 'ACTIVE'), COMPLETED: jobs.filter(j => j.status === 'COMPLETED')
	}), [jobs])
	return (
		<section className='group-wrapper'>
			{admin &&
				<button className="primary" onClick={onCreate}>Создать новую заявку</button>
			}
			{(['WAITING', 'ACTIVE', 'COMPLETED'] as Status[]).map(status =>
				<section className="group" key={status}>
					<h2>{statusText[status]} <span>{groups[status].length}</span></h2>
					<div className='job-cards'>
						{groups[status].length !== 0 &&
							groups[status].map(job =>
								<JobCard key={job.id} job={job} admin={admin} onRefresh={onRefresh} />
							)
						}
					</div>
				</section>
			)}
		</section>
	)
}

function JobCard({ job, admin, onRefresh }: { job: Job; admin: boolean; onRefresh: () => Promise<void> }) {
	const [busy, setBusy] = useState(false)
	const claim = async () => {
		setBusy(true)

		try {
			await api.claim(job.id)
			await onRefresh()

			// window.Telegram?.WebApp?.showAlert('Заявка назначена вам')
		} catch (error) {
			window.Telegram?.WebApp?.showAlert(
				(error as Error).message,
			)
			await onRefresh()
		} finally {
			setBusy(false)
		}
	}
	const complete = async () => {
		const raw = window.prompt('Укажите итоговую сумму в рублях (без копеек):')
		if (raw === null) return
		const amount = Number(raw)
		if (!Number.isInteger(amount) || amount < 0) return window.Telegram?.WebApp?.showAlert('Введите целое положительное число')
		setBusy(true); try { await api.complete(job.id, amount); await onRefresh() } catch (e) { alert((e as Error).message) } finally { setBusy(false) }
	}
	const decline = async () => {
		if (!window.confirm('Отказаться от заявки? Она будет снова отправлена другим исполнителям, а рейтинг уменьшится на 0.5.')) return
		setBusy(true); try { await api.decline(job.id); await onRefresh() } catch (e) { alert((e as Error).message) } finally { setBusy(false) }
	}
	return <article className="card">
		<div className="card-head">
			<div style={{ fontSize: 14, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
				Заявка #{job.id}
				<span style={{ fontWeight: 500, color: '#565c67' }}>({formatDate(job.created_at)}{job.status === 'COMPLETED' ? ` - ${formatDate(job.closed_at)}` : ''})</span></div>
			<span className={`badge ${job.status.toLowerCase()}`}>{job.status === 'COMPLETED' ? money(job.final_amount) : statusText[job.status]}</span>
		</div>

		<p>{job.full_text || job.public_text}</p>

		{admin && job.assignee_name &&
			<div style={{ display: 'flex', alignItems: 'center', color: '#8992a3', fontSize: 13, fontWeight: 600, gap: 3 }}>
				<CircleUserRound size={16} stroke={'#8992a3'} />
				{job.assignee_name.replace('@', '')}
			</div>
		}

		{!admin && job.status === 'WAITING' && (
			<div className="actions">
				<button
					className="primary take-job"
					disabled={busy}
					onClick={claim}
				>
					{busy ? 'Назначаем…' : 'Взять в работу'}
				</button>
			</div>
		)}

		{!admin && job.status === 'ACTIVE' &&
			<div className="actions">
				<button className="success" disabled={busy} onClick={complete}>Выполнить заявку</button>
				<button className="danger" disabled={busy} onClick={decline}>Отказаться</button>
			</div>
		}
	</article>
}

function CreateJobModal({
	onClose,
	onCreated,
}: {
	onClose: () => void
	onCreated: () => Promise<void>
}) {
	const [publicText, setPublicText] = useState('')
	const [fullText, setFullText] = useState('')
	const [busy, setBusy] = useState(false)

	useEffect(() => {
		const previousOverflow = document.body.style.overflow
		document.body.style.overflow = 'hidden'

		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Escape' && !busy) {
				onClose()
			}
		}

		document.addEventListener('keydown', handleKeyDown)

		return () => {
			document.body.style.overflow = previousOverflow
			document.removeEventListener('keydown', handleKeyDown)
		}
	}, [busy, onClose])

	const submit = async (event: FormEvent) => {
		event.preventDefault()
		setBusy(true)

		try {
			await api.createJob(publicText, fullText)
			await onCreated()
		} catch (error) {
			alert((error as Error).message)
		} finally {
			setBusy(false)
		}
	}

	const closeOnBackdrop = (event: React.PointerEvent<HTMLDivElement>) => {
		if (event.target === event.currentTarget && !busy) {
			onClose()
		}
	}

	const revealFieldAfterKeyboard = (
		event: React.FocusEvent<HTMLTextAreaElement>,
	) => {
		const field = event.currentTarget

		window.setTimeout(() => {
			field.scrollIntoView({
				behavior: 'smooth',
				block: 'center',
				inline: 'nearest',
			})
		}, 250)
	}

	return (
		<div className="overlay" onPointerDown={closeOnBackdrop}>
			<form className="modal" onSubmit={submit}>
				<h2>Новая заявка</h2>

				<label>
					Полный текст
					<textarea
						required
						maxLength={10000}
						value={fullText}
						onChange={event => setFullText(event.target.value)}
						onFocus={revealFieldAfterKeyboard}
						placeholder="Что увидит только исполнитель заявки"
					/>
				</label>

				<label>
					Публичный текст
					<textarea
						required
						maxLength={4000}
						value={publicText}
						onChange={event => setPublicText(event.target.value)}
						onFocus={revealFieldAfterKeyboard}
						placeholder="Что увидят все пользователи"
					/>
				</label>

				<div className="actions modal-actions">
					<button type="button" onClick={onClose} disabled={busy}>
						Отмена
					</button>
					<button className="primary" type="submit" disabled={busy}>
						{busy ? 'Создание…' : 'Создать'}
					</button>
				</div>
			</form>
		</div>
	)
}

function UsersView({ users, onRefresh }: { users: User[]; onRefresh: () => Promise<void> }) {
	const add = async () => { const raw = prompt('Введите Telegram ID нового пользователя:'); if (!raw) return; const id = Number(raw); if (!Number.isInteger(id)) return alert('Некорректный Telegram ID'); try { await api.addUser(id); await onRefresh() } catch (e) { alert((e as Error).message) } }
	const ban = async (u: User) => { if (!confirm(`Заблокировать пользователя ${u.username ? '@' + u.username : u.telegram_id}? Его активные заявки вернутся в ожидание.`)) return; try { await api.banUser(u.telegram_id); await onRefresh() } catch (e) { alert((e as Error).message) } }
	return <section><div className="section-title"><button className="primary" onClick={add}>Добавить пользователя</button></div>
		<div className="users">
			{users.map(u =>
				<article className="user" key={u.telegram_id}>
					<div>
						<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
							<strong>{u.first_name || (u.username ? '@' + u.username : u.telegram_id)}</strong>
							{u.is_admin && <span className="admin-label">Админ</span>}
							{!u.is_admin && <div style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 2 }}>⭐ <span style={{ fontSize: 14, fontWeight: 600 }}>{Number(u.rating).toFixed(1)}</span></div>}
						</div>
						<small>Активных: {u.active_jobs} | Завершено: {u.completed_jobs}</small>
					</div>
					{u.is_admin
						? ""
						: u.is_active
							? <button className="danger ghost" onClick={() => ban(u)}>Забанить</button>
							: <span className="muted">Заблокирован</span>
					}
				</article>
			)}
		</div>
	</section>
}
