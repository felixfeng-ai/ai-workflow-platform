import type {
  AgentInfo,
  AgentParam,
  AgentRun,
  AgentSource,
  AuthResponse,
  CopilotEvent,
  CopilotMessage,
  CustomAgentRead,
  DeployRun,
  InviteResult,
  KnowledgeDocument,
  KnowledgeResponse,
  Doc,
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
  WorkflowRun,
  WorkflowStep,
  WritingEvent,
  WritingOperation,
} from '../types'

const iso = (daysAgo: number, h = 10) => {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  d.setHours(h, (24 - (daysAgo % 24) * 3) % 60, 0, 0)
  return d.toISOString()
}

let projects: Project[] = [
  {
    id: 'p-1', name: 'CrossBorder AI', status: 'active',
    description: '1688 商品数据源 · 整店巡检闭环 · 环境变量巡检',
    color: '#D9A441', repo_url: 'https://github.com/Drir1203/crossborder-ai',
    deploy_url: null, local_path: null, deploy_workflow: null, can_deploy: false,
    created_at: iso(38), updated_at: iso(0, 9),
  },
  {
    id: 'p-2', name: 'i面试 · AI 教练', status: 'active',
    description: 'AI 面试教练 · 押题 · 闭环 · 成长报告 · 简历解析',
    color: '#E8C078', repo_url: 'https://github.com/Drir1203/interview-coach',
    deploy_url: null, local_path: null, deploy_workflow: null, can_deploy: false,
    created_at: iso(30), updated_at: iso(1),
  },
  {
    id: 'p-3', name: '雅秩 平台', status: 'planning',
    description: '工作流平台 · 黑金旗舰主题 · Web/小程序/App',
    color: '#A9762B', repo_url: 'https://github.com/Drir1203/ai-workflow-platform',
    deploy_url: 'https://veyawork.work', local_path: 'D:\\Project\\ai-workflow-platform',
    deploy_workflow: null, can_deploy: false,
    created_at: iso(2), updated_at: iso(0, 8),
  },
  {
    id: 'p-4', name: '日常工作', status: 'active',
    description: '周报、待办、灵感速记、AI 内容整理',
    color: '#8FA8C0', repo_url: null, deploy_url: null, local_path: null,
    deploy_workflow: null, can_deploy: false,
    created_at: iso(60), updated_at: iso(0, 7),
  },
]

let tasks: Task[] = [
  { id: 't-1', project_id: 'p-1', title: '1688 数据源整店巡检', description: '跑通 5.0 巡检闭环并核对结果', priority: 'high', status: 'in_progress', due_date: '2026-08-06', created_at: iso(3), updated_at: iso(0) },
  { id: 't-2', project_id: 'p-1', title: '环境变量巡检清单', description: 'GBK / PG schema 对齐', priority: 'medium', status: 'done', due_date: null, created_at: iso(5), updated_at: iso(2) },
  { id: 't-3', project_id: 'p-1', title: 'Onebound 接口开通需求', description: '整理需求文档', priority: 'low', status: 'todo', due_date: '2026-08-10', created_at: iso(1), updated_at: iso(1) },
  { id: 't-4', project_id: 'p-2', title: '移动端改为微信小程序 v3', description: '含订阅消息待办', priority: 'high', status: 'in_progress', due_date: '2026-08-07', created_at: iso(2), updated_at: iso(0, 9) },
  { id: 't-5', project_id: 'p-2', title: '成长报告导出', description: '', priority: 'medium', status: 'todo', due_date: null, created_at: iso(2), updated_at: iso(1) },
  { id: 't-6', project_id: 'p-3', title: 'Web 前端 · 黑金主题 Demo', description: 'Vite + React + Tailwind', priority: 'high', status: 'in_progress', due_date: '2026-08-06', created_at: iso(0), updated_at: iso(0) },
  { id: 't-7', project_id: 'p-3', title: '后端 23/23 测试全绿', description: 'FastAPI + SQLAlchemy async', priority: 'medium', status: 'done', due_date: null, created_at: iso(1), updated_at: iso(0) },
  { id: 't-8', project_id: 'p-4', title: '本周周报', description: '', priority: 'medium', status: 'todo', due_date: '2026-08-08', created_at: iso(1), updated_at: iso(0) },
]

let notes: Note[] = [
  { id: 'n-1', project_id: 'p-1', title: '巡检要点', content: '1688 数据源巡检的闭环步骤：爬取 → 校验 → 比对 → 上报，5.0 已全流程跑通。', created_at: iso(4), updated_at: iso(2) },
  { id: 'n-2', project_id: 'p-1', title: '环境变量陷阱', content: '.env 位置、PG schema 不匹配、GBK 下 emoji 会崩溃 —— 三处易踩坑都记录在案。', created_at: iso(3), updated_at: iso(1) },
  { id: 'n-3', project_id: 'p-2', title: '产品形态备忘', content: '移动端现状为微信小程序 v3，后续 H5 与原生 App 共用 Taro 一套代码。', created_at: iso(2), updated_at: iso(0) },
  { id: 'n-4', project_id: 'p-3', title: '主题决策', content: '黑金旗舰（Obsidian）已确认，DESIGN.md 为唯一风格事实源，主色香槟金 #D9A441。', created_at: iso(0), updated_at: iso(0) },
  { id: 'n-5', project_id: 'p-4', title: '本周灵感', content: '把日常工作里的 AI 内容整理也接进知识库 RAG，减少重复查询。', created_at: iso(1), updated_at: iso(1) },
]

// ---------- Markdown 文档（演示数据） ----------

let docs: Doc[] = [
  { id: 'do-1', project_id: 'p-1', title: '部署指南', content: '# 部署指南\n\n## 一键启动\n\n```bash\ndocker compose up -d\n```\n\n| 服务 | 端口 |\n| --- | --- |\n| Web | 8080 |\n| API | 8000 |\n', doc_meta: null, created_at: iso(6), updated_at: iso(1) },
  { id: 'do-2', project_id: 'p-3', title: '设计规范摘要', content: '# 设计规范\n\n- **主色**：香槟金 `#D9A441`\n- **背景**：黑金旗舰\n\n> 以 DESIGN.md 为唯一风格事实源。\n', doc_meta: null, created_at: iso(4), updated_at: iso(2) },
]

// ---------- 知识库 RAG（演示数据） ----------

let documents: KnowledgeDocument[] = [
  {
    id: 'd-1', project_id: 'p-1', name: 'CLAUDE.md', source: 'scan', content_type: 'md',
    status: 'ready', error: null, source_path: 'CLAUDE.md', created_at: iso(20),
  },
  {
    id: 'd-2', project_id: 'p-1', name: '巡检流程.md', source: 'upload', content_type: 'md',
    status: 'ready', error: null, source_path: null, created_at: iso(3),
  },
  {
    id: 'd-3', project_id: 'p-3', name: 'AI_WORKFLOW_PLATFORM_PLAN.md', source: 'scan', content_type: 'md',
    status: 'ready', error: null, source_path: 'research/AI_WORKFLOW_PLATFORM_PLAN.md', created_at: iso(2),
  },
  {
    id: 'd-4', project_id: 'p-3', name: 'DESIGN.md', source: 'scan', content_type: 'md',
    status: 'ready', error: null, source_path: 'DESIGN.md', created_at: iso(1),
  },
]

const delay = (ms = 180) => new Promise((r) => setTimeout(r, ms))
let nid = 100
let did = 100
let tid = 100
let rid = 100
let wid = 100
let cid = 100
let pti = 100

// ---------- Agent / 工作流演示数据 ----------

const agents: AgentInfo[] = [
  {
    key: 'weekly_report', name: '周报生成',
    description: '汇总本周项目进展、完成事项与风险，生成结构化周报',
    param_schema: [
      { name: 'project_id', label: '项目', type: 'project_id', required: false, default: null, options: [], placeholder: '全部项目' },
      { name: 'period', label: '周期', type: 'select', required: false, default: 'this_week', options: [
        { value: 'this_week', label: '本周' }, { value: 'last_week', label: '上周' }, { value: 'this_month', label: '本月' },
      ], placeholder: '' },
    ],
    source: 'builtin',
  },
  {
    key: 'inspection_report', name: '巡检报告',
    description: '检查指定项目任务完成率、高优与逾期风险，给出改进建议',
    param_schema: [
      { name: 'project_id', label: '项目', type: 'project_id', required: true, default: null, options: [], placeholder: '选择项目' },
    ],
    source: 'builtin',
  },
  {
    key: 'interview_questions', name: '押题生成',
    description: '根据主题生成面试/考试押题，含考察点与参考答案要点',
    param_schema: [
      { name: 'topic', label: '主题', type: 'text', required: true, default: null, options: [], placeholder: '如：FastAPI 异步编程' },
      { name: 'count', label: '题目数量', type: 'number', required: false, default: 10, options: [], placeholder: '' },
      { name: 'difficulty', label: '难度', type: 'select', required: false, default: 'medium', options: [
        { value: 'easy', label: '简单' }, { value: 'medium', label: '中等' }, { value: 'hard', label: '困难' },
      ], placeholder: '' },
    ],
    source: 'builtin',
  },
  {
    key: 'competitor_research', name: '竞品调研',
    description: '抓取指定网页并生成竞品分析报告（演示模式不抓取）',
    param_schema: [
      { name: 'topic', label: '主题', type: 'text', required: true, default: null, options: [], placeholder: '如：AI 笔记类竞品' },
      { name: 'urls', label: '网页链接（每行一个）', type: 'textarea', required: false, default: null, options: [], placeholder: 'https://…' },
      { name: 'max_sources', label: '参考来源数', type: 'number', required: false, default: 3, options: [], placeholder: '' },
    ],
    source: 'builtin',
  },
]

// 用户自定义 Agent（DB 持久化，演示用内存数组）：listAgents 合并内置 + 自定义。
// 本地用 CustomAgentRead 结构存（description 允许 null），listAgents 时再转 AgentInfo。
let customAgents: (CustomAgentRead & { source: AgentSource })[] = []

// 参数预置模板（演示用内存数组）：按命名复用一组参数值
let paramTemplates: ParamTemplate[] = []

let agentRuns: AgentRun[] = [
  {
    id: 'ar-1', agent_key: 'weekly_report', project_id: null, status: 'succeeded',
    // 演示数据刻意覆盖 Markdown 全元素（h1/h2/粗体/分隔线/列表），
    // 用来验证运行记录确实走渲染而非裸文本展示
    params: { period: 'this_week' },
    output: [
      '# 本周周报',
      '',
      '**统计范围**：全部项目｜**周期**：本周',
      '',
      '---',
      '',
      '## 一、本周进展',
      '',
      '- 项目 **CrossBorder AI**（状态：active，进行中）——ai 跨境决策引擎：本周无任务记录，无进展数据。',
      '',
      '## 二、已完成事项',
      '',
      '- 无数据。本周周期内无任务（含已完成任务），故无已完成事项可汇报。',
      '',
      '## 三、问题与风险',
      '',
      '- 无数据。本周无任务记录、无相关笔记，暂无法识别具体问题与风险。',
      '- 需说明的客观情况：本周统计范围内任务数为 0、笔记数为 0，项目 CrossBorder AI 虽处于 active 状态，但缺乏可追踪的进展数据，存在「进展不可见」的信息缺口，建议补充任务与笔记记录。',
      '',
      '## 四、下周计划',
      '',
      '- 无数据。本周无任务与笔记作为计划依据，暂无有数据支撑的下周计划。',
      '',
      '---',
      '',
      '**状态说明**：todo = 待办；in_progress = 进行中；done = 已完成。',
      '',
      '**备注**：本报告仅依据给定数据生成，未作任何推断或补充；标注「无数据」处均因原始数据缺失。',
    ].join('\n'),
    error: null, started_at: iso(1), finished_at: iso(0), created_at: iso(1),
  },
]

let workflows: Workflow[] = [
  {
    id: 'wf-1', user_id: 'demo-user', name: '每日巡检', description: '每天 9 点自动生成巡检报告',
    // 两节点展示画布编排形态：node_id/position 供可视化编辑器渲染
    steps: [
      { label: '巡检', agent_key: 'inspection_report', params: { project_id: 'p-1' }, node_id: 'n0', position: { x: 0, y: 0 } },
      { label: '周报', agent_key: 'weekly_report', params: { project_id: 'p-1' }, node_id: 'n1', position: { x: 276, y: 0 } },
    ],
    schedule: { cron: '0 9 * * *', interval_minutes: null }, enabled: true, created_at: iso(3), updated_at: iso(1),
  },
]

let workflowRuns: WorkflowRun[] = [
  {
    id: 'wr-1', workflow_id: 'wf-1', status: 'succeeded',
    results: [{ label: '巡检', agent_key: 'inspection_report', output: '## 巡检报告\n\n任务完成率 82%，无逾期高风险项。' }],
    error: null, triggered_by: 'manual', started_at: iso(1), finished_at: iso(0), created_at: iso(1),
  },
]

function stubAgentOutput(agentKey: string, params: Record<string, unknown>): string {
  switch (agentKey) {
    case 'weekly_report':
      return `## 本周周报\n\n### 进展\n${(params.period ?? 'this_week') === 'last_week' ? '上周重点推进巡检闭环与小程序迁移。' : 'Phase 2 智能体 + 工作流进入实现阶段。'}\n\n### 下周计划\n- 完成前端 Agents / Workflows 页面\n- 小程序接入智能体`
    case 'inspection_report':
      return `## 巡检报告\n\n- 任务完成率：82%\n- 高优任务：2 项进行中\n- 逾期风险：1 项临近截止\n\n### 建议\n优先处理高优任务，同步进度给相关人。`
    case 'interview_questions':
      return `## ${params.topic ?? '主题'} 押题（${params.count ?? 10} 题）\n\n1. **核心概念**：考察点 + 参考答案要点\n2. **进阶应用**：考察点 + 参考答案要点\n3. **实战场景**：考察点 + 参考答案要点`
    case 'competitor_research':
      return `## 竞品调研：${params.topic ?? '主题'}\n\n> 演示模式未抓取网页，以下为基于主题的通用分析。\n\n- 定位与目标用户\n- 核心功能对比\n- 差异化机会`
    default:
      // 自定义 Agent 演示输出：回显参数，保证 demo 运行有结果
      if (agentKey.startsWith('custom-')) {
        const lines = Object.entries(params).map(([k, v]) => `- ${k}: ${JSON.stringify(v)}`)
        return `## 自定义 Agent 输出（${agentKey}）\n\n${lines.join('\n') || '_（无参数）_'}`
      }
      return '演示输出'
  }
}

// 按固定长度切块，模拟流式打字机增量
function chunkText(s: string, size = 12): string[] {
  const out: string[] = []
  for (let i = 0; i < s.length; i += size) out.push(s.slice(i, i + size))
  return out.length ? out : ['…']
}

// AI 写作演示回复：按操作生成确定性的内容片段
function demoWritingReply(operation: WritingOperation, text: string): string {
  if (operation === 'continue') return '\n\n（续写）基于以上内容，建议下一步沉淀一份可复用的巡检 checklist，把数据源、校验口径与上报链路分别立项跟踪。'
  if (operation === 'summarize') return '要点列表：\n- 核心结论一：已明确\n- 核心结论二：可落地\n- 后续动作：跟进验证'
  return `润色结果：${text.trim()}`
}

function demoReply(q: string): string {
  const s = q.toLowerCase()
  if (s.includes('项目') || s.includes('project')) {
    return '工作区现有 4 个活跃项目。CrossBorder AI 的整店巡检闭环推进中（68.5%），i面试 教练移动端已切换为小程序 v3。需要我汇总某个项目的任务进度吗？'
  }
  if (s.includes('部署') || s.includes('dify') || s.includes('ai')) {
    return 'AI 引擎通过适配层对接 Dify CE（headless Service API）。未配置 DIFY_API_KEY 时返回 503；生产建议把密钥注入环境变量，测试用 FakeEngine 注入。'
  }
  if (s.includes('任务') || s.includes('待办')) {
    return '本周已完成 27 项任务，进行中 9 项，其中 3 项今日截止。建议优先处理 priority = high 的两项巡检任务。'
  }
  return '我已接入工作区数据。可以问我项目进度、任务待办、部署状态或任意 AI 相关问题——生产环境由 Dify 引擎回答，当前为演示数据。'
}

// 团队演示数据：owner（demo 用户）+ 一个 member，展示角色标签与邀请能力
let demoMembers: TeamMember[] = [
  { id: 'demo-user', email: 'demo@example.com', name: '演示用户', role: 'owner', created_at: iso(30) },
  { id: 'm-2', email: 'lin@example.com', name: '林', role: 'member', created_at: iso(20) },
]
let demoInvites: { code: string; email: string; role: string }[] = []

// 站内通知演示数据：5 条覆盖各 type，含未读，供铃铛红点 + 面板展示
let notifications: Notification[] = [
  { id: 'no-1', type: 'due_reminder', title: '任务到期提醒', body: '任务「1688 数据源整店巡检」已于 2026-08-06 到期，请及时处理', ref_id: 't-1', read_at: null, created_at: iso(0, 8) },
  { id: 'no-2', type: 'agent_run', title: 'Agent 运行完成', body: 'Agent「周报生成」已运行完成', ref_id: 'ar-1', read_at: null, created_at: iso(1) },
  { id: 'no-3', type: 'workflow_run', title: '工作流运行完成', body: '工作流「每日巡检」（手动）已运行完成', ref_id: 'wr-1', read_at: iso(2), created_at: iso(2) },
  { id: 'no-4', type: 'team', title: '新成员加入团队', body: 'lin@example.com 通过邀请加入了你的团队（角色：member）', ref_id: 'm-2', read_at: null, created_at: iso(3) },
  { id: 'no-5', type: 'knowledge', title: '文档已入库', body: '文档「巡检流程.md」已成功导入知识库', ref_id: 'd-2', read_at: iso(4), created_at: iso(4) },
]

export const demoApi = {
  // ---------- 认证（演示模式直接放行；补全 api ⇄ demoApi 镜像，保证 DataLayer 不变量成立） ----------
  login: async (email: string, _password: string): Promise<AuthResponse> => {
    await delay()
    return {
      access_token: 'demo-token',
      token_type: 'bearer',
      user: { id: 'demo-user', email, name: email.split('@')[0] || '演示用户', role: 'owner', created_at: new Date().toISOString() },
    }
  },
  register: async (email: string, _password: string, name: string, inviteCode?: string): Promise<AuthResponse> => {
    await delay()
    let role = 'owner'
    if (inviteCode) {
      const inv = demoInvites.find((i) => i.code === inviteCode && i.email === email)
      if (!inv) throw new Error('邀请码无效或已过期')
      role = inv.role
    }
    return {
      access_token: 'demo-token',
      token_type: 'bearer',
      user: { id: 'demo-user', email, name, role, created_at: new Date().toISOString() },
    }
  },
  // ---------- 团队管理（演示内存态；与 api.ts 签名镜像） ----------
  async listTeamMembers(): Promise<TeamMember[]> {
    await delay()
    return [...demoMembers]
  },
  async createInvite(email: string, role: 'member' | 'readonly'): Promise<InviteResult> {
    await delay()
    const code = `demo-${Math.random().toString(36).slice(2, 10)}`
    demoInvites = [...demoInvites, { code, email, role }]
    return { code, invite_url: `/register?invite_code=${code}` }
  },
  async acceptInvite(code: string): Promise<User> {
    await delay()
    const inv = demoInvites.find((i) => i.code === code)
    if (!inv) throw new Error('邀请码无效或已过期')
    return { id: 'demo-user', email: inv.email, name: inv.email.split('@')[0] || '演示用户', role: inv.role, created_at: new Date().toISOString() }
  },
  async updateMemberRole(userId: string, role: string): Promise<TeamMember> {
    await delay()
    const member = demoMembers.find((m) => m.id === userId)
    if (!member) throw new Error('member not found')
    const updated = { ...member, role }
    demoMembers = demoMembers.map((m) => (m.id === userId ? updated : m))
    return updated
  },
  async removeMember(userId: string): Promise<void> {
    await delay()
    demoMembers = demoMembers.filter((m) => m.id !== userId)
  },
  async listProjects(): Promise<Project[]> {
    await delay()
    return [...projects]
  },
  async createProject(p: { name: string; description?: string; repo_url?: string; deploy_url?: string; local_path?: string; deploy_workflow?: string }): Promise<Project> {
    await delay()
    const now = new Date().toISOString()
    const proj: Project = {
      id: `p-${++tid}`, name: p.name, description: p.description ?? null,
      status: 'active', color: '#D9A441',
      repo_url: p.repo_url ?? null, deploy_url: p.deploy_url ?? null, local_path: p.local_path ?? null,
      deploy_workflow: p.deploy_workflow ?? null,
      // 演示模式没有服务端、没有 token，部署能力整体不存在，故恒为 false
      can_deploy: false,
      created_at: now, updated_at: now,
    }
    projects = [proj, ...projects]
    return proj
  },
  async updateProject(id: string, patch: Partial<{ name: string; description: string | null; repo_url: string | null; deploy_url: string | null; local_path: string | null; deploy_workflow: string | null }>): Promise<Project> {
    await delay()
    const before = projects.find((p) => p.id === id)
    if (!before) throw new Error('项目不存在')
    // 不原地改对象：新建一份再整体替换，避免调用方拿到的旧引用被悄悄改掉
    const after: Project = { ...before, ...patch, can_deploy: false, updated_at: new Date().toISOString() }
    projects = projects.map((p) => (p.id === id ? after : p))
    return after
  },

  // ---------- 远程部署 ----------
  // 演示模式无服务端，下列方法只为满足 DataLayer 契约而存在。
  // 所有演示项目的 can_deploy 都是 false，界面不会给出入口；
  // 一旦真被调用到，说明有地方漏判了 can_deploy —— 直接抛错把它暴露出来，
  // 而不是假装部署成功（那会让演示看起来在工作，实际什么都没发生）。
  async deployProject(_projectId: string): Promise<DeployRun> {
    throw new Error('演示模式不支持部署')
  },
  async listDeployments(_projectId: string, _limit = 10): Promise<DeployRun[]> {
    return []
  },
  async getDeployment(_projectId: string, _runId: string): Promise<DeployRun> {
    throw new Error('演示模式不支持部署')
  },
  async deleteProject(id: string): Promise<void> {
    await delay()
    projects = projects.filter((p) => p.id !== id)
    tasks = tasks.filter((t) => t.project_id !== id)
    notes = notes.filter((n) => n.project_id !== id)
    docs = docs.filter((d) => d.project_id !== id)
  },
  async listTasks(projectId?: string): Promise<Task[]> {
    await delay()
    const list = projectId ? tasks.filter((t) => t.project_id === projectId) : tasks
    return [...list]
  },
  async createTask(t: { project_id: string; title: string; priority?: string; description?: string; status?: string }): Promise<Task> {
    await delay()
    const now = new Date().toISOString()
    const task: Task = {
      id: `t-${++tid}`, project_id: t.project_id, title: t.title,
      description: t.description ?? null, priority: t.priority ?? 'medium',
      status: t.status ?? 'todo', due_date: null, created_at: now, updated_at: now,
    }
    tasks = [task, ...tasks]
    return task
  },
  async updateTask(id: string, patch: Partial<Task>): Promise<Task> {
    await delay()
    tasks = tasks.map((t) => (t.id === id ? { ...t, ...patch, updated_at: new Date().toISOString() } : t))
    return tasks.find((t) => t.id === id)!
  },
  async deleteTask(id: string): Promise<void> {
    await delay()
    tasks = tasks.filter((t) => t.id !== id)
  },
  async listNotes(projectId?: string): Promise<Note[]> {
    await delay()
    const list = projectId ? notes.filter((n) => n.project_id === projectId) : notes
    return [...list]
  },
  async createNote(n: { project_id: string; title: string; content?: string }): Promise<Note> {
    await delay()
    const now = new Date().toISOString()
    const note: Note = {
      id: `n-${++nid}`, project_id: n.project_id, title: n.title,
      content: n.content ?? '', created_at: now, updated_at: now,
    }
    notes = [note, ...notes]
    return note
  },
  async updateNote(id: string, patch: Partial<Note>): Promise<Note> {
    await delay()
    notes = notes.map((n) => (n.id === id ? { ...n, ...patch, updated_at: new Date().toISOString() } : n))
    return notes.find((n) => n.id === id)!
  },
  async deleteNote(id: string): Promise<void> {
    await delay()
    notes = notes.filter((n) => n.id !== id)
  },
  async chat(query: string): Promise<{ answer: string }> {
    await delay(420)
    return { answer: demoReply(query) }
  },
  // ---------- AI 副驾（Copilot）：演示模式模拟事件流 ----------
  async *streamCopilot(messages: CopilotMessage[], projectId?: string): AsyncGenerator<CopilotEvent> {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')?.content ?? ''
    await delay(200)
    const s = lastUser.toLowerCase()
    // 内置智能体子流程：status → 逐字流式 → result → done
    const runBuiltin = async function* (
      key: string,
      name: string,
      params: Record<string, unknown>,
    ): AsyncGenerator<CopilotEvent, void, void> {
      yield { type: 'status', message: `正在运行智能体「${name}」`, agent: { key, name } }
      await delay(220)
      const output = stubAgentOutput(key, params)
      for (const chunk of chunkText(output)) {
        yield { type: 'text' as const, delta: chunk }
        await delay(16)
      }
      yield { type: 'result' as const, kind: 'agent', data: { agent_key: key, name, run_id: `ar-${++rid}`, output } }
      yield { type: 'done' as const }
    }
    if (s.includes('周报')) {
      yield* runBuiltin('weekly_report', '周报生成', { period: 'this_week' })
      return
    }
    if (s.includes('巡检')) {
      yield* runBuiltin('inspection_report', '巡检报告', {})
      return
    }
    if (s.includes('押题')) {
      yield* runBuiltin('interview_questions', '押题生成', { topic: 'AI 面试', count: 10 })
      return
    }
    if (s.includes('创建') || s.includes('建个') || s.includes('建一')) {
      yield { type: 'status', message: '已创建任务「AI 副驾演示任务」' }
      await delay(160)
      yield {
        type: 'result', kind: 'task',
        data: { id: `t-${++tid}`, title: 'AI 副驾演示任务', project_id: projectId ?? 'p-1', project_name: 'CrossBorder AI', priority: 'high' },
      }
      yield { type: 'done' }
      return
    }
    // 兜底：普通问答流式输出
    for (const chunk of chunkText(demoReply(lastUser))) {
      yield { type: 'text', delta: chunk }
      await delay(18)
    }
    yield { type: 'done' }
  },
  // ---------- Markdown 文档（演示数据） ----------
  async listDocs(projectId?: string): Promise<Doc[]> {
    await delay()
    const list = projectId ? docs.filter((d) => d.project_id === projectId) : docs
    return [...list]
  },
  async createDoc(d: { project_id: string; title: string; content?: string }): Promise<Doc> {
    await delay()
    const now = new Date().toISOString()
    const doc: Doc = {
      id: `do-${++did}`, project_id: d.project_id, title: d.title,
      content: d.content ?? '', doc_meta: null, created_at: now, updated_at: now,
    }
    docs = [doc, ...docs]
    return doc
  },
  async getDoc(id: string): Promise<Doc> {
    await delay()
    return docs.find((d) => d.id === id)!
  },
  async updateDoc(id: string, patch: Partial<Doc>): Promise<Doc> {
    await delay()
    docs = docs.map((d) => (d.id === id ? { ...d, ...patch, updated_at: new Date().toISOString() } : d))
    return docs.find((d) => d.id === id)!
  },
  async deleteDoc(id: string): Promise<void> {
    await delay()
    docs = docs.filter((d) => d.id !== id)
  },
  // ---------- AI 写作（续写/润色/总结）：演示模式模拟事件流 ----------
  async *streamWriting(operation: WritingOperation, text: string): AsyncGenerator<WritingEvent> {
    await delay(260)
    const reply = demoWritingReply(operation, text)
    for (const chunk of chunkText(reply)) {
      yield { type: 'text', delta: chunk }
      await delay(24)
    }
    yield { type: 'done' }
  },
  // ---------- Agent（演示数据） ----------
  async listAgents(): Promise<AgentInfo[]> {
    await delay()
    return [
      ...agents,
      ...customAgents.map((a) => ({
        key: a.key,
        name: a.name,
        description: a.description ?? '',
        param_schema: a.param_schema,
        source: a.source,
        prompt: a.prompt,
      })),
    ]
  },
  async runAgent(agentKey: string, body: { params?: Record<string, unknown>; project_id?: string }): Promise<{ run_id: string; status: string }> {
    await delay()
    const run: AgentRun = {
      id: `ar-${++rid}`, agent_key: agentKey, project_id: body.project_id ?? null,
      status: 'succeeded', params: body.params ?? {}, output: stubAgentOutput(agentKey, body.params ?? {}),
      error: null, started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    }
    agentRuns = [run, ...agentRuns]
    return { run_id: run.id, status: run.status }
  },
  async listAgentRuns(opts?: { agent_key?: string; page?: number; page_size?: number }): Promise<Paginated<AgentRun>> {
    await delay()
    const key = opts?.agent_key
    const list = key ? agentRuns.filter((r) => r.agent_key === key) : agentRuns
    const page = opts?.page ?? 1
    const pageSize = opts?.page_size ?? 20
    return { items: list.slice((page - 1) * pageSize, page * pageSize), total: list.length, page, page_size: pageSize }
  },
  async getAgentRun(runId: string): Promise<AgentRun> {
    await delay()
    return agentRuns.find((r) => r.id === runId)!
  },
  // ---------- 自定义 Agent（DB 持久化，演示用内存） ----------
  async createAgent(a: { name: string; description?: string | null; prompt: string; param_schema: AgentParam[] }): Promise<CustomAgentRead> {
    await delay()
    const now = new Date().toISOString()
    const agent: CustomAgentRead = {
      id: `ca-${++cid}`, key: `custom-${cid}`, name: a.name,
      description: a.description ?? null, prompt: a.prompt, param_schema: a.param_schema,
      created_at: now, updated_at: now,
    }
    // 本地存 CustomAgentRead 结构 + source 标记，listAgents 时再转 AgentInfo
    customAgents = [...customAgents, { ...agent, source: 'custom' }]
    return agent
  },
  async updateAgent(key: string, patch: Partial<{ name: string; description?: string | null; prompt: string; param_schema: AgentParam[] }>): Promise<CustomAgentRead> {
    await delay()
    customAgents = customAgents.map((a) => (a.key === key ? { ...a, ...patch, updated_at: new Date().toISOString() } : a))
    return customAgents.find((a) => a.key === key)!
  },
  async deleteAgent(key: string): Promise<void> {
    await delay()
    customAgents = customAgents.filter((a) => a.key !== key)
    // 级联清理：删掉绑定该 Agent 的预置模板与历史运行，避免残留死引用
    paramTemplates = paramTemplates.filter((t) => t.agent_key !== key)
    agentRuns = agentRuns.filter((r) => r.agent_key !== key)
  },
  // ---------- 参数预置模板（演示数据） ----------
  async listParamTemplates(agentKey?: string): Promise<ParamTemplate[]> {
    await delay()
    const list = agentKey ? paramTemplates.filter((t) => t.agent_key === agentKey) : paramTemplates
    return [...list]
  },
  async createParamTemplate(t: { name: string; agent_key: string; params: Record<string, unknown> }): Promise<ParamTemplate> {
    await delay()
    const now = new Date().toISOString()
    const tpl: ParamTemplate = {
      id: `pt-${++pti}`, user_id: 'demo-user', name: t.name,
      agent_key: t.agent_key, params: t.params, created_at: now, updated_at: now,
    }
    paramTemplates = [tpl, ...paramTemplates]
    return tpl
  },
  async updateParamTemplate(id: string, patch: Partial<{ name: string; params: Record<string, unknown> }>): Promise<ParamTemplate> {
    await delay()
    paramTemplates = paramTemplates.map((t) => (t.id === id ? { ...t, ...patch, updated_at: new Date().toISOString() } : t))
    return paramTemplates.find((t) => t.id === id)!
  },
  async deleteParamTemplate(id: string): Promise<void> {
    await delay()
    paramTemplates = paramTemplates.filter((t) => t.id !== id)
  },
  // ---------- 工作流（演示数据） ----------
  async listWorkflows(): Promise<Workflow[]> {
    await delay()
    return [...workflows]
  },
  async createWorkflow(w: {
    name: string
    description?: string
    steps: WorkflowStep[]
    schedule?: Schedule | null
  }): Promise<Workflow> {
    await delay()
    const now = new Date().toISOString()
    const wf: Workflow = {
      id: `wf-${++wid}`, user_id: 'demo-user', name: w.name, description: w.description ?? null,
      steps: w.steps,
      schedule: (w.schedule && (w.schedule.cron || w.schedule.interval_minutes)
        ? { cron: w.schedule.cron ?? null, interval_minutes: w.schedule.interval_minutes ?? null }
        : null),
      enabled: true, created_at: now, updated_at: now,
    }
    workflows = [wf, ...workflows]
    return wf
  },
  async updateWorkflow(id: string, patch: Partial<Workflow>): Promise<Workflow> {
    await delay()
    workflows = workflows.map((w) => (w.id === id ? { ...w, ...patch, updated_at: new Date().toISOString() } : w))
    return workflows.find((w) => w.id === id)!
  },
  async deleteWorkflow(id: string): Promise<void> {
    await delay()
    workflows = workflows.filter((w) => w.id !== id)
  },
  async runWorkflow(id: string): Promise<{ run_id: string; status: string }> {
    await delay()
    const wf = workflows.find((w) => w.id === id)!
    const run: WorkflowRun = {
      id: `wr-${++wid}`, workflow_id: id, status: 'succeeded',
      results: wf.steps.map((s, i) => ({ label: s.label, agent_key: s.agent_key, output: stubAgentOutput(s.agent_key, s.params) })),
      error: null, triggered_by: 'manual',
      started_at: new Date().toISOString(), finished_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    }
    workflowRuns = [run, ...workflowRuns]
    return { run_id: run.id, status: run.status }
  },
  async listWorkflowRuns(opts?: { page?: number; page_size?: number }): Promise<Paginated<WorkflowRun>> {
    await delay()
    const page = opts?.page ?? 1
    const pageSize = opts?.page_size ?? 20
    return { items: workflowRuns.slice((page - 1) * pageSize, page * pageSize), total: workflowRuns.length, page, page_size: pageSize }
  },
  async getWorkflowRun(runId: string): Promise<WorkflowRun> {
    await delay()
    return workflowRuns.find((r) => r.id === runId)!
  },
  // ---------- 知识库 RAG（演示数据） ----------
  async listDocuments(projectId: string): Promise<KnowledgeDocument[]> {
    await delay()
    return documents.filter((d) => d.project_id === projectId)
  },
  async uploadDocument(projectId: string, file: File): Promise<KnowledgeDocument> {
    await delay()
    const ext = file.name.toLowerCase().split('.').pop() ?? 'md'
    const now = new Date().toISOString()
    const doc: KnowledgeDocument = {
      id: `d-${++did}`, project_id: projectId, name: file.name,
      source: 'upload', content_type: ext, status: 'ready', error: null,
      source_path: null, created_at: now,
    }
    documents = [doc, ...documents]
    return doc
  },
  async deleteDocument(projectId: string, documentId: string): Promise<void> {
    await delay()
    documents = documents.filter((d) => !(d.project_id === projectId && d.id === documentId))
  },
  async scanDocuments(projectId: string): Promise<ScanResult> {
    await delay()
    const hasScanned = documents.some((d) => d.project_id === projectId && d.source === 'scan')
    if (hasScanned) return { imported: 0, skipped: ['CLAUDE.md', 'README.md'] }
    const now = new Date().toISOString()
    const newDocs: KnowledgeDocument[] = [
      { id: `d-${++did}`, project_id: projectId, name: 'CLAUDE.md', source: 'scan', content_type: 'md', status: 'ready', error: null, source_path: 'CLAUDE.md', created_at: now },
      { id: `d-${++did}`, project_id: projectId, name: 'README.md', source: 'scan', content_type: 'md', status: 'ready', error: null, source_path: 'README.md', created_at: now },
    ]
    documents = [...newDocs, ...documents]
    return { imported: 2, skipped: [] }
  },
  async queryKnowledge(projectId: string, query: string): Promise<KnowledgeResponse> {
    await delay(520)
    const list = documents.filter((d) => d.project_id === projectId)
    if (list.length === 0) return { answer: '知识库中未找到相关信息。', sources: [] }
    const projName = projects.find((p) => p.id === projectId)?.name ?? projectId
    return {
      answer: `根据「${projName}」项目知识库检索到相关内容：\n\n${query}\n\n（演示模式：基于已入库文档的关键词检索。生产环境由 AI 引擎生成回答并附引用来源。）`,
      sources: list.slice(0, 2).map((d, i) => ({
        document_id: d.id, document_name: d.name, seq: i,
        content: '…示例引用片段：文档内与查询相关的段落，最多展示前 300 字符。',
        matched: query.trim().split(/\s+/).slice(0, 3),
      })),
    }
  },
  // ---------- 站内通知（演示数据，与 api.ts 签名镜像） ----------
  async listNotifications(opts?: { unread_only?: boolean; type?: NotificationType; page?: number; page_size?: number }): Promise<Paginated<Notification>> {
    await delay()
    let list = opts?.type ? notifications.filter((n) => n.type === opts.type) : notifications
    if (opts?.unread_only) list = list.filter((n) => !n.read_at)
    const page = opts?.page ?? 1
    const pageSize = opts?.page_size ?? 20
    return { items: list.slice((page - 1) * pageSize, page * pageSize), total: list.length, page, page_size: pageSize }
  },
  async getUnreadCount(): Promise<UnreadCount> {
    await delay()
    return { count: notifications.filter((n) => !n.read_at).length }
  },
  async markNotificationRead(id: string): Promise<void> {
    await delay()
    notifications = notifications.map((n) => (n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n))
  },
  async markAllNotificationsRead(): Promise<{ updated: number }> {
    await delay()
    const unread = notifications.filter((n) => !n.read_at).length
    notifications = notifications.map((n) => (n.read_at ? n : { ...n, read_at: new Date().toISOString() }))
    return { updated: unread }
  },
  async deleteNotification(id: string): Promise<void> {
    await delay()
    notifications = notifications.filter((n) => n.id !== id)
  },
}
