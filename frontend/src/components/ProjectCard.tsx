import { Card } from './ui/card'
import { DeployButton } from './DeployButton'
import { StatusBadge } from './status'
import type { DataLayer } from '../lib/view'
import type { Note, Project, Task } from '../types'

// 只有这类地址能被后端解析出 owner/repo 去触发 Actions（与 services/deploy.py 的正则同义）
const GITHUB_REPO_RE = /^https?:\/\/(?:www\.)?github\.com\/[^/\s]+\/[^/\s#?]+/i

export function ProjectCard({
  project,
  tasks,
  notes,
  layer,
  canConfigure,
  onOpen,
  onConfigureDeploy,
}: {
  project: Project
  tasks: Task[]
  notes: Note[]
  layer: DataLayer
  /** 当前用户是 owner，可以改项目的部署配置（member/访客不能） */
  canConfigure: boolean
  onOpen: () => void
  onConfigureDeploy: () => void
}) {
  const total = tasks.length
  const done = tasks.filter((t) => t.status === 'done').length
  const pct = total ? Math.round((done / total) * 1000) / 10 : 0

  // 三种状态互斥：能部署 → 真按钮；配了 workflow 但不能部署（缺 token 或是 member）
  // → 灰按钮说明原因；什么都没配但是个 GitHub 仓库 → 引导去配置。
  const showConfigure = !project.can_deploy && !project.deploy_workflow && canConfigure && GITHUB_REPO_RE.test(project.repo_url ?? '')
  const showDisabledDeploy = !project.can_deploy && !!project.deploy_workflow

  return (
    <div
      onClick={onOpen}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen()
        }
      }}
      className="block w-full cursor-pointer text-left"
    >
      <Card className="flex h-full flex-col gap-3 p-4 transition-[transform,background-color,border-color] duration-150 hover:-translate-y-[2px] hover:border-gold-primary/40">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold text-ink">{project.name}</div>
            <div className="mt-1.5">
              <StatusBadge status={project.status} />
            </div>
          </div>
          <span
            className="mt-1 h-2 w-2 shrink-0 rounded-full"
            style={{ background: project.color ?? '#D9A441', boxShadow: '0 0 6px rgba(217,164,65,.5)' }}
          />
        </div>
        {project.description && (
          <p className="line-clamp-2 text-[12px] leading-relaxed text-ink-3">{project.description}</p>
        )}
        {(project.repo_url || project.deploy_url || project.can_deploy || showConfigure || showDisabledDeploy) && (
          <div className="flex flex-wrap items-center gap-2">
            {project.repo_url && (
              <a
                href={project.repo_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-1 rounded-md border border-line-soft bg-elev1 px-1.5 py-0.5 text-[11px] text-ink-3 transition-colors hover:border-gold-primary/40 hover:text-gold"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                仓库
              </a>
            )}
            {project.can_deploy && <DeployButton project={project} layer={layer} />}
            {showDisabledDeploy && (
              // 不可点击：诚实地说明「现在不能部署」，而不是给个按钮点下去才报错。
              // 不细分原因（token 未配 / 不是 owner）是刻意的 —— 前端拿不到那个判断依据，
              // 拆开说就会猜错，猜错比说笼统更糟。
              <span
                title="当前不可部署：需要 owner 角色，且服务端已配置部署令牌"
                onClick={(e) => e.stopPropagation()}
                className="flex cursor-not-allowed items-center gap-1 rounded-md border border-line-soft bg-elev1 px-1.5 py-0.5 text-[11px] text-ink-5"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                部署
              </span>
            )}
            {showConfigure && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onConfigureDeploy()
                }}
                title="指定要触发的 GitHub Actions workflow，之后就能从这里一键部署"
                className="flex items-center gap-1 rounded-md border border-line-soft bg-elev1 px-1.5 py-0.5 text-[11px] text-ink-3 transition-colors hover:border-gold-primary/40 hover:text-gold"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                配置部署
              </button>
            )}
            {project.deploy_url && (
              // 「线上」是外链、不是动作：平台不会因为你点它而构建任何东西。
              // 叫「部署」会让人以为点了会触发发布，实际只是开新标签页跳转。
              <a
                href={project.deploy_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                title="在线上打开（不会触发部署）"
                className="flex items-center gap-1 rounded-md border border-line-soft bg-elev1 px-1.5 py-0.5 text-[11px] text-ink-3 transition-colors hover:border-gold-primary/40 hover:text-gold"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M15 3h6v6M10 14 21 3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                线上
              </a>
            )}
          </div>
        )}
        <div className="mt-auto flex flex-col gap-2 pt-1">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-ink-4">进度</span>
            <span className="font-mono tabular-nums text-gold">{pct}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-active">
            <div
              className="h-full rounded-full bg-gradient-to-r from-gold-deep to-gold"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center justify-between pt-0.5 font-mono text-[11px] tabular-nums text-ink-5">
            <span>{total} 任务</span>
            <span>{notes.length} 笔记</span>
          </div>
        </div>
      </Card>
    </div>
  )
}
