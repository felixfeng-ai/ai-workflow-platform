import { useEffect, useRef, useState } from 'react'
import { Spinner } from './ui/button'
import type { DataLayer } from '../lib/view'
import type { DeployRun, Project } from '../types'

// 触发后轮询的时间窗。GitHub Actions 一次真实部署常要几分钟，前端不等到底：
// 超过这个窗口还没结束就停在「部署中」并给出 GitHub 链接，让用户自己去看。
// 注意这不是失败 —— 把它显示成失败是最容易撒的谎。
const POLL_INTERVAL_MS = 5000
const POLL_MAX_ATTEMPTS = 24

// 与后端 services/deploy.py 的 TERMINAL_STATUSES 一致。
// unknown = 回查窗口内没能在 GitHub 上找到这次 run，是不确定而非失败
const TERMINAL = new Set(['success', 'failure', 'cancelled', 'unknown'])

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  in_progress: '部署中',
  success: '部署成功',
  failure: '部署失败',
  cancelled: '已取消',
  unknown: '未能确认',
}

const STATUS_CLASS: Record<string, string> = {
  queued: 'border-line-soft text-ink-3',
  in_progress: 'border-gold-primary/40 text-gold',
  success: 'border-success/40 text-success',
  failure: 'border-error/40 text-error',
  cancelled: 'border-line-soft text-ink-4',
  unknown: 'border-warning/40 text-warning',
}

/**
 * 远程部署按钮：触发 GitHub Actions workflow 并跟踪这一次 run 的状态。
 *
 * 只在 project.can_deploy 为 true 时由 ProjectCard 渲染 —— 那个字段是服务端算的，
 * 前端复制不了它的判断（需要知道服务器有没有配 token 和当前用户角色）。
 */
export function DeployButton({ project, layer }: { project: Project; layer: DataLayer }) {
  const [run, setRun] = useState<DeployRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // 卸载后停止轮询：部署本身会在 GitHub 侧继续跑，前端没必要再打后端。
  // StrictMode 下开发模式会挂载两次，所以这里在 effect 里重新置 true。
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // 挂载时回填最近一次部署。刷新页面后仍能看到「部署中 / 上次失败」，
  // 否则卡片每次都显示成一切正常，用户会重复点击，触发重复部署。
  useEffect(() => {
    let cancelled = false
    layer
      .listDeployments(project.id, 1)
      .then((runs) => {
        if (!cancelled && runs.length > 0) setRun(runs[0])
      })
      // 读历史失败不影响主流程（用户仍可点部署），静默忽略
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [layer, project.id])

  async function poll(runId: string) {
    for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      if (!alive.current) return
      try {
        const latest = await layer.getDeployment(project.id, runId)
        if (!alive.current) return
        setRun(latest)
        if (TERMINAL.has(latest.status)) return
      } catch (e) {
        if (!alive.current) return
        setError(e instanceof Error ? e.message : '状态查询失败')
        return
      }
    }
  }

  async function trigger() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const created = await layer.deployProject(project.id)
      if (!alive.current) return
      setRun(created)
      if (!TERMINAL.has(created.status)) await poll(created.id)
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : '触发部署失败')
    } finally {
      if (alive.current) setBusy(false)
    }
  }

  const running = run !== null && !TERMINAL.has(run.status)

  return (
    <span className="inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={(e) => {
          // 卡片整体可点（点击进入项目详情），这里必须拦住冒泡，否则点部署会跳页
          e.stopPropagation()
          trigger()
        }}
        disabled={busy || running}
        title={`触发 ${project.deploy_workflow} 部署`}
        className="flex items-center gap-1 rounded-md border border-gold-primary/40 bg-gold-tint/40 px-1.5 py-0.5 text-[11px] text-gold transition-colors hover:border-gold-primary/70 disabled:opacity-60"
      >
        {busy || running ? (
          <Spinner className="h-2.5 w-2.5" />
        ) : (
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
        {running ? '部署中' : '部署'}
      </button>

      {run && (
        <a
          href={run.run_url ?? undefined}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title={run.error ?? STATUS_TEXT[run.status] ?? run.status}
          className={`rounded-md border px-1.5 py-0.5 text-[11px] ${STATUS_CLASS[run.status] ?? 'border-line-soft text-ink-3'} ${
            run.run_url ? 'hover:border-current' : 'pointer-events-none'
          }`}
        >
          {STATUS_TEXT[run.status] ?? run.status}
          {run.run_url && ' ↗'}
        </a>
      )}

      {error && (
        <span className="max-w-[180px] truncate text-[11px] text-error" title={error}>
          {error}
        </span>
      )}
    </span>
  )
}
