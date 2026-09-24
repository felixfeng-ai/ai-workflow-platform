import type {
  AgentInfo,
  AgentParam,
  AgentRun,
  AuthResponse,
  CopilotEvent,
  CopilotMessage,
  CustomAgentRead,
  DeployRun,
  Doc,
  InviteResult,
  KnowledgeDocument,
  KnowledgeResponse,
  Note,
  Notification,
  NotificationType,
  Paginated,
  ParamTemplate,
  Project,
  ScanResult,
  Schedule,
  Task,
  TeamMember,
  UnreadCount,
  User,
  Workflow,
  WorkflowDraft,
  WorkflowEdge,
  WorkflowRun,
  WorkflowStep,
  WritingEvent,
  WritingOperation,
} from '../types'
import { BASE } from './mode'

const TOKEN_KEY = 'ph_token'
const USER_KEY = 'ph_user'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getSessionUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export function setSession(r: AuthResponse) {
  localStorage.setItem(TOKEN_KEY, r.access_token)
  localStorage.setItem(USER_KEY, JSON.stringify(r.user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) {
    clearSession()
    window.location.reload()
    throw new ApiError(401, '登录已过期')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail ?? JSON.stringify(j)
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, String(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** multipart 文件上传：浏览器自动带 boundary，不设 Content-Type。 */
async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: form })
  if (res.status === 401) {
    clearSession()
    window.location.reload()
    throw new ApiError(401, '登录已过期')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail ?? JSON.stringify(j)
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, String(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  login: (email: string, password: string) =>
    request<AuthResponse>('POST', '/api/auth/login', { email, password }),
  /** 访客体验入口：免注册换取共享演示租户的 token（后端保证该账号与样例数据存在） */
  guestLogin: () => request<AuthResponse>('POST', '/api/auth/guest'),
  register: (email: string, password: string, name: string, inviteCode?: string) =>
    request<AuthResponse>('POST', '/api/auth/register', {
      email,
      password,
      name,
      ...(inviteCode ? { invite_code: inviteCode } : {}),
    }),
  // ---------- 团队管理 ----------
  listTeamMembers: () => request<TeamMember[]>('GET', '/api/team/members'),
  createInvite: (email: string, role: 'member' | 'readonly') =>
    request<InviteResult>('POST', '/api/team/invites', { email, role }),
  acceptInvite: (code: string) => request<User>('POST', '/api/team/invites/accept', { code }),
  updateMemberRole: (userId: string, role: string) =>
    request<TeamMember>('PATCH', `/api/team/members/${userId}`, { role }),
  removeMember: (userId: string) => request<void>('DELETE', `/api/team/members/${userId}`),
  listProjects: () => request<Project[]>('GET', '/api/projects'),
  createProject: (p: { name: string; description?: string; repo_url?: string; deploy_url?: string; local_path?: string; deploy_workflow?: string }) =>
    request<Project>('POST', '/api/projects', p),
  /** 局部更新：只传要改的字段。deploy_workflow 传 null = 关闭该项目的远程部署。 */
  updateProject: (id: string, patch: Partial<{ name: string; description: string | null; repo_url: string | null; deploy_url: string | null; local_path: string | null; deploy_workflow: string | null }>) =>
    request<Project>('PATCH', `/api/projects/${id}`, patch),
  deleteProject: (id: string) => request<void>('DELETE', `/api/projects/${id}`),
  // 远程部署：触发 GitHub Actions。202 = 已受理，不代表部署成功，
  // 需轮询 getDeployment 拿实时状态。仅 owner 可用（member 会 403）。
  deployProject: (projectId: string) =>
    request<DeployRun>('POST', `/api/projects/${projectId}/deploy`),
  listDeployments: (projectId: string, limit = 10) =>
    request<DeployRun[]>('GET', `/api/projects/${projectId}/deployments?limit=${limit}`),
  getDeployment: (projectId: string, runId: string) =>
    request<DeployRun>('GET', `/api/projects/${projectId}/deployments/${runId}`),
  listTasks: (projectId?: string) =>
    request<Task[]>('GET', `/api/tasks${projectId ? `?project_id=${projectId}` : ''}`),
  createTask: (t: { project_id: string; title: string; priority?: string; description?: string; status?: string }) =>
    request<Task>('POST', '/api/tasks', t),
  updateTask: (id: string, patch: Partial<Task>) =>
    request<Task>('PATCH', `/api/tasks/${id}`, patch),
  deleteTask: (id: string) => request<void>('DELETE', `/api/tasks/${id}`),
  listNotes: (projectId?: string) =>
    request<Note[]>('GET', `/api/notes${projectId ? `?project_id=${projectId}` : ''}`),
  createNote: (n: { project_id: string; title: string; content?: string }) =>
    request<Note>('POST', '/api/notes', n),
  updateNote: (id: string, patch: Partial<Note>) =>
    request<Note>('PATCH', `/api/notes/${id}`, patch),
  deleteNote: (id: string) => request<void>('DELETE', `/api/notes/${id}`),
  // ---------- Markdown 文档 ----------
  listDocs: (projectId?: string) =>
    request<Doc[]>('GET', `/api/docs${projectId ? `?project_id=${projectId}` : ''}`),
  createDoc: (d: { project_id: string; title: string; content?: string }) =>
    request<Doc>('POST', '/api/docs', d),
  getDoc: (id: string) => request<Doc>('GET', `/api/docs/${id}`),
  updateDoc: (id: string, patch: Partial<Doc>) =>
    request<Doc>('PATCH', `/api/docs/${id}`, patch),
  deleteDoc: (id: string) => request<void>('DELETE', `/api/docs/${id}`),
  chat: (query: string) => request<{ answer: string }>('POST', '/api/ai/chat', { query }),
  // ---------- Agent ----------
  listAgents: () => request<AgentInfo[]>('GET', '/api/agents'),
  runAgent: (agentKey: string, body: { params?: Record<string, unknown>; project_id?: string }) =>
    request<{ run_id: string; status: string }>('POST', `/api/agents/${agentKey}/run`, body),
  listAgentRuns: (opts?: { agent_key?: string; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (opts?.agent_key) q.set('agent_key', opts.agent_key)
    q.set('page', String(opts?.page ?? 1))
    q.set('page_size', String(opts?.page_size ?? 20))
    return request<Paginated<AgentRun>>('GET', `/api/agents/runs?${q}`)
  },
  getAgentRun: (runId: string) => request<AgentRun>('GET', `/api/agents/runs/${runId}`),
  // ---------- 自定义 Agent（DB 持久化） ----------
  createAgent: (a: { name: string; description?: string | null; prompt: string; param_schema: AgentParam[] }) =>
    request<CustomAgentRead>('POST', '/api/agents', a),
  updateAgent: (key: string, patch: Partial<{ name: string; description?: string | null; prompt: string; param_schema: AgentParam[] }>) =>
    request<CustomAgentRead>('PATCH', `/api/agents/${key}`, patch),
  deleteAgent: (key: string) => request<void>('DELETE', `/api/agents/${key}`),
  // ---------- 参数预置模板 ----------
  listParamTemplates: (agentKey?: string) =>
    request<ParamTemplate[]>('GET', `/api/param-templates${agentKey ? `?agent_key=${agentKey}` : ''}`),
  createParamTemplate: (t: { name: string; agent_key: string; params: Record<string, unknown> }) =>
    request<ParamTemplate>('POST', '/api/param-templates', t),
  updateParamTemplate: (id: string, patch: Partial<{ name: string; params: Record<string, unknown> }>) =>
    request<ParamTemplate>('PATCH', `/api/param-templates/${id}`, patch),
  deleteParamTemplate: (id: string) => request<void>('DELETE', `/api/param-templates/${id}`),
  // ---------- 工作流 ----------
  listWorkflows: () => request<Workflow[]>('GET', '/api/workflows'),
  createWorkflow: (w: {
    name: string
    description?: string
    steps: WorkflowStep[]
    /** 分支连线；null/缺省 = 线性（后端按 steps 顺序自动连成链） */
    edges?: WorkflowEdge[] | null
    schedule?: Schedule | null
  }) => request<Workflow>('POST', '/api/workflows', w),
  updateWorkflow: (id: string, patch: Partial<Workflow>) =>
    request<Workflow>('PATCH', `/api/workflows/${id}`, patch),
  deleteWorkflow: (id: string) => request<void>('DELETE', `/api/workflows/${id}`),
  /** 一句话起草：只返回草稿，不落库（用户在画布上确认后才 createWorkflow） */
  draftWorkflow: (intent: string) =>
    request<WorkflowDraft>('POST', '/api/workflows/draft', { intent }),
  runWorkflow: (id: string) =>
    request<{ run_id: string; status: string }>('POST', `/api/workflows/${id}/run`),
  /** 断点续跑：复用同一个 run，只重跑失败的那一步及其下游 */
  resumeWorkflowRun: (runId: string) =>
    request<{ run_id: string; status: string }>('POST', `/api/workflows/runs/${runId}/resume`),
  listWorkflowRuns: (opts?: { page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    q.set('page', String(opts?.page ?? 1))
    q.set('page_size', String(opts?.page_size ?? 20))
    return request<Paginated<WorkflowRun>>('GET', `/api/workflows/runs?${q}`)
  },
  getWorkflowRun: (runId: string) => request<WorkflowRun>('GET', `/api/workflows/runs/${runId}`),
  // ---------- 知识库 RAG ----------
  listDocuments: (projectId: string) =>
    request<KnowledgeDocument[]>('GET', `/api/projects/${projectId}/documents`),
  uploadDocument: (projectId: string, file: File) =>
    upload<KnowledgeDocument>(`/api/projects/${projectId}/documents`, file),
  deleteDocument: (projectId: string, documentId: string) =>
    request<void>('DELETE', `/api/projects/${projectId}/documents/${documentId}`),
  scanDocuments: (projectId: string) =>
    request<ScanResult>('POST', `/api/projects/${projectId}/documents/scan`),
  queryKnowledge: (projectId: string, query: string) =>
    request<KnowledgeResponse>('POST', `/api/projects/${projectId}/knowledge`, { query }),
  // ---------- AI 副驾（Copilot）：SSE 流式对话 ----------
  async *streamCopilot(messages: CopilotMessage[], projectId?: string): AsyncGenerator<CopilotEvent> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch(`${BASE}/api/copilot/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ messages, project_id: projectId ?? null }),
    })
    if (res.status === 401) {
      clearSession()
      window.location.reload()
      throw new ApiError(401, '登录已过期')
    }
    if (!res.ok) {
      let detail = res.statusText
      try {
        const j = await res.json()
        detail = j.detail ?? JSON.stringify(j)
      } catch {
        /* keep default */
      }
      throw new ApiError(res.status, String(detail))
    }
    const reader = res.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以空行分隔；逐块解析 data: 行，非 data 行（心跳等）忽略
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const payload = line.slice(5).trim()
        if (!payload) continue
        try {
          yield JSON.parse(payload) as CopilotEvent
        } catch {
          /* 忽略无法解析的数据行 */
        }
      }
    }
  },
  // ---------- AI 写作（续写/润色/总结）：SSE 流式 ----------
  async *streamWriting(operation: WritingOperation, text: string): AsyncGenerator<WritingEvent> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch(`${BASE}/api/writing`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ operation, text }),
    })
    if (res.status === 401) {
      clearSession()
      window.location.reload()
      throw new ApiError(401, '登录已过期')
    }
    if (!res.ok) {
      let detail = res.statusText
      try {
        const j = await res.json()
        detail = j.detail ?? JSON.stringify(j)
      } catch {
        /* keep default */
      }
      throw new ApiError(res.status, String(detail))
    }
    const reader = res.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以空行分隔；逐块解析 data: 行，非 data 行（心跳等）忽略
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? ''
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        const payload = line.slice(5).trim()
        if (!payload) continue
        try {
          yield JSON.parse(payload) as WritingEvent
        } catch {
          /* 忽略无法解析的数据行 */
        }
      }
    }
  },
  // ---------- 站内通知（Notification Center） ----------
  listNotifications: (opts?: { unread_only?: boolean; type?: NotificationType; page?: number; page_size?: number }) => {
    const q = new URLSearchParams()
    if (opts?.unread_only) q.set('unread_only', 'true')
    if (opts?.type) q.set('type', opts.type)
    q.set('page', String(opts?.page ?? 1))
    q.set('page_size', String(opts?.page_size ?? 20))
    return request<Paginated<Notification>>('GET', `/api/notifications?${q}`)
  },
  getUnreadCount: () => request<UnreadCount>('GET', '/api/notifications/unread-count'),
  markNotificationRead: (id: string) => request<void>('POST', `/api/notifications/${id}/read`),
  markAllNotificationsRead: () => request<{ updated: number }>('POST', '/api/notifications/read-all'),
  deleteNotification: (id: string) => request<void>('DELETE', `/api/notifications/${id}`),
}
