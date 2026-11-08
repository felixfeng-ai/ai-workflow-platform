import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '../lib/cn'
import { formatRelativeTime } from '../lib/format'
import type { DataLayer } from '../lib/view'
import type { Notification, NotificationType } from '../types'
import { BellIcon } from './icons'
import { Badge, type BadgeTone } from './ui/badge'

// 通知类型 → 徽章 tone/label（与后端 type 字段一一对应）
const TYPE_TONE: Record<NotificationType, BadgeTone> = {
  agent_run: 'info',
  workflow_run: 'info',
  team: 'gold',
  knowledge: 'success',
  due_reminder: 'warning',
  code_analysis: 'info',
}
const TYPE_LABEL: Record<NotificationType, string> = {
  agent_run: 'Agent',
  workflow_run: '工作流',
  team: '团队',
  knowledge: '知识库',
  due_reminder: '到期',
  code_analysis: '代码分析',
}

interface NotificationBellProps {
  layer: DataLayer
}

export function NotificationBell({ layer }: NotificationBellProps) {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const timerRef = useRef<number | undefined>(undefined)

  // 未读数轮询：30s 一次，随时钟红点保持新鲜
  const refreshUnread = useCallback(async () => {
    try {
      const { count } = await layer.getUnreadCount()
      setUnread(count)
    } catch {
      /* 轮询失败静默：下次轮询重试 */
    }
  }, [layer])

  useEffect(() => {
    refreshUnread()
    timerRef.current = window.setInterval(refreshUnread, 30_000)
    return () => {
      if (timerRef.current !== undefined) window.clearInterval(timerRef.current)
    }
  }, [refreshUnread])

  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const res = await layer.listNotifications({ page_size: 20 })
      setItems(res.items)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '通知加载失败')
    } finally {
      setLoading(false)
    }
  }, [layer])

  const toggle = () => {
    if (!open) void loadList()
    setOpen((o) => !o)
  }

  // 点未读项：先本地乐观置已读再请求，避免面板闪烁
  const markRead = async (n: Notification) => {
    if (n.read_at) return
    setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)))
    setUnread((u) => Math.max(0, u - 1))
    try {
      await layer.markNotificationRead(n.id)
    } catch {
      /* 乐观更新失败：下次刷新校正 */
    }
  }

  const markAllRead = async () => {
    try {
      await layer.markAllNotificationsRead()
    } catch {
      /* 保持现状 */
    }
    setItems((prev) => prev.map((x) => (x.read_at ? x : { ...x, read_at: new Date().toISOString() })))
    setUnread(0)
  }

  return (
    <div className="relative">
      <button
        onClick={toggle}
        className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-line-strong text-ink-2 transition-colors duration-150 hover:bg-active hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-primary/60"
        aria-label="通知"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <BellIcon />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[9px] font-semibold leading-none text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-10 z-50 flex max-h-96 w-80 flex-col overflow-hidden rounded-card border border-line-soft bg-elev2 shadow-modal animate-fadeUp">
            <div className="flex items-center justify-between border-b border-line-soft px-3 py-2">
              <span className="text-[12px] font-medium text-ink">通知</span>
              {unread > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="text-[11px] text-gold transition-colors hover:text-gold-deep"
                >
                  全部已读
                </button>
              )}
            </div>
            <div className="min-h-0 overflow-y-auto">
              {loading ? (
                <div className="px-4 py-6 text-center text-[12px] text-ink-5">加载中…</div>
              ) : items.length === 0 ? (
                <div className="px-4 py-6 text-center text-[12px] text-ink-5">暂无通知</div>
              ) : (
                items.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => void markRead(n)}
                    className={cn(
                      'flex w-full items-start gap-2.5 border-b border-line-soft/60 px-3 py-2.5 text-left transition-colors duration-150 hover:bg-active/50',
                      !n.read_at && 'bg-gold-tint/30',
                    )}
                  >
                    <Badge tone={TYPE_TONE[n.type]} dot={false} className="mt-0.5 shrink-0">
                      {TYPE_LABEL[n.type]}
                    </Badge>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className={cn('truncate text-[12px] font-medium', n.read_at ? 'text-ink-3' : 'text-ink')}>
                          {n.title}
                        </span>
                        {!n.read_at && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-error" />}
                      </span>
                      {n.body && <span className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-ink-5">{n.body}</span>}
                      <span className="mt-1 block text-[10px] text-ink-6">{formatRelativeTime(n.created_at)}</span>
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
