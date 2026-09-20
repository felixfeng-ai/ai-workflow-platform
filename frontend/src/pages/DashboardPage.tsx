import { useMemo, useState } from 'react'
import { ProjectCard } from '../components/ProjectCard'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { Empty } from '../components/ui/empty'
import { Input, Textarea } from '../components/ui/input'
import type { DataLayer } from '../lib/view'
import type { Note, Project, Task } from '../types'

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] text-ink-4">{label}</div>
      <div className="text-glow mt-1.5 font-mono text-[24px] font-semibold tabular-nums text-gold">
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-ink-5">{sub}</div>}
    </Card>
  )
}

export function DashboardPage({
  projects,
  tasks,
  notes,
  layer,
  canConfigure,
  onOpenProject,
  onCreateProject,
  onConfigureDeploy,
}: {
  projects: Project[]
  tasks: Task[]
  notes: Note[]
  layer: DataLayer
  /** 当前用户是 owner：能新建项目、能改部署配置 */
  canConfigure: boolean
  onOpenProject: (id: string) => void
  onCreateProject: (name: string, description?: string, repoUrl?: string, deployUrl?: string, deployWorkflow?: string) => Promise<void>
  onConfigureDeploy: (projectId: string, deployWorkflow: string | null) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [deployUrl, setDeployUrl] = useState('')
  const [deployWorkflow, setDeployWorkflow] = useState('')
  const [busy, setBusy] = useState(false)
  // 部署配置弹窗：正在配置哪个项目（null = 关闭）
  const [configuring, setConfiguring] = useState<Project | null>(null)
  const [configWorkflow, setConfigWorkflow] = useState('')
  const [configError, setConfigError] = useState('')

  const stats = useMemo(() => {
    const total = tasks.length
    const done = tasks.filter((t) => t.status === 'done').length
    const inProgress = tasks.filter((t) => t.status === 'in_progress').length
    const today = new Date().toISOString().slice(0, 10)
    const todayDue = tasks.filter((t) => t.due_date === today).length
    const rate = total ? Math.round((done / total) * 1000) / 10 : 0
    return {
      active: projects.filter((p) => p.status === 'active').length,
      inProgress,
      todayDue,
      rate,
      total,
      done,
    }
  }, [tasks, projects])

  async function submit() {
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      await onCreateProject(
        name.trim(),
        description.trim() || undefined,
        repoUrl.trim() || undefined,
        deployUrl.trim() || undefined,
        deployWorkflow.trim() || undefined,
      )
      setOpen(false)
      setName('')
      setDescription('')
      setRepoUrl('')
      setDeployUrl('')
      setDeployWorkflow('')
    } finally {
      setBusy(false)
    }
  }

  function openConfigure(p: Project) {
    setConfiguring(p)
    setConfigWorkflow(p.deploy_workflow ?? '')
    setConfigError('')
  }

  async function saveConfigure(clear: boolean) {
    if (!configuring) return
    setConfigError('')
    try {
      // 传 null = 关闭该项目的远程部署（按钮回到「配置部署」）
      await onConfigureDeploy(configuring.id, clear ? null : configWorkflow.trim() || null)
      setConfiguring(null)
    } catch (e) {
      setConfigError(e instanceof Error ? e.message : '保存失败')
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-[650] tracking-tight text-ink">工作台</h1>
          <p className="mt-1 text-[12.5px] text-ink-3">管理项目、任务与笔记 · 数据由 AI 引擎驱动</p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          新建项目
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="活跃项目" value={stats.active} sub={`${projects.length} 个全部`} />
        <StatCard label="进行中任务" value={stats.inProgress} sub={`${stats.total} 个总计`} />
        <StatCard label="今日截止" value={stats.todayDue} sub="due today" />
        <StatCard label="完成率" value={`${stats.rate}%`} sub={`${stats.done} / ${stats.total} 已完成`} />
      </div>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-ink-2">项目</h2>
          <span className="font-mono text-[11px] tabular-nums text-ink-5">{projects.length} 个</span>
        </div>
        {projects.length === 0 ? (
          <Card>
            <Empty
              title="还没有项目"
              hint="创建一个项目，开始组织你的任务与笔记。"
              action={
                <Button size="sm" onClick={() => setOpen(true)}>
                  新建项目
                </Button>
              }
            />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {projects.map((p, i) => (
              <div key={p.id} className="animate-fadeUp" style={{ animationDelay: `${i * 30}ms` }}>
                <ProjectCard
                  project={p}
                  tasks={tasks.filter((t) => t.project_id === p.id)}
                  notes={notes.filter((n) => n.project_id === p.id)}
                  layer={layer}
                  canConfigure={canConfigure}
                  onOpen={() => onOpenProject(p.id)}
                  onConfigureDeploy={() => openConfigure(p)}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <Dialog open={open} onClose={() => setOpen(false)} title="新建项目">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">项目名称</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：CrossBorder AI" autoFocus />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">描述（可选）</label>
            <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="一句话说明这个项目" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">仓库地址（可选）</label>
            <Input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/…" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">线上地址（可选）</label>
            <Input value={deployUrl} onChange={(e) => setDeployUrl(e.target.value)} placeholder="https://… 已部署的站点" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">部署 workflow（可选）</label>
            <Input value={deployWorkflow} onChange={(e) => setDeployWorkflow(e.target.value)} placeholder="deploy.yml" />
            <span className="text-[11px] text-ink-5">
              仓库里 .github/workflows/ 下的文件名。填了才会出现「部署」按钮，且该 workflow 必须声明 workflow_dispatch。
            </span>
          </div>
          <Button onClick={submit} loading={busy} disabled={!name.trim()}>
            创建
          </Button>
        </div>
      </Dialog>

      <Dialog open={configuring !== null} onClose={() => setConfiguring(null)} title="部署配置">
        <div className="flex flex-col gap-4">
          <div className="text-[12px] text-ink-3">
            项目：<span className="text-ink">{configuring?.name}</span>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] text-ink-3">部署 workflow 文件名</label>
            <Input
              value={configWorkflow}
              onChange={(e) => setConfigWorkflow(e.target.value)}
              placeholder="deploy.yml"
              autoFocus
            />
            <span className="text-[11px] text-ink-5">
              如 deploy.yml。必须是仓库 .github/workflows/ 下真实存在的文件，且声明了 workflow_dispatch，
              否则触发时 GitHub 会返回 422。
            </span>
          </div>
          {configError && <div className="text-[11.5px] text-error">{configError}</div>}
          <div className="flex items-center gap-2">
            <Button onClick={() => saveConfigure(false)} disabled={!configWorkflow.trim()}>
              保存
            </Button>
            {configuring?.deploy_workflow && (
              <Button variant="danger" onClick={() => saveConfigure(true)}>
                关闭远程部署
              </Button>
            )}
            <Button variant="ghost" onClick={() => setConfiguring(null)}>
              取消
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
