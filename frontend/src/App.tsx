import { FormEvent, PointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Job, Me, Status, User } from './types'
import { Calendar, Check, CircleUserRound, Edit, Pen, Phone, Star, X } from 'lucide-react'
import Tippy from '@tippyjs/react'
import 'tippy.js/themes/material.css'
import 'tippy.js/dist/tippy.css'

const statusText: Record<Status, string> = {
	WAITING: 'Ожидает',
	AWAITING_CALL: 'Ожидает звонка',
	ACTIVE: 'В работе',
	COMPLETED: 'Завершено',
}
const money = (value?: number) => value === undefined ? '' : `${value.toLocaleString('ru-RU')} ₽`
const date = (value?: string) => value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'medium' }) : '—'

function formatDate(value?: string) {
	if (!value) return '—'

	return new Date(value).toLocaleDateString('ru-RU', {
		day: 'numeric',
		month: 'long',
		year: 'numeric',
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
			reload().catch(() => {
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
				<div className="rating"><Star stroke='orange' fill='orange' size={20} />{Number(me.rating).toFixed(1)}</div>

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
		WAITING: jobs.filter(j => j.status === 'WAITING'),
		AWAITING_CALL: jobs.filter(j => j.status === 'AWAITING_CALL'),
		ACTIVE: jobs.filter(j => j.status === 'ACTIVE'),
		COMPLETED: jobs.filter(j => j.status === 'COMPLETED'),
	}), [jobs])
	return (
		<section className='group-wrapper'>
			{admin &&
				<button className="primary" onClick={onCreate}>Создать новую заявку</button>
			}
			{(['WAITING', 'AWAITING_CALL', 'ACTIVE', 'COMPLETED'] as Status[]).map(status => {

				if (groups[status].length === 0)
					return <></>;

				return (
					<section className="group" key={status}>
						<h2>{statusText[status]} <span>{groups[status].length}</span></h2>
						<div className='job-cards'>
							{groups[status].length !== 0 && groups[status].map(job =>
								<JobCard key={job.id} job={job} admin={admin} onRefresh={onRefresh} />
							)}
						</div>
					</section>
				)
			})}
		</section>
	)
}


function CollapsibleJobText({ text }: { text: string }) {
	const [expanded, setExpanded] = useState(false)
	const [overflowing, setOverflowing] = useState(false)

	const ref = useRef<HTMLParagraphElement | null>(null)

	useEffect(() => {
		const element = ref.current
		if (!element) return

		const check = () => {
			if (expanded) return

			setOverflowing(
				element.scrollHeight > element.clientHeight + 1
			)
		}

		check()

		const observer = new ResizeObserver(check)
		observer.observe(element)

		return () => observer.disconnect()
	}, [text, expanded])

	const toggle = () => {
		if (overflowing || expanded) {
			setExpanded(value => !value)
		}
	}

	return (
		<div
			className="job-text"
			onClick={toggle}
		>
			<span
				ref={ref}
				className={expanded ? '' : 'job-text-content-collapsed'}
			>
				{text}
			</span>

			{!expanded && overflowing && (
				<span className="job-text-more">
					…показать больше
				</span>
			)}

			{expanded && (
				<span className="job-text-hide">
					...скрыть
				</span>
			)}
		</div>
	)
}

function JobCard({ job, admin, onRefresh }: { job: Job; admin: boolean; onRefresh: () => Promise<void> }) {
	const [busy, setBusy] = useState(false)
	const claim = async () => {
		const confirmed = window.confirm(
			'Взять эту заявку в работу? После подтверждения она будет закреплена за вами.'
		)

		if (!confirmed) return

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
	const called = async () => {
		setBusy(true)

		try {
			await api.called(job.id)
			await onRefresh()
		} catch (error) {
			window.Telegram?.WebApp?.showAlert(
				(error as Error).message,
			)
		} finally {
			setBusy(false)
		}
	}
	const editComment = async () => {
		const raw = window.prompt(
			job.comment_text
				? 'Редактировать комментарий:'
				: 'Введите комментарий:',
			job.comment_text ?? ''
		)

		if (raw === null) return

		const text = raw.trim()

		if (!text) {
			window.Telegram?.WebApp?.showAlert(
				'Комментарий не может быть пустым'
			)
			return
		}

		setBusy(true)

		try {
			await api.saveComment(job.id, text)
			await onRefresh()
		} catch (error) {
			window.Telegram?.WebApp?.showAlert(
				(error as Error).message
			)
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
				<Tippy
					content={
						<span style={{ fontWeight: 500 }}>
							Создано: {formatDate(job.created_at)} <br />
							{job.status === 'COMPLETED' && `Завершено: ${formatDate(job.closed_at)}`}
						</span>
					}
					placement="top-start"
					theme='material'
				>
					<div className='card-head-left'>
						<div className='card-header-title'>Заявка #{job.id}</div>
						{admin && job.assignee_name &&
							<div className='card-header-author'>
								{job.assignee_name}
							</div>
						}
					</div>
				</Tippy>
			</div>
			<span className={`badge ${job.status.toLowerCase()}`}>{job.status === 'COMPLETED' ? money(job.final_amount) : statusText[job.status]}</span>
		</div>

		<CollapsibleJobText
			text={job.full_text || job.public_text}
		/>

		{job.comment_text && (
			<div className={'job-comment'}>
				<div className="job-comment-title">Комментарий</div>

				<div className={'job-comment-text'}>
					{job.comment_text}
				</div>

				<div className="comment-dates">
					<span>
						Создан: {date(job.comment_created_at)}
					</span>

					{job.comment_updated_at &&
						job.comment_created_at &&
						new Date(job.comment_updated_at).getTime() !==
						new Date(job.comment_created_at).getTime() && (
							<span>
								Изменён: {date(job.comment_updated_at)}
							</span>
						)}
				</div>
			</div>
		)}

		{!admin &&
			<div className='card-bottom-buttons-group'>

				<div className='card-bottom-buttons-topline'>
					{job.status === 'WAITING' && (
						<button className="primary take-job" disabled={busy} onClick={claim} >
							{busy ? 'Назначаем…' : 'Взять в работу'}
						</button>
					)}
					{job.status === 'AWAITING_CALL' &&
						<button className="success" disabled={busy} onClick={called} >
							<Check size={18} />
							Созвонился с клиентом
						</button>
					}
					{job.status === 'ACTIVE' &&
						<button className="success" disabled={busy} onClick={complete}>
							<Check size={18} />
							Выполнить заявку
						</button>
					}
					{(job.status === 'AWAITING_CALL' || job.status === 'ACTIVE') &&
						<>
							<button className="primary" disabled={busy} onClick={editComment} style={{ background: '#343440' }}>
								<Pen size={18} />
								{job.comment_text ? 'Редактировать комментарий' : 'Добавить комментарий'}
							</button>
							<button className="danger" disabled={busy} onClick={decline}>
								<X size={18} />
								Отказаться
							</button>
						</>
					}
				</div>


				{/* {(job.status === 'AWAITING_CALL' || job.status === 'ACTIVE') &&
					<div className='card-bottom-buttons-bottomline'>
						<button className="primary" disabled={busy} onClick={editComment} >
							{job.comment_text ? 'Редактировать комментарий' : 'Добавить комментарий'}
						</button>
						<button className="danger" disabled={busy} onClick={decline}>
							Отказаться
						</button>
					</div>
				} */}

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

	const closeOnBackdrop = (event: PointerEvent<HTMLDivElement>) => {
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
					<button className="danger" type="button" onClick={onClose} disabled={busy}>
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
