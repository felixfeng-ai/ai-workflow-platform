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
  graphToSteps,
  newNodeId,
  stepsToGraph,
  summarizeParams,
  wouldCreateCycle,
  type FlowEdge,
  type FlowNode,
  type WorkflowNodeData,
} from '../../lib/workflowGraph'
import type { AgentInfo, ParamTemplate, Project, WorkflowStep } from '../../types'
import { Button } from '../ui/button'
import { AgentStepNode, NodeIndexContext } from './AgentStepNode'
import { StepConfigPanel } from './StepConfigPanel'

/** 节点类型注册表：组件外常量，否则每次渲染重挂节点导致状态丢失 */
const nodeTypes = { agentStep: AgentStepNode }

export interface WorkflowCanvasHandle {
  /** 线性化当前画布：成功返回 { steps }，失败返回 { error }（父级保存时调用） */
  linearize: () => { steps: WorkflowStep[] } | { error: string }
  /** 用一组步骤重建画布（新建弹窗内「从模板开始」时调用） */
  loadSteps: (steps: WorkflowStep[]) => void
}

interface WorkflowCanvasProps {
  /** 初始步骤（编辑旧数据时传入，缺省自动按序排布；新建传 []） */
  initialSteps: WorkflowStep[]
  agents: AgentInfo[]
  projects: Project[]
  templates: ParamTemplate[]
  /** 画布内校验失败（连线拦截等）时的提示回调 */
  onValidationError: (message: string) => void
  /** 存为预置模板，透传给 StepConfigPanel */
  onSaveTemplate: (agentKey: string, name: string, params: Record<string, unknown>) => Promise<void>
}

/** 内部实现：须在 ReactFlowProvider 下使用 useReactFlow（拖拽落点坐标转换） */
const WorkflowCanvasInner = forwardRef<WorkflowCanvasHandle, WorkflowCanvasProps>(function WorkflowCanvasInner(
  { initialSteps, agents, projects, templates, onValidationError, onSaveTemplate },
  ref,
) {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { screenToFlowPosition } = useReactFlow()
  const initRef = useRef(false)
  /** 画布外框：右侧面板回车「完成」后把焦点交还这里，键盘链路才能接着走 */
  const canvasBoxRef = useRef<HTMLDivElement>(null)
  /** 右侧配置面板容器：回车进入编辑时用来定位第一个输入框 */
  const configPanelRef = useRef<HTMLDivElement>(null)

  /**
   * 删除节点：删边；若为中间节点，前驱→后继自动重连保持链条。
   *
   * 键盘删除与节点上的 × 都走这里，React Flow 内建的删除键则被显式关掉
   * （见下方 deleteKeyCode）—— 内建删除只把节点和它的边一起拿掉，不会重连，
   * 链条会断成两截，要到保存时才报「存在多个起点」，用户看不懂也修不回来。
   */
  const deleteNode = useCallback(
    (nodeId: string) => {
      setNodes((ns) => ns.filter((n) => n.id !== nodeId))
      setEdges((eds) => {
        const inE = eds.find((e) => e.target === nodeId)
        const outE = eds.find((e) => e.source === nodeId)
        const rest = eds.filter((e) => e.source !== nodeId && e.target !== nodeId)
        if (inE && outE) rest.push({ id: `e-${newNodeId()}`, source: inE.source, target: outE.target })
        return rest
      })
      setSelectedId((s) => (s === nodeId ? null : s))
    },
    [setNodes, setEdges],
  )

  /**
   * 选中节点：selectedId（右侧面板看它）与 React Flow 的 selected 标记（画布高亮）
   * 必须一起改。只改前者的话画布上没有高亮环，用户看不出 Delete / 回车会作用在哪个节点上。
   */
  const selectNode = useCallback(
    (nodeId: string | null) => {
      setSelectedId(nodeId)
      setNodes((ns) =>
        ns.map((n) => (n.selected === (n.id === nodeId) ? n : { ...n, selected: n.id === nodeId })),
      )
    },
    [setNodes],
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
    const { nodes: n, edges: e } = stepsToGraph(initialSteps)
    setNodes(withHandlers(n))
    setEdges(e)
    selectNode(n[0]?.id ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 实时链序：供节点序号显示（不写进 node.data，避免整链重渲染）
  const indexMap = useMemo(() => {
    const out = new Map<string, string>()
    const indeg = new Map<string, number>()
    for (const n of nodes) {
      out.set(n.id, '')
      indeg.set(n.id, 0)
    }
    for (const e of edges) {
      if (!out.has(e.source)) continue
      out.set(e.source, e.target)
      indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
    }
    const head = nodes.find((n) => (indeg.get(n.id) ?? 0) === 0)
    const map = new Map<string, number>()
    let cur = head?.id
    let i = 0
    const seen = new Set<string>()
    while (cur && !seen.has(cur)) {
      seen.add(cur)
      map.set(cur, i++)
      cur = out.get(cur) ?? ''
    }
    return map
  }, [nodes, edges])

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

  const onConnect = useCallback(
    (conn: Connection) => {
      const { source, target } = conn
      if (!source || !target) return
      if (source === target) {
        onValidationError('不能连接到自身')
        return
      }
      if (edges.some((e) => e.source === source)) {
        onValidationError('每节点最多一个出边（单链模式）')
        return
      }
      if (edges.some((e) => e.target === target)) {
        onValidationError('每节点最多一个入边（单链模式）')
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
    loadSteps: (steps: WorkflowStep[]) => {
      const { nodes: n, edges: e } = stepsToGraph(steps)
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
            onPaneClick={() => selectNode(null)}
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

        {/* 空画布引导：告诉第一次用的用户接下来的三步操作，降低上手门槛 */}
        {nodes.length === 0 && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-6">
            <div className="pointer-events-auto max-w-sm rounded-xl border border-line-soft bg-bg/95 p-5 text-center shadow-lg">
              <div className="text-[13px] font-semibold text-ink">如何创建工作流？</div>
              <div className="mt-3 space-y-2 text-left text-[12px] leading-relaxed text-ink-3">
                <div className="flex gap-2">
                  <span className="shrink-0 font-medium text-gold">①</span>
                  从左侧「AI 助手」点一下，添加第一个步骤
                </div>
                <div className="flex gap-2">
                  <span className="shrink-0 font-medium text-gold">②</span>
                  点击画布里的步骤卡片，右侧配置它要做什么
                </div>
                <div className="flex gap-2">
                  <span className="shrink-0 font-medium text-gold">③</span>
                  点下方「创建」，工作流即可运行
                </div>
              </div>
              {agents.length > 0 && (
                <Button size="sm" className="mt-4" onClick={() => appendNode(agents[0].key)}>
                  + 快速添加「{agents[0].name}」
                </Button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 右侧配置面板 */}
      <div ref={configPanelRef} className="w-72 shrink-0 overflow-y-auto rounded-lg border border-line-soft bg-elev1">
        <StepConfigPanel
          node={selectedNode}
          agents={agents}
          projects={projects}
          templates={templates}
          onPatch={patchNode}
          onSaveTemplate={onSaveTemplate}
          onCommit={focusCanvas}
        />
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
