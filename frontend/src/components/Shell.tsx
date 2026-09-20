import { useCallback, useEffect, useState } from 'react'
import { api, getSessionUser } from '../lib/api'
import { demoApi } from '../lib/demo'
import type { DataLayer, View } from '../lib/view'
import type { Mode, Note, Project, Task } from '../types'
import { AiPanel } from './AiPanel'
import { MobileNav } from './MobileNav'
import { Sidebar } from './Sidebar'
import { Skeleton } from './ui/skeleton'
import { TopBar } from './TopBar'
import { DashboardPage } from '../pages/DashboardPage'
import { ProjectPage } from '../pages/ProjectPage'
import { AgentsPage } from '../pages/AgentsPage'
import { TeamPage } from '../pages/TeamPage'
import { WorkflowsPage } from '../pages/WorkflowsPage'

export function Shell({
  mode,
  onLogout,
  onRetryConnect,
  retrying,
}: {
  mode: Mode
  onLogout?: () => void
  /** 演示模式横幅上的「重试连接」；由 App 传入，live 模式不传 */
  onRetryConnect?: () => void
  retrying?: boolean
}) {
  const layer: DataLayer = mode === 'demo' ? demoApi : api
  const [view, setView] = useState<View>({ name: 'dashboard' })
  const [projects, setProjects] = useState<Project[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const user = mode === 'live' ? getSessionUser() : null

  const refresh = useCallback(async () => {
    try {
      const [p, t, n] = await Promise.all([
        layer.listProjects(),
        layer.listTasks(),
        layer.listNotes(),
      ])
      setProjects(p)
      setTasks(t)
      setNotes(n)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [layer])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handlers = {
    createProject: async (name: string, description?: string, repoUrl?: string, deployUrl?: string, deployWorkflow?: string) => {
      await layer.createProject({
        name,
        description,
        repo_url: repoUrl || undefined,
        deploy_url: deployUrl || undefined,
        deploy_workflow: deployWorkflow || undefined,
      })
      await refresh()
    },
    configureDeploy: async (id: string, deployWorkflow: string | null) => {
      await layer.updateProject(id, { deploy_workflow: deployWorkflow })
      await refresh()
    },
    deleteProject: async (id: string) => {
      await layer.deleteProject(id)
      await refresh()
      if (view.name === 'project' && view.id === id) setView({ name: 'dashboard' })
    },
    createTask: async (t: { project_id: string; title: string; priority?: string; status?: string }) => {
      await layer.createTask(t)
      await refresh()
    },
    toggleTask: async (task: Task) => {
      await layer.updateTask(task.id, { status: task.status === 'done' ? 'todo' : 'done' })
      await refresh()
    },
    moveTask: async (task: Task, status: string) => {
      await layer.updateTask(task.id, { status })
      await refresh()
    },
    deleteTask: async (id: string) => {
      await layer.deleteTask(id)
      await refresh()
    },
    createNote: async (n: { project_id: string; title: string; content?: string }) => {
      await layer.createNote(n)
      await refresh()
    },
    updateNote: async (id: string, patch: Partial<Note>) => {
      await layer.updateNote(id, patch)
      await refresh()
    },
    deleteNote: async (id: string) => {
      await layer.deleteNote(id)
      await refresh()
    },
  }

  return (
    <div className="flex h-dvh flex-col bg-bg">
      <TopBar mode={mode} layer={layer} user={user} onLogout={onLogout} />
      {/* 演示模式横幅：刻意用 error 红而非品牌金 —— 这代表"你看到的不是真实
          数据"，必须一眼可见（演示投影时尤其），不能伪装成正常状态。 */}
      {mode === 'demo' && (
        <div className="flex items-center gap-2 border-b border-error/25 bg-error/10 px-5 py-2 text-[11.5px] text-error">
          <span className="h-1.5 w-1.5 shrink-0 animate-pulseDot rounded-full bg-error" />
          <span className="shrink-0 font-medium">演示模式</span>
          <span className="min-w-0 flex-1 truncate text-error/85">
            后端未连接：当前为内存样例数据，AI 回复是预设文案，均非真实数据
          </span>
          {onRetryConnect && (
            <button
              onClick={onRetryConnect}
              disabled={retrying}
              className="shrink-0 rounded-md border border-error/35 px-2 py-0.5 font-medium transition-colors duration-150 hover:bg-error/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/50 disabled:opacity-50"
            >
              {retrying ? '重试中…' : '重试连接'}
            </button>
          )}
        </div>
      )}
      {error && (
        <div className="border-b border-error/20 bg-error/10 px-5 py-1.5 text-[11px] text-error">{error}</div>
      )}
      <div className="flex min-h-0 flex-1">
        <Sidebar projects={projects} view={view} onSelect={setView} />
        <main className="min-w-0 flex-1 overflow-y-auto">
          {loading ? (
            <ShellSkeleton />
          ) : view.name === 'dashboard' ? (
            <DashboardPage
              projects={projects}
              tasks={tasks}
              notes={notes}
              layer={layer}
              // 演示模式没有 user（user 恒为 null），也就没有配置部署的入口
              canConfigure={user?.role === 'owner'}
              onOpenProject={(id) => setView({ name: 'project', id })}
              onCreateProject={handlers.createProject}
              onConfigureDeploy={handlers.configureDeploy}
            />
          ) : view.name === 'agents' ? (
            <AgentsPage layer={layer} projects={projects} />
          ) : view.name === 'workflows' ? (
            <WorkflowsPage layer={layer} projects={projects} />
          ) : view.name === 'team' ? (
            <TeamPage layer={layer} currentUser={user} />
          ) : (
            <ProjectPage
              project={projects.find((p) => p.id === view.id)}
              tasks={tasks.filter((t) => t.project_id === view.id)}
              notes={notes.filter((n) => n.project_id === view.id)}
              layer={layer}
              onBack={() => setView({ name: 'dashboard' })}
              onCreateTask={handlers.createTask}
              onToggleTask={handlers.toggleTask}
              onMoveTask={handlers.moveTask}
              onDeleteTask={handlers.deleteTask}
              onCreateNote={handlers.createNote}
              onUpdateNote={handlers.updateNote}
              onDeleteNote={handlers.deleteNote}
              onDeleteProject={handlers.deleteProject}
            />
          )}
        </main>
      </div>
      <MobileNav view={view} onSelect={setView} />
      <AiPanel layer={layer} />
    </div>
  )
}

function ShellSkeleton() {
  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <Skeleton className="h-6 w-32" />
          <Skeleton className="mt-2 h-3 w-56" />
        </div>
        <Skeleton className="h-9 w-24" />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-card" />
        ))}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-44 rounded-card" />
        ))}
      </div>
    </div>
  )
}
