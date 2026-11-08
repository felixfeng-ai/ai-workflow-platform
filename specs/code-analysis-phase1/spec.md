# 代码提交分析报告 V1 规格

> 状态：已确认
> 确认方式：用户确认技术方案并要求「先完成第一期」，附第一期范围截图
> 更新时间：2026-11-09
> 实现状态：V1 已实现并通过后端与前端门禁

## 能力点 1：项目级 GitHub 仓库连接

### Requirement

项目 owner 可以配置 GitHub 仓库、访问 Token、Webhook Secret 和分支规则。

### Scenario 1.1：成功创建连接

- Given 当前用户是项目 owner
- When 提交合法 GitHub 仓库地址、Fine-grained PAT 和分支规则
- Then 系统验证仓库可访问
- And 保存加密后的 Token 和 Webhook Secret
- And 仅本次响应返回 Webhook Secret 明文

### Scenario 1.1a：公开仓库无 PAT

- Given 仓库是公开仓库
- When owner 不填写访问 Token
- Then 系统仍可通过 GitHub 匿名 API 完成仓库验证和分析

### Scenario 1.1b：保存后的 GitHub 接入指引

- Given 项目 owner 已保存仓库连接
- When 页面展示 Webhook URL 和 Secret
- Then 页面显示打开 GitHub Webhook 设置的可点击入口
- And 列出 Payload URL、Content type、Secret、SSL 和 Push 事件配置项
- And 提供复制完整配置和重新生成 Secret 的说明
- And 明确提示保存后推送匹配分支进行验证

### Scenario 1.2：非 owner 禁止配置

- Given 当前用户不是 owner
- When 请求创建或修改仓库连接
- Then 返回 403

### Scenario 1.3：跨租户不可见

- Given 项目属于另一个租户
- When 当前用户请求该项目的仓库连接或分析报告
- Then 统一返回 404

## 能力点 2：接收 GitHub Push Webhook

### Requirement

平台接收 GitHub `push` 事件，并按 `before...after` 创建一次分析任务。

### Scenario 2.1：合法 push

- Given 项目已配置仓库连接和 Webhook Secret
- When GitHub 发送签名正确的 `push` 事件
- Then 返回 202
- And 创建一个 `pending` 分析任务

### Scenario 2.2：错误签名

- Given 请求签名与原始 body 不匹配
- When 请求 Webhook
- Then 返回 401
- And 不创建分析任务

### Scenario 2.3：重复 Delivery

- Given 同一 `X-GitHub-Delivery` 已处理
- When 再次收到相同事件
- Then 返回 204
- And 不创建重复任务

### Scenario 2.4：分支不匹配

- Given push 分支不符合项目分支规则
- When 请求 Webhook
- Then 返回 204
- And 不创建分析任务

## 能力点 3：拉取与归一化变更

### Requirement

系统按提交范围拉取 commits 和 files，并统计提交、文件、增删行、二进制、重命名和语言分布。

### Scenario 3.1：普通提交范围

- Given GitHub Compare API 返回 commits 和 files
- When 分析任务执行
- Then 报告包含提交数、文件数、增删行数和语言分布
- And 保留每个 commit 的 SHA 和摘要

### Scenario 3.2：新分支或 Force Push

- Given `before` 为空或旧提交不可比较
- When 分析任务执行
- Then 系统使用默认分支比较或退回首提交
- And 失败时任务记录可读错误，不产生 500

### Scenario 3.3：大型提交

- Given 文件数量超过配置上限
- When 分析任务执行
- Then 只分析优先文件
- And 报告标记 `truncated=true`

## 能力点 4：结构化分析报告

### Requirement

报告包含变更量、功能点、模块与接口、状态管理、数据结构、影响范围、安全扫描、测试缺口、复核建议和证据。

### Scenario 4.1：确定性报告

- Given 变更已完成归一化
- When AI 不可用
- Then 仍生成包含确定性统计、commit 摘要和 Secret 扫描结果的报告

### Scenario 4.2：AI 可用

- Given AI 返回合法结构化 JSON
- When 分析任务执行
- Then 合并 AI 功能点、边界、状态、影响和复核建议
- And 每条风险保留证据和置信度

### Scenario 4.3：Secret 与 Semgrep

- Given 变更文件包含疑似密钥或 Semgrep 可识别风险
- When 执行安全扫描
- Then 报告包含文件、行号、规则来源、严重级别和建议
- And Semgrep 不可用时报告明确标记不可用，不伪造结果

## 能力点 5：项目页代码分析历史

### Requirement

项目详情页提供「代码分析」Tab，展示历史报告列表和详情。

### Scenario 5.1：查看历史

- Given 项目已有分析任务
- When 用户打开代码分析 Tab
- Then 显示分支、Commit、变更量、风险数量和状态

### Scenario 5.2：查看详情

- Given 用户选择一份报告
- When 打开详情
- Then 显示结构化报告、证据和安全发现

### Scenario 5.3：演示模式

- Given 前端处于 demo 模式
- Then 同样可浏览样例分析报告

## 能力点 6：完成通知

### Requirement

分析成功、部分完成或失败时发送站内通知。

### Scenario 6.1：成功通知

- Given 分析任务完成
- When 写入最终状态
- Then 创建 `code_analysis` 类型通知
- And 通知失败不影响报告落库

## 能力点 7：详情报告下载为 Word 文档

### Requirement

用户可以从已完成的代码分析详情中下载真正的 Word `.docx` 文件。

### Scenario 7.1：下载成功

- Given 报告状态为 `succeeded` 或 `partial`
- When 项目成员点击「下载 DOCX」
- Then 返回可被 Word 打开的 `.docx` 文件
- And 文件包含变更概览、Commit、功能点、边界与状态、影响、安全发现、测试缺口和复核清单

### Scenario 7.2：报告未完成

- Given 报告仍在运行或已失败且没有报告内容
- When 请求下载
- Then 返回 409，不生成空文档

### Scenario 7.3：跨租户访问

- Given 用户不属于报告所属租户
- When 请求下载
- Then 返回 404

## 能力点 8：历史报告搜索、筛选、分页与风险摘要

### Requirement

项目成员可以搜索和筛选历史报告，并分页浏览全部记录。

### Scenario 8.1：分页与总数

- Given 项目有 25 份报告
- When 请求第 2 页、每页 10 条
- Then 返回 10 条记录
- And 返回 `total=25`、`page=2`、`page_size=10`

### Scenario 8.2：关键词搜索

- Given 报告包含 Commit 信息、SHA、分支、文件路径、功能点或安全标题
- When 用户输入关键词
- Then 返回任一字段命中的报告

### Scenario 8.3：组合筛选

- Given 报告具有状态、分支、日期和风险等级
- When 用户组合筛选条件
- Then 所有条件同时生效

### Scenario 8.4：风险摘要

- Given 报告生成完成
- Then 保存最高风险等级和风险数量
- And 列表无需加载完整报告即可展示风险摘要

### Scenario 8.5：保留筛选状态

- Given 用户从筛选后的列表进入报告详情
- When 用户返回列表
- Then 搜索词、筛选条件和页码保持不变

## 能力点 9：旧数据回填、时区筛选与真实 GitHub 联调

### Scenario 9.1：旧报告回填

- Given 历史报告已有 `report` JSON，但 `search_text` 为空
- When 应用启动或执行回填
- Then 重新生成搜索文本
- And 重新计算最高风险等级和风险数量

### Scenario 9.2：上海时区日期筛选

- Given 报告时间在 UTC 2026-11-09 16:30
- When 用户筛选上海日期 2026-11-10
- Then 该报告应命中

### Scenario 9.3：真实 GitHub 联调

- Given 提供仓库名和可选 PAT
- When 执行联调脚本
- Then 验证仓库元数据、默认分支和 Compare API 可读取
- And 私有仓库必须使用最小权限 PAT

## 非目标

- 不实现 GitHub PR 评论。
- 不实现自动修复。
- 不承诺完整影响分析或零安全漏报。
- 不实现 GitHub App；V1 使用 Fine-grained PAT。
