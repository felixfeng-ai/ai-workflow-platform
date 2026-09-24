import { Button } from '../ui/button'
import { Input } from '../ui/input'
import {
  BINARY_OPS,
  CONDITION_OPS,
  DEFAULT_LEFT,
  LOGIC_OPS,
  OP_LABEL,
  describeCondition,
  type FlowEdge,
  type FlowNode,
} from '../../lib/workflowGraph'
import type { WorkflowCondition } from '../../types'

interface EdgeConditionPanelProps {
  /** 当前选中的边；null 时展示占位提示 */
  edge: FlowEdge | null
  nodes: FlowNode[]
  /** 改这条边的条件（null = 无条件）；label 由父级一并重算 */
  onPatch: (edgeId: string, when: WorkflowCondition | null) => void
  onDelete: (edgeId: string) => void
}

const selectCls =
  'h-9 w-full rounded-lg border border-line-soft bg-elev1 px-3 text-[13px] text-ink focus:border-gold-primary/60 focus:outline-none focus:ring-2 focus:ring-gold-primary/25'

/** 简单条件（不嵌套）：op + right。left 固定取上一步输出，UI 上不给改 —— 见下方说明 */
function simple(op: string, right = ''): WorkflowCondition {
  return BINARY_OPS.has(op) ? { op, left: DEFAULT_LEFT, right } : { op, left: DEFAULT_LEFT }
}

/**
 * 边的条件编辑。
 *
 * 只支持「一层组合」：顶层可以是某个简单条件，或 all/any/not 套一组简单条件。
 * 后端 DSL 允许 6 层嵌套，但画布上面向的是业务用户，再深的树用表单表达只是折磨 ——
 * 真要写复杂逻辑，走模板/接口落下同样的 JSON 即可，两条路生成的数据结构完全一致。
 *
 * left（左值）固定为 {{prev_output}}，不给输入框：它是「上一步的输出」这个语义本身，
 * 让用户手写 {{step.2.output}} 这种占位符，写错了要到运行时才炸。
 */
export function EdgeConditionPanel({ edge, nodes, onPatch, onDelete }: EdgeConditionPanelProps) {
  if (!edge) {
    return (
      <div className="p-3">
        <div className="text-[11px] font-semibold text-ink-3">分支条件</div>
        <div className="mt-2 text-[11.5px] leading-relaxed text-ink-5">
          点击画布上的一条连线，在这里设置「什么情况下走这条路」。
          <br />
          <br />
          一个步骤有多条出边时：都设条件 = 按条件择路；都不设条件 = 两条分支并行执行。
        </div>
      </div>
    )
  }

  const from = nodes.find((n) => n.id === edge.source)
  const to = nodes.find((n) => n.id === edge.target)
  const nameOf = (n?: FlowNode) => n?.data.label || n?.data.agentName || n?.id || '?'

  const when = edge.data?.when ?? null
  const op = when?.op ?? ''
  const isLogic = LOGIC_OPS.has(op)
  const subs: WorkflowCondition[] = isLogic
    ? Array.isArray(when?.of)
      ? when!.of as WorkflowCondition[]
      : when?.of
        ? [when.of as WorkflowCondition]
        : []
    : []

  /** 改顶层 op：切到逻辑 op 时补一个空子条件，否则子条件列表会是空的（后端要求非空） */
  const setOp = (next: string) => {
    if (!next) return onPatch(edge.id, null)
    if (LOGIC_OPS.has(next)) {
      const child = simple('contains')
      return onPatch(edge.id, next === 'not' ? { op: next, of: child } : { op: next, of: [child] })
    }
    onPatch(edge.id, simple(next))
  }

  const setSub = (i: number, next: WorkflowCondition) => {
    const list = subs.map((s, k) => (k === i ? next : s))
    onPatch(edge.id, op === 'not' ? { op, of: list[0] } : { op, of: list })
  }

  return (
    <div className="p-3">
      <div className="text-[11px] font-semibold text-ink-3">分支条件</div>
      <div className="mt-1.5 rounded-md border border-line-soft bg-bg px-2 py-1.5 text-[11.5px] text-ink-2">
        {nameOf(from)} <span className="text-ink-5">→</span> {nameOf(to)}
      </div>

      <div className="mt-3 text-[11px] text-ink-4">这条路径什么时候走？</div>
      <select className={`${selectCls} mt-1`} value={op} onChange={(e) => setOp(e.target.value)}>
        <option value="">总是执行（无条件）</option>
        {CONDITION_OPS.map((o) => (
          <option key={o} value={o}>
            {LOGIC_OPS.has(o) ? `组合：${OP_LABEL[o]}` : OP_LABEL[o]}
          </option>
        ))}
      </select>

      {/* 简单条件：一个右值输入框 */}
      {op && !isLogic && (
        <div className="mt-3">
          <div className="text-[11px] text-ink-4">右值（按字面量比较，不解析模板）</div>
          {BINARY_OPS.has(op) ? (
            <Input
              className="mt-1 h-9"
              value={typeof when?.right === 'string' ? when.right : String(when?.right ?? '')}
              placeholder={op === 'gt' || op === 'gte' || op === 'lt' || op === 'lte' ? '100' : '风险'}
              onChange={(e) =>
                onPatch(edge.id, {
                  ...simple(op),
                  right: e.target.value,
                })
              }
            />
          ) : (
            <div className="mt-1 text-[11.5px] text-ink-5">该条件只用左值，无需填写</div>
          )}
        </div>
      )}

      {/* 组合条件：一组简单条件 */}
      {isLogic && (
        <div className="mt-3 space-y-2">
          {subs.map((sub, i) => (
            <div key={i} className="rounded-md border border-line-soft bg-bg p-2">
              <select
                className={selectCls}
                value={sub.op}
                onChange={(e) =>
                  // 换 op 时保留同一个索引，右值清空 —— 复用旧右值大概率是错的
                  setSub(i, simple(e.target.value))
                }
              >
                {CONDITION_OPS.filter((o) => !LOGIC_OPS.has(o)).map((o) => (
                  <option key={o} value={o}>
                    {OP_LABEL[o]}
                  </option>
                ))}
              </select>
              {BINARY_OPS.has(sub.op) && (
                <Input
                  className="mt-2 h-9"
                  value={typeof sub.right === 'string' ? sub.right : String(sub.right ?? '')}
                  placeholder="要匹配的文字"
                  onChange={(e) => setSub(i, { ...sub, right: e.target.value })}
                />
              )}
              {op !== 'not' && subs.length > 1 && (
                <button
                  type="button"
                  className="mt-2 text-[11px] text-ink-5 hover:text-error"
                  onClick={() =>
                    onPatch(edge.id, { op, of: subs.filter((_, k) => k !== i) })
                  }
                >
                  移除这一条
                </button>
              )}
            </div>
          ))}
          {op !== 'not' && (
            <Button
              size="sm"
              variant="secondary"
              className="w-full"
              onClick={() => onPatch(edge.id, { op, of: [...subs, simple('contains')] })}
            >
              + 加一条
            </Button>
          )}
        </div>
      )}

      {when && (
        <div className="mt-3 rounded-md bg-active px-2 py-1.5 text-[11px] leading-relaxed text-ink-3">
          读作：{describeCondition(when)}
        </div>
      )}

      <Button
        size="sm"
        variant="secondary"
        className="mt-4 w-full"
        onClick={() => onDelete(edge.id)}
      >
        删除这条连线
      </Button>
    </div>
  )
}
