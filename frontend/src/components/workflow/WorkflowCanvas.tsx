import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type XYPosition,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  NODE_W,
  X_GAP,
  chainTail,
  describeCondition,
  graphToSteps,
  newNodeId,
  stepsToGraph,
  summarizeParams,
  topoIndexMap,
  wouldCreateCycle,
  type FlowEdge,
  type FlowNode,
  type WorkflowNodeData,
} from '../../lib/workflowGraph'
import type { AgentInfo, ParamTemplate, Project, WorkflowCondition, WorkflowEdge, WorkflowStep } from '../../types'
import { Button } from '../ui/button'
import { AgentStepNode, NodeIndexContext } from './AgentStepNode'
import { EdgeConditionPanel } from './EdgeConditionPanel'
import { StepConfigPanel } from './StepConfigPanel'

/** 节点类型注册表：组件外常量，否则每次渲染重挂节点导致状态丢失 */
const nodeTypes = { agentStep: AgentStepNode }

export interface WorkflowCanvasHandle {
  /** 收口当前画布：成功返回 { steps, edges }，失败返回 { error }（父级保存时调用） */
  linearize: () => { steps: WorkflowStep[]; edges: WorkflowEdge[] } | { error: string }
  /** 用一组步骤（可带连线）重建画布（新建弹窗内「从模板开始」时调用） */
  loadSteps: (steps: WorkflowStep[], edges?: WorkflowEdge[] | null) => void
}

interface WorkflowCanvasProps {
  /** 初始步骤（编辑旧数据时传入，缺省自动按序排布；新建传 []） */
  initialSteps: WorkflowStep[]
  /** 初始连线；null/缺省 = 按 steps 顺序连成线性链（存量工作流形态） */
  initialEdges?: WorkflowEdge[] | null
  agents: AgentInfo[]
  projects: Project[]
  templates: ParamTemplate[]
  /** 画布内校验失败（连线拦截等）时的提示回调 */
  onValidationError: (message: string) => void
  /** 存为预置模板，透传给 StepConfigPanel */
  onSaveTemplate: (agentKey: string, name: string, params: Record<string, unknown>) => Promise<void>
  /**
   * 空画布上的一句话起草。接口调用留在父级 —— 画布只负责收集意图，
   * 它不该知道有个叫 /api/workflows/draft 的东西存在。
   */
  onDraft: (intent: string) => void
  /** 起草中：禁用输入与按钮，避免重复提交烧 token */
  drafting: boolean
}

/** 内部实现：须在 ReactFlowProvider 下使用 useReactFlow（拖拽落点坐标转换） */
const WorkflowCanvasInner = forwardRef<WorkflowCanvasHandle, WorkflowCanvasProps>(function WorkflowCanvasInner(
  { initialSteps, initialEdges, agents, projects, templates, onValidationError, onSaveTemplate, onDraft, drafting },
  ref,
) {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  /** 选中的连线：右侧面板在「节点配置」与「分支条件」之间切换 */
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  /** 空画布引导卡里的意图输入。起草失败时保留原文，用户改两个字就能重试 */
  const [intent, setIntent] = useState('')
  const { screenToFlowPosition } = useReactFlow()
  const initRef = useRef(false)
  /** 画布外框：右侧面板回车「完成」后把焦点交还这里，键盘链路才能接着走 */
  const canvasBoxRef = useRef<HTMLDivElement>(null)
  /** 右侧配置面板容器：回车进入编辑时用来定位第一个输入框 */
  const configPanelRef = useRef<HTMLDivElement>(null)

  /**
   * 删除节点：连带删掉它的边；仅当它恰好一进一出时，前驱→后继自动重连保持链条。
   *
   * 键盘删除与节点上的 × 都走这里，React Flow 内建的删除键则被显式关掉
   * （见下方 deleteKeyCode）—— 内建删除只把节点和它的边一起拿掉，不会重连，
   * 链条会断成两截，要到保存时才报「存在多个起点」，用户看不懂也修不回来。
   *
   * 分支节点（多进或多出）不重连：把 N 个前驱接到 M 个后继会产生 N×M 条边，
   * 那是在替用户编一张他没画过的图，不如让他自己连。
   */
  const deleteNode = useCallback(
    (nodeId: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== nodeId))
      setEdges((eds) => {
        const inEs = eds.filter((e) => e.target === nodeId)
        const outEs = eds.filter((e) => e.source === nodeId)
        const rest = eds.filter((e) => e.source !== nodeId && e.target !== nodeId)
        if (inEs.length === 1 && outEs.length === 1) {
          rest.push({ id: `e-${newNodeId()}`, source: inEs[0].source, target: outEs[0].target })
        }
        return rest
      })
      setSelectedId((s) => (s === nodeId ? null : s))
    },
    [setNodes, setEdges],
  )

  /** 改某条边的条件（null = 无条件）。label 一并重算，画布上才能直接读出「什么情况下走这条」 */
  const patchEdge = useCallback(
    (edgeId: string, when: WorkflowCondition | null) => {
      setEdges((eds) =>
        eds.map((e) =>
          e.id === edgeId ? { ...e, data: { ...e.data, when }, label: describeCondition(when) || undefined } : e,
        ),
      )
    },
    [setEdges],
  )

  const deleteEdge = useCallback(
    (edgeId: string) => {
      setEdges((eds) => eds.filter((e) => e.id !== edgeId))
      setSelectedEdgeId((s) => (s === edgeId ? null : s))
    },
    [setEdges],
  )

  /**
   * 选中节点：selectedId（右侧面板看它）与 React Flow 的 selected 标记（画布高亮）
   * 必须一起改。只改前者的话画布上没有高亮环，用户看不出 Delete / 回车会作用在哪个节点上。
   */
  const selectNode = useCallback(
    (nodeId: string | null) => {
      setSelectedId(nodeId)
      // 节点与边共用一个右侧面板：选中一方就把另一方让出去，否则面板显示谁的是模糊的
      if (nodeId) setSelectedEdgeId(null)
      setNodes((ns) =>
        ns.map((n) => (n.selected === (n.id === nodeId) ? n : { ...n, selected: n.id === nodeId })),
      )
    },
    [setNodes],
  )

  /** 选中连线：清掉节点选中态，右侧面板切到条件编辑 */
  const selectEdge = useCallback(
    (edgeId: string | null) => {
      setSelectedEdgeId(edgeId)
      if (edgeId) selectNode(null)
    },
    [selectNode],
  )

  // 参数摘要 label 化：key→中文参数名、项目 id→项目名，让节点卡片对非技术用户可读
  const summarizeNode = useCallback(
    (n: FlowNode) => {
      const a = agents.find((x) => x.key === n.data.agent_key)
      const labels = a ? Object.fromEntries(a.param_schema.map((p) => [p.name, p.label])) : undefined
      const names = Object.fromEntries(projects.map((p) => [p.id, p.name]))
      return summarizeParams(n.data.params, labels, names)
    },
    [agents, projects],
  )

  // 初始化：ref 守卫防 StrictMode 双跑；只按初始步骤建一次图；选中首节点便于引导配置
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    const { nodes: n, edges: e } = stepsToGraph(initialSteps, initialEdges)
    setNodes(withHandlers(n))
    setEdges(e)
    selectNode(n[0]?.id ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 实时序号：供节点上的 ①②③ 显示（不写进 node.data，避免整链重渲染）。
  // 有分支后不再是「链上的位置」，而是拓扑序 —— 详见 topoIndexMap
  const indexMap = useMemo(() => topoIndexMap(nodes, edges), [nodes, edges])

  /** 修改节点 data（label/agent_key/params/paramsSummary） */
  const patchNode = useCallback(
    (nodeId: string, patch: Partial<WorkflowNodeData>) => {
      setNodes((ns) => ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)))
    },
    [setNodes],
  )

  /**
   * 给 stepsToGraph 产出的节点补上交互回调。
   * stepsToGraph 只负责「数据 → 图」，不碰回调 —— 于是编辑旧工作流时（走的是
   * stepsToGraph）节点上没有 onDelete，× 点了没反应。这里统一补齐，
   * 新增节点、模板重建、编辑旧数据三条路径才不会各走各的。
   */
  const withHandlers = useCallback(
    (ns: FlowNode[]) =>
      ns.map((n) => ({
        ...n,
        data: { ...n.data, paramsSummary: summarizeNode(n), onDelete: deleteNode, onSelect: selectNode },
      })),
    [summarizeNode, deleteNode, selectNode],
  )

  /** 追加节点：接到链尾，或落在指定坐标（拖拽落点） */
  const appendNode = useCallback(
    (agentKey: string, position?: XYPosition) => {
      const agent = agents.find((a) => a.key === agentKey)
      const id = newNodeId()
      const fallback: XYPosition = (() => {
        const tail = chainTail(nodes, edges)
        return tail ? { x: tail.position.x + NODE_W + X_GAP, y: tail.position.y } : { x: 40, y: 80 }
      })()
      const pos = position ?? fallback
      const node: FlowNode = {
        id,
        type: 'agentStep',
        position: pos,
        data: {
          label: '',
          agent_key: agentKey,
          params: {},
          agentName: agent?.name ?? agentKey,
          paramsSummary: '',
          onDelete: deleteNode,
          onSelect: selectNode,
        },
      }
      setNodes((ns) => [...ns.map((n) => (n.selected ? { ...n, selected: false } : n)), node])
      const tail = chainTail(nodes, edges)
      if (tail) setEdges((eds) => [...eds, { id: `e-${newNodeId()}`, source: tail.id, target: id }])
      selectNode(id)
    },
    [agents, nodes, edges, setNodes, setEdges, deleteNode, selectNode],
  )

  /**
   * 连线校验：只拦「图跑不起来」的三种形态（自环 / 成环 / 重复边），
   * 出度入度不再限制 —— 多出边 = 分支，多入边 = 汇聚，都是本次改造要开放的能力。
   */
  const onConnect = useCallback(
    (conn: Connection) => {
      const { source, target } = conn
      if (!source || !target) return
      if (source === target) {
        onValidationError('不能连接到自身')
        return
      }
      if (edges.some((e) => e.source === source && e.target === target)) {
        // 同一对节点之间两条边没有意义：条件不同也只会让两条判定同时成立、目标跑两次
        onValidationError('这两个步骤之间已经有一条连线了')
        return
      }
      if (wouldCreateCycle(edges, source, target)) {
        onValidationError('该连线会形成环路')
        return
      }
      setEdges((eds) => addEdge({ ...conn, id: `e-${newNodeId()}` }, eds))
    },
    [edges, setEdges, onValidationError],
  )

  // 暴露线性化 + 模板填充方法给父级（保存 / 「从模板开始」时调用）
  useImperativeHandle(ref, () => ({
    linearize: () => graphToSteps(nodes, edges),
    loadSteps: (steps: WorkflowStep[], newEdges?: WorkflowEdge[] | null) => {
      const { nodes: n, edges: e } = stepsToGraph(steps, newEdges)
      setNodes(withHandlers(n))
      setEdges(e)
      selectNode(n[0]?.id ?? null)
    },
  }), [nodes, edges, withHandlers, selectNode])

  /** 回车进入编辑：焦点送进右侧面板的第一个输入框 */
  const focusConfigPanel = useCallback(() => {
    configPanelRef.current?.querySelector<HTMLElement>('input, select, textarea')?.focus()
  }, [])

  /** 面板里回车「完成」后交还焦点，Delete / 继续选节点才不会因为焦点在面板里而失效 */
  const focusCanvas = useCallback(() => canvasBoxRef.current?.focus(), [])

  /**
   * 画布快捷键：Delete/退格删除选中节点，回车进入该节点配置。
   *
   * 挂在 document 上而不是画布容器的 onKeyDown：点击节点后焦点落在节点自身的
   * div 上，事件压根不会走到画布容器的处理函数，挂容器收不到。
   * 代价是必须自己放行输入态 —— 否则在右侧面板里改参数按退格，会把整个节点删掉。
   */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // 已处理的（如弹窗的 Esc）不重复响应；带修饰键的组合留给浏览器/系统
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return
      // 输入态或可交互控件：退格是删字符、回车是触发控件，都不能抢
      const t = e.target as HTMLElement | null
      if (t?.closest('input, textarea, select, button, a, [contenteditable="true"]')) return
      if (!selectedId) return
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        deleteNode(selectedId)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        focusConfigPanel()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [selectedId, deleteNode, focusConfigPanel])

  const selectedNode = nodes.find((n) => n.id === selectedId) ?? null
  const selectedEdge = edges.find((e) => e.id === selectedEdgeId) ?? null

  return (
    <div className="flex h-full min-h-0 gap-2">
      {/* 左侧 palette：点击或拖拽追加节点 */}
      <div className="w-44 shrink-0 overflow-y-auto rounded-lg border border-line-soft bg-elev1 p-2">
        <div className="mb-1.5 px-1 text-[11px] font-semibold text-ink-3">AI 助手</div>
        <div className="mb-2 px-1 text-[10.5px] leading-snug text-ink-5">点击（或拖拽）添加一个步骤</div>
        {agents.map((a) => (
          <button
            key={a.key}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData('application/reactflow', a.key)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onClick={() => appendNode(a.key)}
            className="mb-1 block w-full rounded-md border border-line-soft bg-bg px-2 py-1.5 text-left transition-colors hover:border-gold-primary/50 hover:bg-active"
            title={`${a.name}：${a.description}\n点击或拖拽到画布`}
          >
            <div className="truncate text-[12px] font-medium text-ink">{a.name}</div>
            <div className="truncate text-[10px] leading-snug text-ink-5">{a.description}</div>
          </button>
        ))}
        {agents.length === 0 && <div className="px-1 text-[11px] text-ink-5">暂无 AI 助手</div>}
      </div>

      {/* 中间画布 */}
      <div
        ref={canvasBoxRef}
        tabIndex={-1}
        className="relative min-w-0 flex-1 rounded-lg border border-line-soft bg-elev1 outline-none"
        onDrop={(e) => {
          e.preventDefault()
          const key = e.dataTransfer.getData('application/reactflow')
          if (!key) return
          appendNode(key, screenToFlowPosition({ x: e.clientX, y: e.clientY }))
        }}
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'move'
        }}
      >
        <NodeIndexContext.Provider value={indexMap}>
          <ReactFlow
            className="h-full w-full"
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => selectNode(n.id)}
            onEdgeClick={(_, e) => selectEdge(e.id)}
            onPaneClick={() => {
              selectNode(null)
              selectEdge(null)
            }}
            // 边要能被点中才能编辑条件；默认的 20px 交互宽度对细线太窄
            edgesFocusable
            defaultEdgeOptions={{ interactionWidth: 24 }}
            nodeTypes={nodeTypes}
            // 内建删除键关掉，改由上面的 deleteNode 接管：内建的不会重连前后节点
            deleteKeyCode={null}
            fitView
            minZoom={0.3}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} />
            <MiniMap pannable zoomable />
            <Controls />
          </ReactFlow>
        </NodeIndexContext.Provider>

        {/* 空画布引导：主路径是「说一句话让 AI 起草」，手动搭建退居其后的 ①②③ */}
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
            <div className="pointer-events-auto max-h-full w-full max-w-md overflow-y-auto rounded-xl border border-line-soft bg-bg/95 p-5 shadow-lg">
              <div className="text-[13px] font-semibold text-ink">说一句话，让 AI 起草</div>
              <div className="mt-1 text-[11.5px] leading-relaxed text-ink-4">
                它会替你挑助手、填参数、排顺序。落到画布上还能再改。
              </div>
              <textarea
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                // Ctrl/Cmd+Enter 提交：输入框里回车要留给换行，意图本来就可能写成两行
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    if (intent.trim() && !drafting) onDraft(intent.trim())
                  }
                }}
                rows={3}
                disabled={drafting || agents.length === 0}
                placeholder="如：每周一把三个竞品的价格抓下来，出一份简报发我"
                className="mt-2.5 w-full resize-none rounded-lg border border-line-soft bg-elev1 px-2.5 py-2 text-[12.5px] leading-relaxed text-ink outline-none transition-colors placeholder:text-ink-5 focus:border-gold-primary/60 disabled:opacity-60"
              />
              <Button
                size="sm"
                className="mt-2 w-full"
                loading={drafting}
                disabled={drafting || !intent.trim() || agents.length === 0}
                onClick={() => onDraft(intent.trim())}
              >
                起草
              </Button>

              <div className="mt-4 flex items-center gap-2 text-[10.5px] text-ink-5">
                <span className="h-px flex-1 bg-line-soft" />
                或者自己搭
                <span className="h-px flex-1 bg-line-soft" />
              </div>
              <div className="mt-3 space-y-1.5 text-[11.5px] leading-relaxed text-ink-3">
                <div className="flex gap-2">
                  <span className="shrink-0 text-gold">①</span>
                  从左侧「AI 助手」点一下添加步骤
                </div>
                <div className="flex gap-2">
                  <span className="shrink-0 text-gold">②</span>
                  点画布里的卡片，右侧配它要做什么
                </div>
                <div className="flex gap-2">
                  <span className="shrink-0 text-gold">③</span>
                  一个步骤拉出两条连线即分支，点连线设条件
                </div>
              </div>
              {agents.length === 0 && (
                <div className="mt-3 text-[11px] text-warning">当前没有可用的 AI 助手，先创建一个再起草</div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 右侧配置面板：选中连线时切到条件编辑，否则是节点配置 */}
      <div ref={configPanelRef} className="w-72 shrink-0 overflow-y-auto rounded-lg border border-line-soft bg-elev1">
        {selectedEdge ? (
          <EdgeConditionPanel
            edge={selectedEdge}
            nodes={nodes}
            onPatch={patchEdge}
            onDelete={deleteEdge}
          />
        ) : (
          <StepConfigPanel
            node={selectedNode}
            agents={agents}
            projects={projects}
            templates={templates}
            onPatch={patchNode}
            onSaveTemplate={onSaveTemplate}
            onCommit={focusCanvas}
          />
        )}
      </div>
    </div>
  )
})

/** 对外组件：包 ReactFlowProvider（useReactFlow 依赖其上下文），其余透传给内部实现 */
export const WorkflowCanvas = forwardRef<WorkflowCanvasHandle, WorkflowCanvasProps>(function WorkflowCanvas(
  props,
  ref,
) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} ref={ref} />
    </ReactFlowProvider>
  )
})
