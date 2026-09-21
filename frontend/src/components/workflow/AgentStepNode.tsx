import { createContext, memo, useContext } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { NODE_W, NODE_H, type FlowNode } from '../../lib/workflowGraph'

/**
 * 节点序号上下文：由 WorkflowCanvas 按链序计算注入。
 * 序号不写进 node.data，避免节点自身 data 变化触发整链重渲染。
 */
export const NodeIndexContext = createContext<ReadonlyMap<string, number>>(new Map())

const AgentStepNodeInner = ({ id, data, selected }: NodeProps<FlowNode>) => {
  const indexMap = useContext(NodeIndexContext)
  const index = indexMap.get(id)
  return (
    <div
      className="relative rounded-xl border bg-elev1 shadow-md transition-colors"
      style={{
        width: NODE_W,
        height: NODE_H,
        // 用真实的主题 token（--gold-primary / --border-soft，值形如 "217 164 65"，
        // 需经 rgb() 包装）。这两个变量名必须写对：写成不存在的名字不会报错，
        // 只会静默走 fallback 字面色，从而在非默认主题下显示错误颜色
        borderColor: selected ? 'rgb(var(--gold-primary))' : 'rgb(var(--border-soft))',
        boxShadow: selected ? '0 0 0 2px rgba(217,164,65,.35), 0 4px 16px rgba(0,0,0,.35)' : undefined,
      }}
    >
      {/* 左入右出的横向链 Handle */}
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-gold/60 !bg-gold" />
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-gold/60 !bg-gold" />

      <div className="flex h-full flex-col p-3">
        <div className="flex items-center gap-1.5">
          {index !== undefined && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-gold/20 px-1 font-mono text-[10px] leading-none text-gold">
              {index + 1}
            </span>
          )}
          <span className="truncate text-[11px] font-medium text-ink-3" title={data.agentName}>
            {data.agentName}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation()
              data.onDelete?.(id)
            }}
            /* nodrag：不加的话按下这个按钮会同时触发节点拖拽，点删除时节点会跟着飘 */
            className="nodrag ml-auto flex h-6 w-6 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-error/15 hover:text-error"
            title="删除步骤（也可选中节点后按 Delete）"
            aria-label="删除步骤"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="mt-1.5 truncate text-[13px] font-semibold text-ink" title={data.label}>
          {data.label || '未命名步骤'}
        </div>

        <div className="mt-auto truncate font-mono text-[10px] leading-relaxed text-ink-5" title={data.paramsSummary}>
          {data.paramsSummary || '无参数'}
        </div>
      </div>
    </div>
  )
}

export const AgentStepNode = memo(AgentStepNodeInner)
