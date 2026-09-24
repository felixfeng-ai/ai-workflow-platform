import type { Edge, Node } from '@xyflow/react'
import type { WorkflowCondition, WorkflowEdge, WorkflowStep } from '../types'

/** 自定义节点尺寸与间距（与画布渲染保持一致） */
export const NODE_W = 220
export const NODE_H = 96
export const X_GAP = 56

/** 画布节点数据：label/agent_key/params 为持久化核心，其余为渲染/交互辅助 */
export type WorkflowNodeData = {
  label: string
  agent_key: string
  params: Record<string, unknown>
  /** agent 展示名（agent_key 未匹配到注册表时的兜底） */
  agentName: string
  /** 参数摘要（截断后），避免每次渲染重算 */
  paramsSummary: string
  onDelete?: (nodeId: string) => void
  onSelect?: (nodeId: string) => void
}

export type FlowNode = Node<WorkflowNodeData, 'agentStep'>
/** 边的 when 挂在 data 上（React Flow 的 label 只作展示，条件本体要能原样回传后端） */
export type FlowEdge = Edge<{ when?: WorkflowCondition | null }>

/**
 * 参数摘要：键值对连接，超长截断，防撑破节点卡片。
 * labels / projectNames 可选：传入后把原始 key 换成中文参数名、把项目 id 换成项目名，
 * 让画布节点上的摘要对非技术用户可读（如「项目=xxxx, 周期=本周」而非「project_id=p-1」）。
 */
export function summarizeParams(
  params: Record<string, unknown>,
  labels?: Record<string, string>,
  projectNames?: Record<string, string>,
  max = 40,
): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => {
      const label = labels?.[k] ?? k
      if (projectNames && typeof v === 'string' && projectNames[v]) return `${label}=${projectNames[v]}`
      return `${label}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`
    })
  const joined = parts.join(', ')
  return joined.length > max ? joined.slice(0, max) + '…' : joined
}

/** 会话内稳定新节点 id（勿用 random，避免 StrictMode 双跑抖动） */
export function newNodeId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // 非 secure context 兜底：时间戳 + 随机后缀
  return `n-${Date.now()}-${Math.floor(1000000 * Math.random())}`
}

// ---------------------------------------------------------------- 条件展示

export const OP_LABEL: Record<string, string> = {
  contains: '包含',
  not_contains: '不含',
  starts_with: '开头是',
  ends_with: '结尾是',
  eq: '等于',
  ne: '不等于',
  is_empty: '为空',
  not_empty: '不为空',
  gt: '大于',
  gte: '不小于',
  lt: '小于',
  lte: '不大于',
  all: '且',
  any: '或',
  not: '非',
}

/** 用于条件编辑器下拉；与后端 conditions.ALL_OPS 一一对应 */
export const CONDITION_OPS = Object.keys(OP_LABEL)

/** 需要填右值的 op（其余只用左值）；组合 op 走 of，不在此列 */
export const BINARY_OPS = new Set([
  'contains',
  'not_contains',
  'starts_with',
  'ends_with',
  'eq',
  'ne',
  'gt',
  'gte',
  'lt',
  'lte',
])

export const LOGIC_OPS = new Set(['all', 'any', 'not'])

/** 左值默认取「上一步输出」。写成模板占位符，与后端 templates.resolve 的语法一致 */
export const DEFAULT_LEFT = '{{prev_output}}'

/**
 * 条件 → 一句中文，给边上的标签用。
 * 只做展示，不参与判定 —— 判定完全在后端，前端复刻一套求值只会两边跑偏。
 */
export function describeCondition(when: WorkflowCondition | null | undefined, depth = 0): string {
  if (!when || typeof when !== 'object') return ''
  const op = when.op
  if (op === 'not') {
    const sub = Array.isArray(when.of) ? when.of[0] : when.of
    return `非(${describeCondition(sub, depth + 1) || '…'})`
  }
  if (op === 'all' || op === 'any') {
    const subs = Array.isArray(when.of) ? when.of : []
    const joiner = op === 'all' ? ' 且 ' : ' 或 '
    const body = subs.map((s) => describeCondition(s, depth + 1) || '…').join(joiner)
    // 嵌套时加括号：a 且 b 或 c 与 a 且 (b 或 c) 不是一回事
    return depth > 0 && subs.length > 1 ? `(${body})` : body
  }
  const label = OP_LABEL[op] ?? op
  if (!BINARY_OPS.has(op)) return label
  const left = when.left && when.left !== DEFAULT_LEFT ? `${when.left} ` : ''
  const right = typeof when.right === 'string' ? when.right : JSON.stringify(when.right ?? '')
  return `${left}${label}「${right ?? ''}」`
}

// ---------------------------------------------------------------- 图 <-> steps

/**
 * steps[] + edges[] → 画布图结构。
 *
 * edges 为空（存量线性工作流）时按 steps 顺序自动连成一条链；有 edges 就原样还原，
 * 包括分支条件。缺 node_id 用下标派生（node-${i}，与后端 collect_nodes 的兜底规则一致），
 * 缺 position 自动水平排布。
 */
export function stepsToGraph(
  steps: WorkflowStep[],
  edges?: WorkflowEdge[] | null,
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodes: FlowNode[] = steps.map((s, i) => {
    const id = s.node_id ?? `node-${i}`
    return {
      id,
      type: 'agentStep',
      position: s.position ?? { x: i * (NODE_W + X_GAP), y: 0 },
      data: {
        label: s.label,
        agent_key: s.agent_key,
        params: s.params ?? {},
        agentName: s.agent_key,
        paramsSummary: summarizeParams(s.params ?? {}),
      },
    }
  })

  const known = new Set(nodes.map((n) => n.id))
  const raw: WorkflowEdge[] = edges?.length
    ? edges
    : nodes.slice(0, -1).map((n, i) => ({ source: n.id, target: nodes[i + 1].id }))

  const flowEdges: FlowEdge[] = raw
    // 指向已删节点的边直接丢弃：画布上画不出来，留着只会在保存时炸出一个看不懂的报错
    .filter((e) => known.has(e.source) && known.has(e.target))
    .map((e) => ({
      id: `e-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      data: { when: e.when ?? null },
      label: describeCondition(e.when) || undefined,
    }))

  return { nodes, edges: flowEdges }
}

/** 拓扑序（Kahn），同层按 x 坐标排序 —— 保证并行分支的 steps 顺序稳定且符合视觉直觉 */
function topoOrder(nodes: FlowNode[], edges: FlowEdge[]): { order: string[]; cyclic: boolean } {
  const indeg = new Map<string, number>()
  const out = new Map<string, string[]>()
  for (const n of nodes) {
    indeg.set(n.id, 0)
    out.set(n.id, [])
  }
  for (const e of edges) {
    if (!indeg.has(e.source) || !indeg.has(e.target)) continue
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
    out.get(e.source)!.push(e.target)
  }
  const xOf = new Map(nodes.map((n) => [n.id, n.position.x]))
  const ready = nodes.filter((n) => (indeg.get(n.id) ?? 0) === 0).map((n) => n.id)
  const order: string[] = []
  while (ready.length) {
    ready.sort((a, b) => (xOf.get(a) ?? 0) - (xOf.get(b) ?? 0))
    const id = ready.shift()!
    order.push(id)
    for (const next of out.get(id) ?? []) {
      indeg.set(next, (indeg.get(next) ?? 0) - 1)
      if (indeg.get(next) === 0) ready.push(next)
    }
  }
  return { order, cyclic: order.length !== nodes.length }
}

/**
 * 节点序号（拓扑序，同层按 x 排序）。
 * 改造前序号 = 唯一链上的位置；有分支后一条链不存在了，只能按拓扑序编。
 */
export function topoIndexMap(nodes: FlowNode[], edges: FlowEdge[]): Map<string, number> {
  const { order } = topoOrder(nodes, edges)
  return new Map(order.map((id, i) => [id, i]))
}

/**
 * 画布图结构 → steps[] + edges[]。
 *
 * 失败返回 { error }。这里只拦「画布上就能看出来」的结构错误（环 / 多起点 / 孤立节点）——
 * 等深汇聚、条件 op 合法性交给后端 validate_graph，前端复刻一遍只会两边判定不一致。
 *
 * 与改造前的区别：不再要求「每节点最多一个出边」。出边多于一条即分支：
 * 都无条件 = 并行扇出；带条件 = 按条件择路。入边同理，多条即汇聚。
 */
export function graphToSteps(
  nodes: FlowNode[],
  edges: FlowEdge[],
): { steps: WorkflowStep[]; edges: WorkflowEdge[] } | { error: string } {
  if (nodes.length === 0) return { steps: [], edges: [] }

  const known = new Set(nodes.map((n) => n.id))
  const real = edges.filter((e) => known.has(e.source) && known.has(e.target))

  const indeg = new Map<string, number>()
  for (const n of nodes) indeg.set(n.id, 0)
  for (const e of real) indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)

  // 多起点报错：图必须有唯一入口（后端 validate_graph 同款判定）
  const heads = nodes.filter((n) => (indeg.get(n.id) ?? 0) === 0)
  if (heads.length > 1) {
    return { error: `存在多个起点（${heads.map(headName).join('、')}）：工作流只能有一个入口` }
  }
  if (heads.length === 0) return { error: '所有步骤都有上游：连线形成了环，请断开' }

  const { order, cyclic } = topoOrder(nodes, real)
  if (cyclic) return { error: '存在循环连线：请断开形成环的边' }
  if (order.length !== nodes.length) {
    return { error: '存在断链/孤立节点：请连接所有步骤或删除孤立节点' }
  }

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const steps: WorkflowStep[] = order.map((id) => {
    const n = byId.get(id)!
    return {
      label: n.data.label || n.data.agentName || n.data.agent_key,
      agent_key: n.data.agent_key,
      params: n.data.params,
      node_id: n.id,
      position: { x: n.position.x, y: n.position.y },
    }
  })
  const outEdges: WorkflowEdge[] = real.map((e) => {
    const base: WorkflowEdge = { source: e.source, target: e.target }
    // 无条件边不落 when 键：后端把「字段不存在」当作恒成立，落 null 会被 _clean 剔掉，
    // 两种写法等价，但不写更贴近「这条边没有条件」的语义
    return e.data?.when ? { ...base, when: e.data.when } : base
  })
  return { steps, edges: outEdges }
}

function headName(n: FlowNode): string {
  return n.data.label || n.data.agentName || n.data.agent_key || n.id
}

/**
 * 从 target 出发沿出边能否绕回 source（含自环）→ 新建此边会产生环。
 *
 * 必须按 DFS 走遍所有出边：改造前每条边只记一个后继，遇到分支结构会漏判 ——
 * a→b 与 a→c 并存时，「先记下的那条」会盖掉另一条，环就藏起来了。
 */
export function wouldCreateCycle(edges: FlowEdge[], source: string, target: string): boolean {
  if (source === target) return true
  const out = new Map<string, string[]>()
  for (const e of edges) {
    const list = out.get(e.source)
    if (list) list.push(e.target)
    else out.set(e.source, [e.target])
  }
  const stack = [target]
  const seen = new Set<string>()
  while (stack.length) {
    const cur = stack.pop()!
    if (cur === source) return true
    if (seen.has(cur)) continue
    seen.add(cur)
    for (const next of out.get(cur) ?? []) {
      if (!seen.has(next)) stack.push(next)
    }
  }
  return false
}

/** 链头：唯一入度为 0 的节点（多起点时取第一个，供连接新节点定位） */
export function chainHead(nodes: FlowNode[], edges: FlowEdge[]): FlowNode | null {
  const indeg = new Set(edges.map((e) => e.target))
  return nodes.find((n) => !indeg.has(n.id)) ?? null
}

/** 链尾：没有任何出边的节点（供追加新节点定位；分支结构下可能有多个，取 x 最大的那个） */
export function chainTail(nodes: FlowNode[], edges: FlowEdge[]): FlowNode | null {
  const hasOut = new Set(edges.map((e) => e.source))
  const tails = nodes.filter((n) => !hasOut.has(n.id))
  if (!tails.length) return null
  return tails.reduce((a, b) => (b.position.x > a.position.x ? b : a))
}
