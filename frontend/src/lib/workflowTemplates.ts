import type { WorkflowEdge, WorkflowStep } from '../types'

/**
 * 内置工作流模板：给第一次用的用户「点一下就能开始」的常见场景。
 * 每个模板只声明步骤骨架 + 非必填参数；必填参数（如「项目」）留空，
 * 填充画布后引导用户点击步骤在右侧补充。
 * agent_key 需存在于当前 agents 注册表才展示（见 WorkflowsPage 的可用性过滤）。
 */
export interface WorkflowTemplate {
  id: string
  name: string
  desc: string
  steps: WorkflowStep[]
  /** 分支模板的连线。不填 = 线性；填了则 steps 必须带 node_id，连线按 id 引用 */
  edges?: WorkflowEdge[]
}

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'daily-inspection',
    name: '每日项目巡检',
    desc: '先巡检项目风险，再汇总成当日结论',
    steps: [
      { label: '项目巡检', agent_key: 'inspection_report', params: {} },
      { label: '生成日报', agent_key: 'weekly_report', params: { period: 'this_week' } },
    ],
  },
  {
    id: 'weekly-report',
    name: '每周自动写周报',
    desc: '汇总项目进展，一键生成本周周报',
    steps: [{ label: '汇总周报', agent_key: 'weekly_report', params: { period: 'this_week' } }],
  },
  {
    id: 'interview-prep',
    name: '面试押题生成',
    desc: '围绕一个主题，生成一组面试/考试押题',
    steps: [
      { label: '生成押题', agent_key: 'interview_questions', params: { count: 10, difficulty: 'medium' } },
    ],
  },
  {
    id: 'risk-branch',
    name: '风险分支处理',
    desc: '先巡检，有风险走风险应对、无风险走常规汇总（条件分支示例）',
    // 分支模板必须显式写 node_id：连线靠它引用节点，缺省派生只对线性骨架成立
    steps: [
      { label: '项目巡检', agent_key: 'inspection_report', params: {}, node_id: 'n0', position: { x: 0, y: 0 } },
      {
        label: '有风险：专项应对',
        agent_key: 'weekly_report',
        params: { period: 'this_week' },
        node_id: 'n1',
        position: { x: 276, y: -110 },
      },
      {
        label: '无风险：常规汇总',
        agent_key: 'weekly_report',
        params: { period: 'this_week' },
        node_id: 'n2',
        position: { x: 276, y: 110 },
      },
    ],
    // 两条互斥条件 → 同一步只会走其中一条；都不成立时后端会让整个 run 失败（不静默成功）
    edges: [
      {
        source: 'n0',
        target: 'n1',
        when: { op: 'contains', left: '{{prev_output}}', right: '风险' },
      },
      {
        source: 'n0',
        target: 'n2',
        when: { op: 'not_contains', left: '{{prev_output}}', right: '风险' },
      },
    ],
  },
]
