import { useState, type FormEvent } from 'react'
import { cn } from '../lib/cn'
import type { DataLayer } from '../lib/view'
import { NoteCard } from '../components/NoteCard'
import { StatusBadge } from '../components/status'
import { TaskItem } from '../components/TaskItem'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Empty } from '../components/ui/empty'
import { Input, Textarea } from '../components/ui/input'
import type { Note, Project, Task } from '../types'
import { DocTab } from './DocTab'
import { KanbanBoard } from '../components/KanbanBoard'
import { KnowledgeTab } from './KnowledgeTab'
import { CodeAnalysisTab } from './CodeAnalysisTab'

export function ProjectPage({
  project,
  tasks,
  notes,
  layer,
  onBack,
  onCreateTask,
  onToggleTask,
  onMoveTask,
  onDeleteTask,
  onCreateNote,
  onUpdateNote,
  onDeleteNote,
  onDeleteProject,
  canConfigureCodeAnalysis,
}: {
  project?: Project
  tasks: Task[]
  notes: Note[]
  layer: DataLayer
  onBack: () => void
  onCreateTask: (t: { project_id: string; title: string; priority?: string; status?: string }) => Promise<void>
  onToggleTask: (task: Task) => Promise<void>
  onMoveTask: (task: Task, status: string) => Promise<void>
  onDeleteTask: (id: string) => Promise<void>
  onCreateNote: (n: { project_id: string; title: string; content?: string }) => Promise<void>
  onUpdateNote: (id: string, patch: Partial<Note>) => Promise<void>
  onDeleteNote: (id: string) => Promise<void>
  onDeleteProject: (id: string) => Promise<void>
  canConfigureCodeAnalysis: boolean
}) {
  const [showTaskForm, setShowTaskForm] = useState(false)
  const [taskMode, setTaskMode] = useState<'list' | 'board'>('list')
  const [tab, setTab] = useState<'overview' | 'knowledge' | 'docs' | 'code-analysis'>('overview')
  const [taskTitle, setTaskTitle] = useState('')
  const [priority, setPriority] = useState('medium')
  const [noteTitle, setNoteTitle] = useState('')
  const [noteContent, setNoteContent] = useState('')

  if (!project) {
    return (
      <div className="mx-auto max-w-7xl p-6">
        <Card>
          <Empty
            title="项目不存在或已被删除"
            action={
              <Button variant="secondary" size="sm" onClick={onBack}>
                返回工作台
              </Button>
            }
          />
        </Card>
      </div>
    )
  }

  const done = tasks.filter((t) => t.status === 'done').length
  const projectId = project.id
  const projectName = project.name

  function submitTask(e: FormEvent) {
    e.preventDefault()
    if (!taskTitle.trim()) return
    void onCreateTask({ project_id: projectId, title: taskTitle.trim(), priority })
    setTaskTitle('')
    setPriority('medium')
  }

  function submitNote(e: FormEvent) {
    e.preventDefault()
    if (!noteTitle.trim()) return
    void onCreateNote({ project_id: projectId, title: noteTitle.trim(), content: noteContent })
    setNoteTitle('')
    setNoteContent('')
  }

  function removeProject() {
    if (window.confirm(`确定删除项目「${projectName}」？其任务与笔记将一并删除。`)) {
      void onDeleteProject(projectId)
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-[12.5px] text-ink-3 transition-colors hover:text-gold"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M19 12H5m7-7-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        返回工作台
      </button>

      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[20px] font-[650] tracking-tight text-ink">{project.name}</h1>
          <StatusBadge status={project.status} />
          <Button variant="ghost" size="sm" className="text-error hover:bg-error/10" onClick={removeProject}>
            删除项目
          </Button>
        </div>
        {project.description && <p className="mt-1.5 text-[12.5px] text-ink-3">{project.description}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge tone="gold" dot={false}>
            <span className="font-mono tabular-nums">{tasks.length}</span> 任务
          </Badge>
          <Badge tone="success" dot={false}>
            <span className="font-mono tabular-nums">{done}</span> 完成
          </Badge>
          <Badge tone="info" dot={false}>
            <span className="font-mono tabular-nums">{notes.length}</span> 笔记
          </Badge>
        </div>
      </header>

      <div className="flex items-center gap-1 border-b border-line" role="tablist" aria-label="项目内容">
        <button
          role="tab"
          aria-selected={tab === 'overview'}
          aria-controls="project-overview"
          id="tab-overview"
          onClick={() => setTab('overview')}
          className={cn(
            'relative -mb-px border-b-2 px-3 pb-2 pt-1 text-[13px] transition-colors',
            tab === 'overview' ? 'border-gold text-gold' : 'border-transparent text-ink-3 hover:text-ink',
          )}
        >
          概览
        </button>
        <button
          role="tab"
          aria-selected={tab === 'knowledge'}
          aria-controls="project-knowledge"
          id="tab-knowledge"
          onClick={() => setTab('knowledge')}
          className={cn(
            'relative -mb-px border-b-2 px-3 pb-2 pt-1 text-[13px] transition-colors',
            tab === 'knowledge' ? 'border-gold text-gold' : 'border-transparent text-ink-3 hover:text-ink',
          )}
        >
          知识库
        </button>
        <button
          role="tab"
          aria-selected={tab === 'docs'}
          aria-controls="project-docs"
          id="tab-docs"
          onClick={() => setTab('docs')}
          className={cn(
            'relative -mb-px border-b-2 px-3 pb-2 pt-1 text-[13px] transition-colors',
            tab === 'docs' ? 'border-gold text-gold' : 'border-transparent text-ink-3 hover:text-ink',
          )}
        >
          文档
        </button>
        <button
          role="tab"
          aria-selected={tab === 'code-analysis'}
          aria-controls="project-code-analysis"
          id="tab-code-analysis"
          onClick={() => setTab('code-analysis')}
          className={cn(
            'relative -mb-px border-b-2 px-3 pb-2 pt-1 text-[13px] transition-colors',
            tab === 'code-analysis' ? 'border-gold text-gold' : 'border-transparent text-ink-3 hover:text-ink',
          )}
        >
          代码分析
        </button>
      </div>

      {tab === 'overview' ? (
        <div
          id="project-overview"
          role="tabpanel"
          aria-labelledby="tab-overview"
          className="grid gap-6 lg:grid-cols-7"
        >
          <section className={cn('lg:col-span-4', taskMode === 'board' && 'lg:col-span-7')}>
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex items-center gap-2">
                <h2 className="text-[13px] font-semibold text-ink-2">任务</h2>
                {/* 列表/看板视图切换：看板 = 拖拽列改状态 */}
                <div className="flex overflow-hidden rounded-md border border-line-soft">
                  <button
                    onClick={() => setTaskMode('list')}
                    className={cn(
                      'px-2 py-0.5 text-[11px] transition-colors',
                      taskMode === 'list' ? 'bg-gold-primary/15 text-gold' : 'text-ink-4 hover:text-ink',
                    )}
                  >
                    列表
                  </button>
                  <button
                    onClick={() => setTaskMode('board')}
                    className={cn(
                      'px-2 py-0.5 text-[11px] transition-colors',
                      taskMode === 'board' ? 'bg-gold-primary/15 text-gold' : 'text-ink-4 hover:text-ink',
                    )}
                  >
                    看板
                  </button>
                </div>
              </div>
              {taskMode === 'list' && (
                <Button size="sm" variant="secondary" onClick={() => setShowTaskForm((s) => !s)}>
                  {showTaskForm ? '收起' : '+ 添加任务'}
                </Button>
              )}
            </div>
            {showTaskForm && (
              <form onSubmit={submitTask} className="flex gap-2 border-b border-line bg-elev1 p-3">
                <Input
                  value={taskTitle}
                  onChange={(e) => setTaskTitle(e.target.value)}
                  placeholder="任务标题"
                  className="flex-1"
                  autoFocus
                />
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  className="h-9 rounded-lg border border-line-soft bg-elev1 px-2 text-[12px] text-ink-2 focus:border-gold-primary/60 focus:outline-none"
                >
                  <option value="high">高</option>
                  <option value="medium">中</option>
                  <option value="low">低</option>
                </select>
                <Button size="sm" type="submit" disabled={!taskTitle.trim()}>
                  创建
                </Button>
              </form>
            )}
            {taskMode === 'board' ? (
              // 看板模式：三列拖拽，空列自带「拖拽任务到这里」引导，不再用空态卡片
              <KanbanBoard
                tasks={tasks}
                projectId={projectId}
                onMoveTask={onMoveTask}
                onCreateTask={onCreateTask}
                onDeleteTask={onDeleteTask}
              />
            ) : tasks.length === 0 ? (
              <Empty
                title="还没有任务"
                hint="添加第一个任务，开始推进这个项目。"
                action={
                  <Button size="sm" onClick={() => setShowTaskForm(true)}>
                    添加任务
                  </Button>
                }
              />
            ) : (
              <div>
                {tasks.map((t) => (
                  <TaskItem
                    key={t.id}
                    task={t}
                    onToggle={() => void onToggleTask(t)}
                    onDelete={() => void onDeleteTask(t.id)}
                  />
                ))}
              </div>
            )}
          </Card>
        </section>

        <section className="lg:col-span-3">
          <Card className="space-y-4 p-4">
            <h2 className="text-[13px] font-semibold text-ink-2">笔记</h2>
            <form onSubmit={submitNote} className="flex flex-col gap-2">
              <Input value={noteTitle} onChange={(e) => setNoteTitle(e.target.value)} placeholder="笔记标题" />
              <Textarea
                rows={2}
                value={noteContent}
                onChange={(e) => setNoteContent(e.target.value)}
                placeholder="随手记，支持 AI 相关备忘…"
              />
              <Button size="sm" type="submit" disabled={!noteTitle.trim()}>
                保存笔记
              </Button>
            </form>
            <div className="flex flex-col gap-3 pt-1">
              {notes.length === 0 ? (
                <p className="py-6 text-center text-[12px] text-ink-5">还没有笔记</p>
              ) : (
                notes.map((n) => (
                  <NoteCard
                    key={n.id}
                    note={n}
                    onUpdate={onUpdateNote}
                    onDelete={() => void onDeleteNote(n.id)}
                  />
                ))
              )}
            </div>
          </Card>
          </section>
        </div>
      ) : tab === 'knowledge' ? (
        <div id="project-knowledge" role="tabpanel" aria-labelledby="tab-knowledge">
          <KnowledgeTab key={project.id} layer={layer} project={project} />
        </div>
      ) : tab === 'docs' ? (
        <div id="project-docs" role="tabpanel" aria-labelledby="tab-docs">
          <DocTab key={project.id} layer={layer} project={project} />
        </div>
      ) : (
        <div id="project-code-analysis" role="tabpanel" aria-labelledby="tab-code-analysis">
          <CodeAnalysisTab
            key={project.id}
            layer={layer}
            project={project}
            canConfigure={canConfigureCodeAnalysis}
          />
        </div>
      )}
    </div>
  )
}
