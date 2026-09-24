export interface Project {
  id: string
  name: string
  description: string | null
  status: string
  color: string | null
  repo_url: string | null
  deploy_url: string | null
  local_path: string | null
  /** 要远程触发的 GitHub Actions workflow 文件名；null = 该项目不可部署 */
  deploy_workflow: string | null
  /** 服务端计算：当前用户此刻能否触发部署（取决于角色 + 服务器是否配了 token） */
  can_deploy: boolean
  created_at: string
  updated_at: string
}

/** 一次远程部署记录（对应 GitHub Actions 的一次 workflow run） */
export interface DeployRun {
  id: string
  project_id: string
  status: string
  workflow: string
  repo_full_name: string
  github_run_id: string | null
  run_url: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  description: string | null
  priority: string
  status: string
  due_date: string | null
  created_at: string
  updated_at: string
}

export interface Note {
  id: string
  project_id: string
  title: string
  content: string
  created_at: string
  updated_at: string
}

// Markdown 文档（与速记 notes 区分：正式产物，可预览渲染）
export interface Doc {
  id: string
  project_id: string
  title: string
  content: string
  doc_meta: unknown | null
  created_at: string
  updated_at: string
}

export interface User {
  id: string
  email: string
  name: string
  role: string
  created_at: string
}

// 团队成员：共享 tenant_id 即同团队；role = owner | member | readonly
export interface TeamMember {
  id: string
  email: string
  name: string
  role: string
  created_at: string
}

export interface InviteResult {
  code: string
  invite_url: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export type Mode = 'demo' | 'live'

// ---------- Agent / 工作流（Phase 2） ----------

export type AgentParamType = 'text' | 'textarea' | 'number' | 'select' | 'project_id'

export interface AgentParam {
  name: string
  label: string
  type: AgentParamType
  required: boolean
  default: unknown
  options: { value: string; label: string }[]
  placeholder: string
}

export type AgentSource = 'builtin' | 'custom'

export interface AgentInfo {
  key: string
  name: string
  description: string
  param_schema: AgentParam[]
  source: AgentSource
  prompt?: string | null // 仅自定义 Agent 返回，供编辑回填
}

// 参数预置模板：一组参数值存成命名模板，运行 Agent / 编辑工作流步骤时一键复用
export interface ParamTemplate {
  id: string
  user_id: string
  name: string
  agent_key: string
  params: Record<string, unknown>
  created_at: string
  updated_at: string
}

// 自定义 Agent 定义（DB 持久化）：prompt 支持 {{param}} 占位符
export interface CustomAgentRead {
  id: string
  key: string
  name: string
  description: string | null
  prompt: string
  param_schema: AgentParam[]
  created_at: string
  updated_at: string
}

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface AgentRun {
  id: string
  agent_key: string
  project_id: string | null
  status: RunStatus
  params: Record<string, unknown>
  output: string | null
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface WorkflowStepPosition {
  x: number
  y: number
}

export interface WorkflowStep {
  label: string
  agent_key: string
  params: Record<string, unknown>
  /** 画布节点 id（可视化编排预留；旧数据缺省由前端派生） */
  node_id?: string
  /** 画布坐标（可视化编排预留；旧数据缺省由前端自动排布） */
  position?: WorkflowStepPosition
}

export interface Schedule {
  cron: string | null
  interval_minutes: number | null
}

/**
 * 连线条件（结构化 DSL，后端 op 白名单校验，不做表达式求值）。
 * `of` 只被 all / any / not 使用：all/any 收数组，not 收单个子条件。
 */
export interface WorkflowCondition {
  op: string
  left?: string
  right?: unknown
  of?: WorkflowCondition | WorkflowCondition[]
}

/** 画布连线。when 为空 = 无条件成立（无条件出边有多条即并行扇出）。 */
export interface WorkflowEdge {
  source: string
  target: string
  when?: WorkflowCondition | null
}

export interface Workflow {
  id: string
  user_id: string
  name: string
  description: string | null
  steps: WorkflowStep[]
  /** null = 线性：由后端按 steps 顺序自动连成一条链（存量工作流即此形态） */
  edges: WorkflowEdge[] | null
  schedule: Schedule | null
  enabled: boolean
  created_at: string
  updated_at: string
}

/**
 * AI 起草结果：形状对齐 WorkflowCreate，可直接 loadSteps 进画布。
 * rationale 是「AI 为什么这么拆」的一句话，只在起草成功后展示一次，不随工作流保存。
 */
export interface WorkflowDraft {
  name: string
  description: string
  rationale: string
  steps: WorkflowStep[]
  /** null = 线性（多数情况）；有分支时后端已算好每条边 */
  edges: WorkflowEdge[] | null
}

export interface WorkflowRunResult {
  label: string
  agent_key: string
  output: string
  /** 对应 steps[].node_id：分支结构下按它把结果对回画布节点，而非靠顺序猜 */
  node_id: string | null
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  status: RunStatus
  results: WorkflowRunResult[] | null
  error: string | null
  triggered_by: 'manual' | 'scheduled'
  started_at: string | null
  finished_at: string | null
  /** 断点续跑的时刻；从未续跑为 null */
  resumed_at: string | null
  created_at: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------- 知识库 RAG（Capability 4） ----------

export interface KnowledgeDocument {
  id: string
  project_id: string
  name: string
  source: string // upload | scan
  content_type: string // md | txt | pdf | docx
  status: string // ready | processing | error
  error: string | null
  source_path: string | null
  created_at: string
}

export interface KnowledgeSource {
  document_id: string
  document_name: string
  seq: number
  content: string
  matched: string[]
}

export interface KnowledgeResponse {
  answer: string
  sources: KnowledgeSource[]
}

export interface ScanResult {
  imported: number
  skipped: string[]
}

// ---------- 站内通知（Notification Center） ----------

export type NotificationType = 'agent_run' | 'workflow_run' | 'team' | 'knowledge' | 'due_reminder'

export interface Notification {
  id: string
  type: NotificationType
  title: string
  body: string | null
  ref_id: string | null
  read_at: string | null // 为空即未读
  created_at: string
}

export interface UnreadCount {
  count: number
}

// ---------- AI 副驾（Copilot） ----------

export interface CopilotMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface CopilotAgentMeta {
  key: string
  name: string
}

export interface CopilotWorkflowMeta {
  id: string
  name: string
}

export type CopilotResultKind = 'agent' | 'workflow' | 'task' | 'project' | 'knowledge'

// SSE 事件协议：与后端 copilot/service.py 的 event_* 构造函数一一对应
export type CopilotEvent =
  | { type: 'status'; message: string; agent?: CopilotAgentMeta; workflow?: CopilotWorkflowMeta }
  | { type: 'text'; delta: string }
  | { type: 'result'; kind: CopilotResultKind; data: Record<string, unknown> }
  | { type: 'done' }
  | { type: 'error'; code: string; message: string }

// ---------- AI 写作（续写/润色/总结） ----------

export type WritingOperation = 'continue' | 'polish' | 'summarize'

// SSE 事件协议：与后端 writing/service.py 的 event_* 构造函数一一对应
export type WritingEvent =
  | { type: 'text'; delta: string }
  | { type: 'done' }
  | { type: 'error'; code: string; message: string }
