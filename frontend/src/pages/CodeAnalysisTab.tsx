import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { cn } from '../lib/cn'
import type { DataLayer } from '../lib/view'
import type {
  CodeAnalysisConfig,
  CodeAnalysisRun,
  CodeAnalysisRunSummary,
  Project,
} from '../types'
import { Badge, type BadgeTone } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Empty } from '../components/ui/empty'
import { Input, Textarea } from '../components/ui/input'

const STATUS_META: Record<string, { label: string; tone: BadgeTone }> = {
  pending: { label: '等待分析', tone: 'neutral' },
  running: { label: '分析中', tone: 'info' },
  succeeded: { label: '已完成', tone: 'success' },
  partial: { label: '部分完成', tone: 'warning' },
  failed: { label: '失败', tone: 'error' },
}

function severityTone(severity: string): BadgeTone {
  if (severity === 'critical' || severity === 'high' || severity === 'error') return 'error'
  if (severity === 'medium' || severity === 'warning') return 'warning'
  return 'info'
}

function shortSha(sha: string): string {
  return sha.slice(0, 8)
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-line-soft bg-elev1 px-3 py-2.5">
      <div className="text-[10.5px] text-ink-4">{label}</div>
      <div className="mt-0.5 font-mono text-[18px] font-semibold tabular-nums text-ink">{value}</div>
    </div>
  )
}

function Section({
  title,
  children,
  className,
}: {
  title: string
  children: ReactNode
  className?: string
}) {
  return (
    <Card className={cn('p-4', className)}>
      <h3 className="mb-3 text-[13px] font-semibold text-ink-2">{title}</h3>
      {children}
    </Card>
  )
}

export function CodeAnalysisTab({
  project,
  layer,
  canConfigure,
}: {
  project: Project
  layer: DataLayer
  canConfigure: boolean
}) {
  const [config, setConfig] = useState<CodeAnalysisConfig | null>(null)
  const [runs, setRuns] = useState<CodeAnalysisRunSummary[]>([])
  const [selected, setSelected] = useState<CodeAnalysisRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [branchFilter, setBranchFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [repoUrl, setRepoUrl] = useState(project.repo_url ?? '')
  const [accessToken, setAccessToken] = useState('')
  const [patterns, setPatterns] = useState('feature/*\nfix/*')
  const [webhookSecret, setWebhookSecret] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [copiedField, setCopiedField] = useState('')
  const [guideExpanded, setGuideExpanded] = useState<boolean | null>(null)

  const loadConfig = useCallback(async () => {
    try {
      setConfig(await layer.getCodeAnalysisConfig(project.id))
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载代码分析失败')
    }
  }, [layer, project.id])

  const loadRuns = useCallback(async () => {
    try {
      const result = await layer.listCodeAnalysisRuns(project.id, {
        page,
        page_size: pageSize,
        keyword,
        status: statusFilter || undefined,
        branch: branchFilter || undefined,
        severity: severityFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      setRuns(result.items)
      setTotal(result.total)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载代码分析失败')
    } finally {
      setLoading(false)
    }
  }, [
    branchFilter,
    dateFrom,
    dateTo,
    keyword,
    layer,
    page,
    pageSize,
    project.id,
    severityFilter,
    statusFilter,
  ])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (!config || config.webhook_connected_at) return
    const timer = window.setInterval(() => void loadConfig(), 5000)
    return () => window.clearInterval(timer)
  }, [config, loadConfig])

  useEffect(() => {
    const timer = window.setTimeout(() => void loadRuns(), 250)
    return () => window.clearTimeout(timer)
  }, [loadRuns])

  useEffect(() => {
    if (!runs.some((run) => run.status === 'pending' || run.status === 'running')) return
    const timer = window.setInterval(() => void loadRuns(), 3000)
    return () => window.clearInterval(timer)
  }, [loadRuns, runs])

  function resetFilters() {
    setKeyword('')
    setStatusFilter('')
    setBranchFilter('')
    setSeverityFilter('')
    setDateFrom('')
    setDateTo('')
    setPage(1)
  }

  async function saveConfig(e: FormEvent) {
    e.preventDefault()
    if (!repoUrl.trim()) return
    setSaving(true)
    setError('')
    try {
      const created = await layer.configureCodeAnalysis(project.id, {
        repo_url: repoUrl.trim(),
        access_token: accessToken.trim(),
        branch_patterns: patterns
          .split(/\n|,/)
          .map((item) => item.trim())
          .filter(Boolean),
        enabled: true,
      })
      setConfig(created)
      setGuideExpanded(true)
      setWebhookSecret(created.webhook_secret ?? '')
      setAccessToken('')
      setEditing(false)
      await Promise.all([loadConfig(), loadRuns()])
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  async function verify() {
    setSaving(true)
    try {
      setConfig(await layer.verifyCodeAnalysisConfig(project.id))
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '验证失败')
    } finally {
      setSaving(false)
    }
  }

  async function rotateSecret() {
    if (
      !window.confirm(
        '重新生成后，GitHub Webhook 中的旧 Secret 会立即失效。确认生成新 Secret？',
      )
    ) {
      return
    }
    setSaving(true)
    setError('')
    try {
      const rotated = await layer.rotateCodeAnalysisSecret(project.id)
      setConfig(rotated)
      setWebhookSecret(rotated.webhook_secret ?? '')
      setGuideExpanded(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新生成 Secret 失败')
    } finally {
      setSaving(false)
    }
  }

  async function removeConfig() {
    if (!window.confirm('删除仓库连接后，后续 push 将不再自动分析。确定删除？')) return
    try {
      await layer.deleteCodeAnalysisConfig(project.id)
      setConfig(null)
      setGuideExpanded(null)
      setWebhookSecret('')
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除配置失败')
    }
  }

  async function openRun(run: CodeAnalysisRunSummary) {
    try {
      setSelected(await layer.getCodeAnalysisRun(project.id, run.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载报告失败')
    }
  }

  async function copy(value: string, field: string) {
    await navigator.clipboard.writeText(value)
    setCopiedField(field)
    window.setTimeout(() => setCopiedField(''), 1500)
  }

  async function downloadSelected() {
    if (!selected) return
    setDownloading(true)
    setError('')
    try {
      const blob = await layer.downloadCodeAnalysisDocx(project.id, selected.id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${project.name}-代码分析-${selected.after_sha.slice(0, 8)}.docx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : '下载文档失败')
    } finally {
      setDownloading(false)
    }
  }

  if (loading) {
    return <Card className="h-48 animate-pulse bg-elev1" />
  }

  const webhookUrl = config ? `${window.location.origin}${config.webhook_path}` : ''
  const webhookConnected = Boolean(config?.webhook_connected_at)
  const showGuide = config ? (guideExpanded ?? !webhookConnected) : false

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-lg border border-error/25 bg-error/10 px-3 py-2 text-[12px] text-error">
          {error}
        </div>
      )}

      {selected ? (
        <RunDetail
          report={selected}
          onBack={() => setSelected(null)}
          onDownload={() => void downloadSelected()}
          downloading={downloading}
        />
      ) : (
        <>
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[14px] font-semibold text-ink">GitHub 提交分析</h2>
                {config ? (
                  <p className="mt-1 text-[12px] text-ink-3">
                    {config.repo_full_name} · 默认分支 {config.default_branch} ·{' '}
                    {config.branch_patterns.join('、')}
                  </p>
                ) : (
                  <p className="mt-1 text-[12px] text-ink-3">绑定仓库并接收 push 事件后自动生成报告。</p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {config && (
                  <Badge tone={config.enabled ? 'success' : 'neutral'}>
                    {config.enabled ? '仓库已连接' : '已停用'}
                  </Badge>
                )}
                {canConfigure && config && (
                  <>
                    <Button size="sm" variant="secondary" loading={saving} onClick={() => void verify()}>
                      验证连接
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)}>
                      重新配置
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => void removeConfig()}>
                      删除
                    </Button>
                  </>
                )}
              </div>
            </div>

            {config && (
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-line-soft bg-elev1 p-3">
                  <div className="text-[10.5px] font-medium text-ink-4">仓库连接</div>
                  <div className="mt-1 text-[12px] text-ink-2">
                    {config.enabled ? '平台已可读取仓库，等待 GitHub 发送 Push' : '仓库连接已停用'}
                  </div>
                </div>
                <div className="rounded-lg border border-line-soft bg-elev1 p-3">
                  <div className="text-[10.5px] font-medium text-ink-4">最近连接检查</div>
                  <div className="mt-1 text-[12px] text-ink-2">
                    {config.last_verified_at ? new Date(config.last_verified_at).toLocaleString('zh-CN') : '尚未验证'}
                  </div>
                  {config.last_error && <div className="mt-1 text-[11px] text-error">{config.last_error}</div>}
                </div>
              </div>
            )}

            {(editing || (!config && canConfigure)) && (
              <form onSubmit={saveConfig} className="mt-4 space-y-3 border-t border-line pt-4">
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="space-y-1">
                    <span className="text-[11.5px] text-ink-3">GitHub 仓库地址</span>
                    <Input
                      value={repoUrl}
                      onChange={(e) => setRepoUrl(e.target.value)}
                      placeholder="https://github.com/owner/repo"
                    />
                  </label>
                  <label className="space-y-1">
                    <span className="text-[11.5px] text-ink-3">Fine-grained PAT（公开仓库可留空）</span>
                    <Input
                      type="password"
                      value={accessToken}
                      onChange={(e) => setAccessToken(e.target.value)}
                      placeholder="私有仓库填写 Contents: read 和 Metadata: read"
                    />
                  </label>
                </div>
                <label className="block space-y-1">
                  <span className="text-[11.5px] text-ink-3">分析分支规则，一行一条</span>
                  <Textarea
                    rows={3}
                    value={patterns}
                    onChange={(e) => setPatterns(e.target.value)}
                    placeholder={'feature/*\nfix/*'}
                  />
                </label>
                <div className="flex items-center gap-2">
                  <Button size="sm" type="submit" loading={saving} disabled={!repoUrl.trim()}>
                    保存并验证
                  </Button>
                  {config && (
                    <Button size="sm" type="button" variant="ghost" onClick={() => setEditing(false)}>
                      取消
                    </Button>
                  )}
                </div>
              </form>
            )}
          </Card>

          {config &&
            (showGuide ? (
              <WebhookSetupGuide
                config={config}
                webhookUrl={webhookUrl}
                webhookSecret={webhookSecret}
                copiedField={copiedField}
                connected={webhookConnected}
                onCopy={(value, field) => void copy(value, field)}
                onRegenerate={() => void rotateSecret()}
                onCollapse={() => setGuideExpanded(false)}
              />
            ) : webhookConnected ? (
              <WebhookConnectedSummary
                config={config}
                onExpand={() => setGuideExpanded(true)}
              />
            ) : (
              <WebhookCollapsedSummary
                onExpand={() => setGuideExpanded(true)}
              />
            ))}

          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="text-[13px] font-semibold text-ink-2">分析历史</h2>
                <span className="text-[11px] text-ink-4">共 {total} 条</span>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void Promise.all([loadConfig(), loadRuns()])}
              >
                刷新
              </Button>
            </div>
            <Card className="mb-3 p-3">
              <div className="grid items-end gap-3 sm:grid-cols-2 xl:grid-cols-12">
                <label className="space-y-1 sm:col-span-2 xl:col-span-6">
                  <span className="block text-[10.5px] text-ink-4">搜索</span>
                  <Input
                    value={keyword}
                    onChange={(e) => {
                      setKeyword(e.target.value)
                      setPage(1)
                    }}
                    placeholder="Commit、SHA、分支、文件、功能或风险"
                  />
                </label>
                <label className="space-y-1 xl:col-span-3">
                  <span className="block text-[10.5px] text-ink-4">状态</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => {
                      setStatusFilter(e.target.value)
                      setPage(1)
                    }}
                    className="h-9 w-full rounded-lg border border-line-soft bg-elev1 px-2 text-[12px] text-ink-2 focus:border-gold-primary/60 focus:outline-none"
                  >
                    <option value="">全部状态</option>
                    <option value="succeeded">已完成</option>
                    <option value="partial">部分完成</option>
                    <option value="running">分析中</option>
                    <option value="pending">等待分析</option>
                    <option value="failed">失败</option>
                  </select>
                </label>
                <label className="space-y-1 xl:col-span-3">
                  <span className="block text-[10.5px] text-ink-4">风险等级</span>
                  <select
                    value={severityFilter}
                    onChange={(e) => {
                      setSeverityFilter(e.target.value)
                      setPage(1)
                    }}
                    className="h-9 w-full rounded-lg border border-line-soft bg-elev1 px-2 text-[12px] text-ink-2 focus:border-gold-primary/60 focus:outline-none"
                  >
                    <option value="">全部风险</option>
                    <option value="critical">严重及以上</option>
                    <option value="high">高风险及以上</option>
                    <option value="medium">中风险及以上</option>
                    <option value="low">低风险及以上</option>
                  </select>
                </label>
                <label className="space-y-1 sm:col-span-2 xl:col-span-4">
                  <span className="block text-[10.5px] text-ink-4">分支名</span>
                  <Input
                    value={branchFilter}
                    onChange={(e) => {
                      setBranchFilter(e.target.value)
                      setPage(1)
                    }}
                    placeholder="精确分支名"
                  />
                </label>
                <label className="space-y-1 xl:col-span-2">
                  <span className="block text-[10.5px] text-ink-4">开始日期</span>
                  <Input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => {
                      setDateFrom(e.target.value)
                      setPage(1)
                    }}
                  />
                </label>
                <label className="space-y-1 xl:col-span-2">
                  <span className="block text-[10.5px] text-ink-4">结束日期</span>
                  <Input
                    type="date"
                    value={dateTo}
                    onChange={(e) => {
                      setDateTo(e.target.value)
                      setPage(1)
                    }}
                  />
                </label>
                <div className="flex items-center justify-end sm:col-span-2 xl:col-span-4">
                  <Button size="sm" variant="ghost" onClick={resetFilters}>
                    清除筛选
                  </Button>
                </div>
              </div>
            </Card>
            {runs.length === 0 ? (
              <Card>
                <Empty
                  title={
                    keyword || statusFilter || branchFilter || severityFilter || dateFrom || dateTo
                      ? '没有匹配的分析报告'
                      : '还没有代码分析报告'
                  }
                  hint={
                    keyword || statusFilter || branchFilter || severityFilter || dateFrom || dateTo
                      ? '调整搜索词或筛选条件后重试。'
                      : '完成仓库配置后，向匹配分支推送代码即可生成第一份报告。'
                  }
                />
              </Card>
            ) : (
              <>
                <div className="space-y-2">
                  {runs.map((run) => {
                    const meta = STATUS_META[run.status] ?? STATUS_META.pending
                    return (
                      <button
                        key={run.id}
                        onClick={() => void openRun(run)}
                        className="flex w-full flex-wrap items-center gap-3 rounded-card border border-line-strong bg-elev2 px-4 py-3 text-left shadow-card transition-colors hover:bg-active/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-primary/60"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-[13px] font-semibold text-ink">
                              {run.head_commit_message || '无提交说明'}
                            </span>
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                            {run.finding_count > 0 && (
                              <Badge tone={severityTone(run.max_severity)}>
                                {run.finding_count} 风险
                              </Badge>
                            )}
                            {run.truncated && <Badge tone="warning">已截断</Badge>}
                          </div>
                          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-4">
                            <span>{run.branch}</span>
                            <span className="font-mono">{shortSha(run.after_sha)}</span>
                            {run.pusher_login && <span>{run.pusher_login}</span>}
                            <span>{new Date(run.created_at).toLocaleString('zh-CN')}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 text-[11.5px] text-ink-3">
                          <span className="font-mono tabular-nums">{run.change_stats?.files ?? 0} 文件</span>
                          <span className="font-mono text-success">+{run.change_stats?.additions ?? 0}</span>
                          <span className="font-mono text-error">-{run.change_stats?.deletions ?? 0}</span>
                        </div>
                      </button>
                    )
                  })}
                </div>
                <div className="mt-3 flex items-center justify-end gap-2">
                  <span className="text-[11px] text-ink-4">
                    第 {page} / {Math.max(1, Math.ceil(total / pageSize))} 页
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                  >
                    上一页
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={page >= Math.max(1, Math.ceil(total / pageSize))}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    下一页
                  </Button>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function WebhookConnectedSummary({
  config,
  onExpand,
}: {
  config: CodeAnalysisConfig
  onExpand: () => void
}) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[14px] font-semibold text-ink">GitHub Webhook 已接通</h2>
            <Badge tone="success">已接通</Badge>
          </div>
          <p className="mt-1 text-[12px] text-ink-3">
            最近事件：{config.webhook_last_event || '未知'}
            {config.webhook_connected_at
              ? ` · ${new Date(config.webhook_connected_at).toLocaleString('zh-CN')}`
              : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={`https://github.com/${config.repo_full_name}/settings/hooks`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-line-strong px-3 text-[12px] font-medium text-ink transition-colors hover:bg-active focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-primary/60"
          >
            管理 GitHub Webhook
          </a>
          <Button size="sm" variant="ghost" onClick={onExpand}>
            查看接入说明
          </Button>
        </div>
      </div>
    </Card>
  )
}

function WebhookCollapsedSummary({ onExpand }: { onExpand: () => void }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[13px] font-semibold text-ink-2">GitHub Webhook 接入说明已收起</h2>
            <Badge tone="neutral">待完成</Badge>
          </div>
          <p className="mt-1 text-[11.5px] text-ink-4">
            添加 Webhook 并推送代码后，平台会自动显示接通状态。
          </p>
        </div>
        <Button size="sm" variant="ghost" onClick={onExpand}>
          展开接入说明
        </Button>
      </div>
    </Card>
  )
}

function WebhookSetupGuide({
  config,
  webhookUrl,
  webhookSecret,
  copiedField,
  connected,
  onCopy,
  onRegenerate,
  onCollapse,
}: {
  config: CodeAnalysisConfig
  webhookUrl: string
  webhookSecret: string
  copiedField: string
  connected: boolean
  onCopy: (value: string, field: string) => void
  onRegenerate: () => void
  onCollapse: () => void
}) {
  const settingsUrl = `https://github.com/${config.repo_full_name}/settings/hooks${
    connected ? '' : '/new'
  }`
  const copyLabel = (field: string) => (copiedField === field ? '已复制' : '复制')
  const fullConfig = [
    'GitHub Webhook 配置',
    `Payload URL: ${webhookUrl}`,
    'Content type: application/json',
    `Secret: ${webhookSecret || '请点击重新生成 Secret'}`,
    'SSL verification: Enable SSL verification',
    'Events: Just the push event',
    'Active: 勾选',
  ].join('\n')

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line p-4">
        <div>
          <h2 className="text-[14px] font-semibold text-ink">
            {connected ? 'GitHub Webhook 接入说明' : '完成 GitHub Webhook 接入'}
          </h2>
          <p className="mt-1 text-[12px] leading-5 text-ink-3">
            {connected
              ? `GitHub 已向平台发送过 ${config.webhook_last_event || '事件'}，后续 Push 会自动生成报告。`
              : '保存配置只完成了平台侧连接。还需要在 GitHub 添加一次 Webhook，Push 后才会自动生成报告。'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={settingsUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 shrink-0 items-center justify-center rounded-lg border border-line-strong px-3 text-[12px] font-medium text-ink transition-colors hover:bg-active focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold-primary/60"
          >
            {connected ? '管理 GitHub Webhook' : '打开 GitHub Webhook 设置'}
          </a>
          <Button size="sm" variant="ghost" onClick={onCollapse}>
            收起说明
          </Button>
        </div>
      </div>

      <ol className="grid gap-3 border-b border-line p-4 md:grid-cols-4">
        {[
          ['1', '打开设置', `仓库 Settings → Webhooks → Add webhook`],
          ['2', '填写连接', '复制下面 Payload URL 与 Secret'],
          ['3', '选择事件', 'Content type 选 JSON，事件选 Just the push event'],
          ['4', '保存并验证', '向匹配分支 Push，GitHub Deliveries 应返回 202'],
        ].map(([number, title, description]) => (
          <li key={number} className="flex gap-2.5">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-gold/30 bg-gold-tint font-mono text-[11px] text-gold">
              {number}
            </span>
            <div>
              <div className="text-[12px] font-semibold text-ink">{title}</div>
              <p className="mt-0.5 text-[11px] leading-5 text-ink-4">{description}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="divide-y divide-line border-b border-line">
        <div className="grid gap-2 px-4 py-3 md:grid-cols-[150px_1fr_64px] md:items-center">
          <span className="text-[11.5px] font-medium text-ink-3">Payload URL *</span>
          <code className="break-all text-[11.5px] text-ink-2">{webhookUrl}</code>
          <Button size="sm" variant="ghost" onClick={() => onCopy(webhookUrl, 'payload')}>
            {copyLabel('payload')}
          </Button>
        </div>
        <div className="grid gap-2 px-4 py-3 md:grid-cols-[150px_1fr_64px] md:items-center">
          <span className="text-[11.5px] font-medium text-ink-3">Content type *</span>
          <code className="text-[11.5px] text-ink-2">application/json</code>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onCopy('application/json', 'content-type')}
          >
            {copyLabel('content-type')}
          </Button>
        </div>
        <div className="grid gap-2 px-4 py-3 md:grid-cols-[150px_1fr_64px] md:items-center">
          <span className="text-[11.5px] font-medium text-ink-3">Secret</span>
          <code className="break-all text-[11.5px] text-ink-2">
            {webhookSecret || '已隐藏，刷新后无法再次查看'}
          </code>
          {webhookSecret ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onCopy(webhookSecret, 'secret')}
            >
              {copyLabel('secret')}
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={onRegenerate}>
              重新生成 Secret
            </Button>
          )}
        </div>
        <div className="grid gap-2 px-4 py-3 md:grid-cols-[150px_1fr] md:items-center">
          <span className="text-[11.5px] font-medium text-ink-3">SSL verification</span>
          <span className="text-[11.5px] text-ink-2">保持 Enable SSL verification</span>
        </div>
        <div className="grid gap-2 px-4 py-3 md:grid-cols-[150px_1fr] md:items-center">
          <span className="text-[11.5px] font-medium text-ink-3">Events *</span>
          <span className="text-[11.5px] text-ink-2">选择 Just the push event，并勾选 Active</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="max-w-2xl text-[11px] leading-5 text-ink-4">
          Secret 只在保存或重新生成时显示一次。如果已经关闭页面，请点击“重新生成”，然后在 GitHub Webhook 中同步更新。
        </p>
        <Button size="sm" variant="secondary" onClick={() => onCopy(fullConfig, 'all')}>
          {copiedField === 'all' ? '已复制全部配置' : '复制全部配置'}
        </Button>
      </div>
    </Card>
  )
}

function RunDetail({
  report,
  onBack,
  onDownload,
  downloading,
}: {
  report: CodeAnalysisRun
  onBack: () => void
  onDownload: () => void
  downloading: boolean
}) {
  const data = report.report
  if (!data) {
    return (
      <Card>
        <Empty
          title={report.status === 'failed' ? '分析失败' : '报告尚未生成'}
          hint={report.error || '稍后刷新查看结果。'}
          action={<Button size="sm" variant="secondary" onClick={onBack}>返回历史</Button>}
        />
      </Card>
    )
  }
  const highRisks = data.security_findings.filter(
    (item) => item.severity === 'high' || item.severity === 'critical' || item.severity === 'error',
  )
  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-[12px] text-ink-3 hover:text-gold">
        ← 返回分析历史
      </button>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] font-semibold text-ink">代码分析报告</h2>
              <Badge tone={(STATUS_META[report.status] ?? STATUS_META.pending).tone}>
                {(STATUS_META[report.status] ?? STATUS_META.pending).label}
              </Badge>
              {highRisks.length > 0 && <Badge tone="error">{highRisks.length} 个高风险</Badge>}
            </div>
            <p className="mt-1 text-[12px] text-ink-3">
              {data.repo_full_name} · {data.branch} · {shortSha(data.after_sha)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {report.ai_provider && (
              <Badge tone="info" dot={false}>
                AI · {report.ai_model || report.ai_provider}
              </Badge>
            )}
            <Button size="sm" variant="secondary" loading={downloading} onClick={onDownload}>
              下载分析报告
            </Button>
          </div>
        </div>
        <p className="mt-4 text-[13px] leading-6 text-ink-2">{data.summary}</p>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label="提交" value={data.change_scale.commits} />
          <Metric label="文件" value={data.change_scale.files} />
          <Metric label="新增" value={`+${data.change_scale.additions}`} />
          <Metric label="删除" value={`-${data.change_scale.deletions}`} />
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="功能点">
          <div className="space-y-2">
            {data.functional_points.map((item, index) => (
              <div key={`${item.title}-${index}`} className="rounded-lg border border-line-soft bg-elev1 p-3">
                <div className="text-[12.5px] font-medium text-ink">{item.title}</div>
                <p className="mt-1 text-[11.5px] leading-5 text-ink-3">{item.description}</p>
                {item.files.length > 0 && (
                  <div className="mt-1.5 font-mono text-[10.5px] text-ink-5">{item.files.join(' · ')}</div>
                )}
              </div>
            ))}
            {data.functional_points.length === 0 && <p className="text-[12px] text-ink-4">暂无功能点摘要。</p>}
          </div>
        </Section>

        <Section title="Commit 摘要">
          <div className="space-y-2">
            {data.commits.map((commit) => (
              <div key={commit.sha} className="rounded-lg border border-line-soft bg-elev1 p-3">
                <div className="font-mono text-[10.5px] text-gold">{shortSha(commit.sha)}</div>
                <div className="mt-1 text-[12px] text-ink-2">{commit.message}</div>
                {commit.author && <div className="mt-1 text-[10.5px] text-ink-5">{commit.author}</div>}
              </div>
            ))}
          </div>
        </Section>

        <Section title="边界与状态管理">
          <div className="space-y-3">
            {data.boundaries.map((item, index) => (
              <div key={`${item.module}-${index}`}>
                <div className="text-[12px] font-medium text-ink">{item.module} · {item.boundary_type}</div>
                <p className="mt-1 text-[11.5px] leading-5 text-ink-3">{item.description}</p>
              </div>
            ))}
            {data.state_management.map((item, index) => (
              <div key={`${item.area}-${index}`} className="border-t border-line-soft pt-3">
                <div className="text-[12px] font-medium text-ink">{item.area}</div>
                <p className="mt-1 text-[11.5px] leading-5 text-ink-3">{item.mechanism}：{item.risk}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section title="影响范围">
          <div className="space-y-2 text-[11.5px] leading-5 text-ink-3">
            {data.impact.direct.map((item) => <p key={item}>• {item}</p>)}
            {data.impact.external_contracts.map((item) => <p key={item}>• 外部契约：{item}</p>)}
            {data.impact.test_gaps.map((item) => <p key={item} className="text-warning">• {item}</p>)}
          </div>
        </Section>
      </div>

      <Section title={`安全发现 · ${data.security_findings.length}`}>
        <div className="space-y-2">
          {data.security_findings.map((finding, index) => (
            <div
              key={`${finding.file}-${finding.line}-${index}`}
              className="rounded-lg border border-line-soft bg-elev1 p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
                <span className="text-[12.5px] font-medium text-ink">{finding.title}</span>
                <Badge tone="neutral" dot={false}>{finding.source}</Badge>
              </div>
              {finding.file && (
                <div className="mt-1.5 font-mono text-[10.5px] text-ink-5">
                  {finding.file}{finding.line ? `:${finding.line}` : ''}
                </div>
              )}
              <p className="mt-1.5 text-[11.5px] leading-5 text-ink-3">{finding.recommendation}</p>
            </div>
          ))}
          {data.security_findings.length === 0 && (
            <p className="text-[12px] text-ink-4">没有确定性风险命中，但这不代表代码绝对安全。</p>
          )}
        </div>
      </Section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="测试缺口">
          {data.test_gaps.length ? (
            <ul className="space-y-2 text-[11.5px] leading-5 text-warning">
              {data.test_gaps.map((item) => <li key={item}>• {item}</li>)}
            </ul>
          ) : (
            <p className="text-[12px] text-ink-4">未检测到明显测试缺口。</p>
          )}
        </Section>
        <Section title="人工复核清单">
          <ul className="space-y-2 text-[11.5px] leading-5 text-ink-3">
            {data.review_checklist.map((item) => <li key={item}>• {item}</li>)}
          </ul>
        </Section>
      </div>
    </div>
  )
}
