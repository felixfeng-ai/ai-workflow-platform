# 代码提交分析报告技术方案

> 状态：V1 已实现，待真实 GitHub 私有仓库联调
> 目标版本：V1
> 更新时间：2026-11-09
> 关联需求：本地代码推送到 GitHub 分支后，在对应项目下自动生成代码提交分析报告

---

## 1. 背景与目标

AI 编程提高了代码产出速度，但一次改动可能包含大量文件、跨模块状态变化和潜在安全风险。当前平台只有项目、任务、部署和运行记录，没有面向代码变更的分析能力。

本功能要解决的问题：

1. 这次提交改了多少代码。
2. 这次提交实现了哪些功能点。
3. 涉及哪些模块、边界和状态管理。
4. 可能影响哪些调用方、接口、配置和测试。
5. 是否存在需要人工关注的安全风险。

目标不是替代人工 Code Review，而是生成一份有证据、可追溯、可复核的风险报告。

## 2. 范围

### 2.1 V1 目标

- 接收 GitHub `push` Webhook。
- 将 GitHub 仓库连接绑定到平台项目。
- 按一次 push 的 `before...after` 范围创建分析任务。
- 统计提交、文件、增删行、语言和变更类型。
- 使用 Semgrep 和 AI 生成结构化分析报告。
- 在项目详情页展示历史报告和报告详情。
- 报告详情支持下载真正的 Word `.docx` 文件。
- 分析完成或失败后发送站内通知。
- 严格隔离租户、仓库凭据和报告数据。

### 2.2 V1 不做

- 不向 GitHub PR 自动发表评论。
- 不自动修改代码或提交修复。
- 不承诺发现全部安全问题。
- 不实现完整跨仓库调用图和微服务依赖分析。
- 不把该功能建模成用户可自由编排的通用工作流。
- 不支持 GitLab、Bitbucket、Gitee，后续通过统一仓库连接模型扩展。

### 2.3 关键假设

- GitHub 仓库可以通过 Fine-grained PAT 或 GitHub App 访问。
- 平台后端可接收公网 HTTPS Webhook。
- 生产部署初期仍为单后端实例；后续多实例时需要分布式任务队列和调度锁。
- AI 使用平台现有 `AiEngine` 抽象。
- 报告只做风险提示和辅助决策，不作为安全合规认证。

## 3. 核心产品定义

### 3.1 分析单位

分析单位是一次 GitHub `push` 事件对应的提交范围，而不是单个 commit。

原因：

- 一个 push 可能包含多个 commit。
- 单 commit 分析会丢失跨 commit 的上下文。
- 一次 push 只生成一份完整报告，可以降低模型成本和通知噪音。
- 报告中仍保留逐 commit 摘要。

### 3.2 报告内容

报告固定包含：

1. 变更概览：分支、提交范围、提交数、文件数、增删行数。
2. 功能点：新增、修改、删除的能力。
3. 边界变化：模块边界、接口边界、数据边界、配置边界。
4. 状态管理：前端状态、后端状态、数据库状态、异步任务状态。
5. 影响分析：直接依赖、间接影响、接口契约、迁移和测试缺口。
6. 安全风险：确定性扫描结果和 AI 补充判断。
7. 人工复核清单。
8. 证据与限制：文件、行号、Commit、是否截断、置信度。

### 3.3 报告可信度原则

- 代码量统计必须由确定性算法生成。
- 安全问题必须优先来自静态扫描工具。
- AI 结论必须附证据，不能只输出自由文本。
- 上下文不足时必须降低置信度并明确写出未知项。
- 大型提交允许生成 `partial` 报告，不能假装完整分析。

## 4. 总体架构

```text
GitHub Repository
      │ push event
      ▼
POST /api/integrations/github/{connection_id}/webhook
      │
      ├─ 读取原始 body
      ├─ HMAC-SHA256 验签
      ├─ Delivery ID 去重
      └─ 校验仓库、分支和事件类型
      ▼
code_analysis_runs(pending)
      │
      ▼
CodeAnalysisRunManager
      │
      ├─ GitHub Compare API
      ├─ ChangeSet 归一化
      ├─ 文件过滤与截断
      ├─ Semgrep / Secret Scan
      ├─ 上下文构建
      ├─ AI 结构化分析
      └─ Markdown 渲染
      ▼
code_analysis_runs(succeeded / partial / failed)
      │
      ├─ 项目页「代码分析」Tab
      └─ 站内通知
```

## 5. GitHub 接入方案

### 5.1 鉴权方式

支持两种模式，代码层通过统一接口隔离：

```python
class GitHubRepoAuth(Protocol):
    async def get_headers(self) -> dict[str, str]: ...
```

#### 模式 A：Fine-grained PAT，V1 默认

- 每个项目独立配置 PAT。
- 权限只授予 `Contents: read` 和 `Metadata: read`。
- 只授权目标仓库。
- PAT 使用对称加密后落库。
- 公开仓库允许不配置 PAT，使用 GitHub 匿名只读 API。
- 不复用现有 `github_deploy_token`。

现有部署 Token 只适合 `Actions: write`，不能扩大为全仓库读取权限。

#### 模式 B：GitHub App，后续正式方案

- 通过 installation 获取短期 Token。
- 仓库选择由 GitHub 安装流程控制。
- Webhook 可以由 App 统一接收。
- 更适合多租户、私有仓库和正式商业化部署。

推荐路径：V1 先做 PAT 模式，但认证接口从一开始按多实现设计，避免后续重写业务链路。

### 5.2 仓库绑定

管理员在项目设置中填写：

- GitHub 仓库 URL。
- 访问 Token。
- 分析分支规则。
- 是否启用自动分析。

服务端必须调用 GitHub API 验证：

- 仓库可访问。
- 默认分支。
- 仓库 ID 和 `full_name`。
- Token 具备读取代码的权限。

验证通过后由服务端生成 Webhook Secret。Secret 只在创建时展示一次，加密保存。

### 5.3 Webhook 端点

```text
POST /api/integrations/github/{connection_id}/webhook
```

处理要求：

1. 使用 `await request.body()` 读取原始 body。
2. 校验 `X-Hub-Signature-256`。
3. 使用 `hmac.compare_digest` 做常量时间比较。
4. 使用 `X-GitHub-Delivery` 做幂等去重。
5. 只处理 `ping` 和 `push`。
6. 先落 `pending` run，再返回 `202`，不能同步跑分析。
7. Webhook 错误日志不得包含 body、源码、Token 或 Secret。

### 5.4 Push 事件处理规则

| 场景 | 处理方式 |
|---|---|
| 普通 push | 分析 `before...after` |
| 新分支，`before` 全零 | 与默认分支 merge base 比较；失败时退回最新 commit |
| Force push | 优先 compare；旧 SHA 不可用时退回最新 commit |
| 删除分支，`after` 全零 | 忽略 |
| 无 commit 的 push | 忽略 |
| 分支不匹配配置 | 返回 `204`，不创建 run |
| 重复 Delivery | 返回 `204`，不重复创建 |
| 同一 after SHA 重复触发 | 复用已有 run |

### 5.5 分支策略

项目级配置 `branch_patterns`，例如：

```json
["feature/*", "fix/*", "main"]
```

默认只分析非默认分支，是否分析 `main` 由项目配置决定。

## 6. 数据模型

新增两张表。所有查询必须带 `tenant_id`，跨租户与不存在统一返回 404。

### 6.1 project_repo_connections

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(36) | 连接 ID，也用于 Webhook 路径 |
| `tenant_id` | String(36) | 租户隔离键 |
| `project_id` | String(36) | 对应项目 |
| `provider` | String(20) | V1 固定 `github` |
| `auth_type` | String(20) | `pat` / `app` |
| `repository_id` | BigInteger | GitHub 稳定仓库 ID |
| `repo_full_name` | String(200) | `owner/repo` |
| `default_branch` | String(120) | 默认分支 |
| `branch_patterns` | JSON | 分析分支规则 |
| `webhook_secret_encrypted` | Text | Webhook Secret |
| `access_token_encrypted` | Text nullable | PAT |
| `installation_id` | BigInteger nullable | GitHub App 备用 |
| `enabled` | Boolean | 是否启用 |
| `created_by` | String(36) | 配置人 |
| `last_verified_at` | DateTime | 最近验证时间 |
| `last_error` | Text nullable | 最近错误 |

唯一约束：

- `(tenant_id, provider, repository_id)`。

### 6.2 code_analysis_runs

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(36) | 分析任务 ID |
| `tenant_id` | String(36) | 租户隔离键 |
| `project_id` | String(36) | 项目 |
| `connection_id` | String(36) | 仓库连接 |
| `trigger_type` | String(20) | `webhook` / `manual` |
| `delivery_id` | String(100) nullable | GitHub Delivery |
| `repo_full_name` | String(200) | 触发时仓库名 |
| `branch` | String(200) | 分支 |
| `before_sha` | String(40) | 起点 |
| `after_sha` | String(40) | 终点 |
| `pusher_login` | String(100) nullable | 推送人 |
| `head_commit_message` | Text nullable | 最新提交信息 |
| `status` | String(20) | `pending/running/succeeded/partial/failed` |
| `change_stats` | JSON | 变更统计 |
| `report` | JSON | 结构化报告 |
| `report_markdown` | Text nullable | 渲染结果 |
| `analysis_version` | String(20) | 报告 Schema 版本 |
| `ai_provider` | String(40) nullable | 实际模型提供方 |
| `ai_model` | String(100) nullable | 模型名 |
| `truncated` | Boolean | 是否截断分析 |
| `error` | Text nullable | 失败原因 |
| `started_at` | DateTime nullable | 开始时间 |
| `finished_at` | DateTime nullable | 完成时间 |

约束与索引：

- 唯一：`(connection_id, delivery_id)`，`delivery_id` 非空时生效。
- 唯一：`(connection_id, branch, before_sha, after_sha)`。
- 索引：`(project_id, created_at desc)`。
- 索引：`(tenant_id, status)`。

V1 不单独建 findings 表，安全发现保存在 `report` JSON 中。后续需要跨报告检索、忽略和跟踪时，再拆 `code_analysis_findings`。

## 7. API 设计

### 7.1 管理接口

```text
POST   /api/projects/{project_id}/code-analysis/config
GET    /api/projects/{project_id}/code-analysis/config
DELETE /api/projects/{project_id}/code-analysis/config
POST   /api/projects/{project_id}/code-analysis/verify
```

权限：

- 配置和验证：`owner`。
- 查看报告：`owner`、`member`、`readonly`。

### 7.2 运行接口

```text
POST /api/projects/{project_id}/code-analysis/runs
GET  /api/projects/{project_id}/code-analysis/runs
GET  /api/projects/{project_id}/code-analysis/runs/{run_id}
POST /api/projects/{project_id}/code-analysis/runs/{run_id}/retry
```

`POST /runs` 用于手动补跑，支持传入 `branch` 和 `after_sha`；不传时使用默认分支最新提交。

`GET /runs` 返回分页结构 `{items,total,page,page_size}`，支持 `keyword`、`status`、`branch`、`date_from`、`date_to` 和最低 `severity` 筛选。报告完成时会冗余生成 `search_text`、`max_severity` 和 `finding_count`，避免列表查询解析完整 JSON。

日期筛选按 `settings.scheduler_timezone`（默认 `Asia/Shanghai`）解释为自然日，再转换为 UTC 查询。应用启动时会回填旧报告缺失的搜索文本和风险摘要。

真实 GitHub 联调可执行：

```bash
cd backend
python scripts/check_github_integration.py --repo owner/repo
python scripts/check_github_integration.py --repo owner/private-repo --token "$GITHUB_TEST_TOKEN"
```

### 7.3 Webhook 接口

```text
POST /api/integrations/github/{connection_id}/webhook
```

响应约定：

- 验签失败：`401`。
- 未知连接：`404`。
- 事件被忽略：`204`。
- 已接受分析：`202`。
- 上游暂时不可用：`503`，由 GitHub 重试。

## 8. 分析流水线

### 8.1 Stage 1：拉取变更

使用 GitHub Compare API：

```text
GET /repos/{owner}/{repo}/compare/{before}...{after}
```

归一化为内部 `ChangeSet`：

```python
class ChangedFile:
    path: str
    old_path: str | None
    status: str
    additions: int
    deletions: int
    language: str | None
    patch: str | None
    is_binary: bool
    is_generated: bool
    is_truncated: bool
```

过滤规则：

- 锁文件：`package-lock.json`、`pnpm-lock.yaml`、`poetry.lock` 等。
- 生成产物：`dist/`、`build/`、`coverage/`、压缩文件。
- 二进制文件。
- 超大文件。
- 项目自定义忽略规则，V1 使用内置规则，V2 支持仓库配置文件。

限制：

- 最大分析文件数。
- 最大 diff 字符数。
- 最大 commit 数。
- 最大单文件字符数。

超过限制时：

- 优先保留业务源码、迁移、配置和测试。
- 标记 `truncated=true`。
- 报告状态使用 `partial`。

### 8.2 Stage 2：确定性分析

不依赖 AI 计算：

- commit 数。
- 文件数。
- 增删行数。
- 新增、修改、删除、重命名文件数。
- 语言分布。
- 模块分布。
- 测试文件变更。
- 配置和迁移文件变更。
- 大文件和高风险路径提示。

### 8.3 Stage 3：安全扫描

V1 使用 Semgrep：

- 只扫描当前 `after_sha` 的仓库快照。
- 使用本地规则集，避免私有部署依赖外网。
- 只保留本次 diff 命中的发现。
- 输出统一结构，不直接存原始终端文本。

后续扩展：

- Secret 扫描。
- 依赖漏洞扫描。
- IaC 和容器扫描。

扫描执行要求：

- 独立临时目录。
- 禁止网络。
- 非 root 执行。
- CPU、内存、文件大小和运行时间限制。
- 结束后强制清理。

V1 可先在后台进程内以子进程执行。正式环境必须迁移到独立分析 Worker 或沙箱容器。

### 8.4 Stage 4：上下文构建

AI 不能只看 patch。上下文按优先级组装：

1. 改动 hunk 前后代码。
2. 改动文件完整内容，按大小截断。
3. 改动文件中的 import 和导出符号。
4. 相关测试文件。
5. 同一模块的配置文件。
6. 静态扫描发现附近代码。

V2 引入 Tree-sitter Code Graph：

- 函数和类节点。
- import 和 call 关系。
- 反向调用方。
- 相关测试。
- Blast Radius。

可复用 `code-review-graph` 的 Tree-sitter 图模型和影响半径思路，但不直接嵌入其 CLI 产物作为平台协议。

### 8.5 Stage 5：AI 结构化分析

AI 输入：

- 仓库语言和目录摘要。
- commit message。
- 变更统计。
- 过滤后的 diff。
- 文件上下文。
- Semgrep 发现。

AI 输出必须是 JSON，不接受自由 Markdown 作为唯一结果。

大提交使用 Map-Reduce：

1. 按文件或模块分批生成局部摘要。
2. 汇总功能点、边界和状态变化。
3. 生成全局影响和风险。
4. 最后生成 Markdown。

如果 JSON 校验失败：

1. 进行一次修复调用。
2. 再失败则降级为确定性报告加 AI 摘要。
3. 报告中明确标记 AI 结构化分析失败。

### 8.6 Stage 6：结果落库与通知

- 保存 `report` JSON 和 `report_markdown`。
- 更新状态、时间、模型和截断信息。
- 发送 `code_analysis` 类型通知。
- 通知失败不能回滚分析结果。

## 9. 报告 JSON Schema

```json
{
  "schema_version": "1.0",
  "summary": "本次提交主要完成了什么",
  "change_scale": {
    "commits": 3,
    "files": 18,
    "additions": 420,
    "deletions": 95,
    "languages": {"python": 8, "typescript": 7},
    "categories": {"source": 12, "test": 3, "config": 2, "docs": 1},
    "truncated": false
  },
  "functional_points": [
    {
      "title": "新增 GitHub Webhook 接收",
      "description": "支持 push 事件验签、去重和任务投递",
      "files": ["backend/app/api/github.py"],
      "confidence": "high"
    }
  ],
  "boundaries": [
    {
      "module": "code-analysis",
      "boundary_type": "api",
      "description": "Webhook 入口与业务 API 分离",
      "evidence": ["backend/app/api/github.py:20"],
      "confidence": "medium"
    }
  ],
  "state_management": [
    {
      "area": "code_analysis_runs",
      "mechanism": "数据库状态机",
      "risk": "服务重启时 running 任务可能悬挂",
      "evidence": ["backend/app/models/code_analysis.py:30"],
      "confidence": "high"
    }
  ],
  "impact": {
    "direct": ["项目详情页新增 Tab", "通知类型新增 code_analysis"],
    "indirect": ["DataLayer 契约需要同步 demo 实现"],
    "external_contracts": ["GitHub Webhook"],
    "migrations": [],
    "test_gaps": ["缺少 Force Push 场景测试"]
  },
  "security_findings": [
    {
      "severity": "high",
      "category": "secret",
      "title": "可能存在硬编码凭据",
      "file": "backend/app/example.py",
      "line": 42,
      "source": "semgrep",
      "evidence": "rule_id=generic.secrets",
      "recommendation": "改为环境变量并轮换凭据",
      "confidence": "high"
    }
  ],
  "risks": [],
  "review_checklist": [],
  "unknowns": [],
  "limitations": []
}
```

约束：

- `confidence` 只能是 `high/medium/low`。
- `severity` 只能是 `critical/high/medium/low/info`。
- `source` 只能是 `semgrep`、`secret_scan`、`ai`、`heuristic`。
- 每条 AI 风险至少包含一个证据或明确写入 `unknowns`。
- GitHub 文件链接使用 `after_sha` 生成永久链接。

## 10. 后端模块设计

建议新增：

```text
backend/app/
  models/
    code_analysis.py
  schemas/
    code_analysis.py
  api/
    github_webhooks.py
    code_analysis.py
  services/
    github/
      client.py
      auth.py
      webhook.py
    code_analysis/
      diff.py
      filters.py
      context.py
      scanner.py
      analyzer.py
      report.py
      runner.py
```

职责边界：

- `api/github_webhooks.py`：原始 body、验签、事件识别、快速返回。
- `services/github/auth.py`：PAT 和 GitHub App 认证。
- `services/github/client.py`：Compare、Commit、Tree、Content API。
- `services/code_analysis/diff.py`：ChangeSet 和代码量统计。
- `services/code_analysis/filters.py`：忽略文件、截断和优先级。
- `services/code_analysis/context.py`：上下文组装。
- `services/code_analysis/scanner.py`：Semgrep 适配。
- `services/code_analysis/analyzer.py`：AI 调用和 JSON 校验。
- `services/code_analysis/report.py`：Markdown 渲染。
- `services/code_analysis/runner.py`：状态机和后台执行。

不建议把整个逻辑塞进 `projects.py` 或现有 `workflows` 模块。

## 11. 前端设计

### 11.1 项目页

在 `ProjectPage` 增加 Tab：

```text
概览 | 知识库 | 文档 | 代码分析
```

列表展示：

- 分支。
- Commit 短 SHA 和提交信息。
- 推送人。
- 文件数、增删行数。
- 状态。
- 风险等级。
- 生成时间。

详情展示：

- 变更概览指标卡。
- 功能点列表。
- 边界与状态管理分析。
- 影响范围。
- 安全发现。
- 测试缺口。
- 人工复核清单。
- GitHub 证据链接。
- 截断和置信度说明。

### 11.2 配置页

由项目 owner 配置：

- GitHub 仓库地址。
- Token。
- Webhook URL 和 Secret。
- 分支规则。
- 自动分析开关。
- 手动验证连接。

Token 和 Secret 保存后不再回显明文。

### 11.3 DataLayer

需要同步修改：

- `frontend/src/types.ts`
- `frontend/src/lib/view.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/demo.ts`

演示模式必须提供至少两条样例报告，否则 TypeScript 契约门禁会失败。

## 12. 通知

新增通知类型：

```text
code_analysis
```

触发事件：

- 分析完成。
- 分析部分完成。
- 分析失败。

通知正文包含：

- 项目名。
- 分支。
- 提交短 SHA。
- 文件数和增删行数。
- 高风险发现数量。

通知失败使用现有 SAVEPOINT 隔离，不能影响分析结果落库。

## 13. 安全设计

### 13.1 Webhook

- HMAC-SHA256 验签。
- 原始 body 校验，不能使用重新序列化后的 JSON。
- 常量时间比较。
- Delivery ID 幂等。
- 按连接和 IP 限流。
- 不在日志中记录原始 body。

### 13.2 凭据

- PAT 和 Webhook Secret 使用 Fernet 对称加密。
- 加密密钥来自环境变量 `APP_ENCRYPTION_KEY`。
- 未配置密钥时禁用该功能，不能明文降级。
- 接口只返回“已配置”状态，不返回明文。
- 删除连接时清理加密字段。

### 13.3 数据隔离

- 所有查询按 `tenant_id` 过滤。
- 跨租户访问统一返回 404。
- Webhook 通过连接 ID 和 Secret 找到租户，不信任请求体中的 tenant 信息。
- 报告中的证据链接不能暴露其他仓库凭据。

### 13.4 代码处理

- 临时目录随机生成。
- 解压防止路径穿越。
- 限制压缩包和解压后大小。
- Semgrep 扫描不执行用户代码。
- 扫描进程设置 CPU、内存和超时。
- 分析结束后删除源码临时文件。
- 默认不保存完整 diff 和完整源码。

### 13.5 AI

- 只发送完成分析所需的最小上下文。
- 日志不记录 Prompt 中的源码。
- 报告明确标记 AI 推断和确定性扫描结果。
- 不把 AI 安全结论描述为“已确认无漏洞”。

## 14. 异步、可靠性与成本

### 14.1 任务管理

V1 复用现有 `asyncio.create_task` 模式：

```text
pending -> running -> succeeded / partial / failed
```

增加：

- 全局并发信号量。
- 单连接并发限制。
- 任务取消。
- 超时。
- 临时错误重试。
- 启动时扫描悬挂任务。

### 14.2 重试策略

自动重试：

- GitHub 429、5xx 和网络超时。
- AI 临时错误。

不自动重试：

- 验签失败。
- 仓库无权限。
- 分支被忽略。
- 报告 Schema 永久不合法。

默认最多重试 2 次，使用指数退避。

### 14.3 成本控制

- 每项目每月最大分析次数。
- 单次最大 diff 字符数。
- 单次最大 AI 输入 Token。
- 过滤 lock 文件和生成代码。
- 大提交先做文件摘要，再做全局汇总。
- 同一 `after_sha` 不重复分析。
- 快速连续 push 可配置“只分析最新 head”。

## 15. 测试方案

### 15.1 Webhook

- 正确签名。
- 缺失签名。
- 错误签名。
- 重复 Delivery。
- `ping` 事件。
- 非 push 事件。
- 未知连接。
- 分支不匹配。
- 新分支 `before=000000`。
- Force push。
- 删除分支。

### 15.2 分析流水线

- 代码量统计。
- 文件过滤。
- 大提交截断。
- 二进制和重命名文件。
- Semgrep 结果归一化。
- AI JSON 合法输出。
- AI JSON 非法输出后降级。
- 报告 Markdown 渲染。

### 15.3 权限与隔离

- owner 配置。
- member 不能配置。
- readonly 只能查看。
- 跨租户访问 404。
- Token 和 Secret 不明文返回。

### 15.4 前端

- 项目页 Tab。
- 报告列表。
- 报告详情。
- 失败和 partial 状态。
- 演示模式。
- `tsc` 类型契约。

### 15.5 PostgreSQL

- Alembic 迁移。
- JSON 字段读写。
- 唯一约束冲突。
- 时区字段。

GitHub、Semgrep 和 AI 均使用接口注入，测试中使用 Fake，不依赖真实外网。

## 16. 实施阶段

### Phase 1：基础链路，1-2 周

- 数据模型和迁移。
- 项目仓库连接配置。
- Webhook 验签和 push 事件。
- GitHub Compare API。
- 变更统计。
- 手动触发分析。
- 基础 Semgrep 扫描。
- 最小报告详情页。

### Phase 2：可用 MVP，3-5 周

- AI 结构化报告。
- 大提交截断和 Map-Reduce。
- 分支规则。
- 通知。
- 历史列表和重试。
- 完整权限、租户隔离和测试。
- 演示数据。

### Phase 3：生产增强，2-3 个月

- GitHub App。
- 独立分析 Worker/沙箱。
- Tree-sitter Code Graph。
- 影响半径和测试缺口。
- Secret 扫描和依赖扫描。
- 成本配额、运行追踪和管理后台。

## 17. 验收标准

功能验收：

- 推送代码到受支持分支后，30 秒内创建分析任务。
- 常规提交在 5 分钟内生成报告。
- 项目页能看到报告历史和详情。
- 报告包含变更量、功能点、边界、状态、影响、安全、测试缺口。
- 分析完成或失败会发送通知。

安全验收：

- 错误签名无法触发分析。
- 重复 Delivery 不重复生成报告。
- Token 和 Secret 不以明文出现在 API、日志和数据库中。
- 跨租户无法读取连接和报告。

质量验收：

- 新代码通过后端单元测试。
- PostgreSQL 集成测试通过。
- 前端 `npm run build` 通过。
- 大提交、Force Push 和新分支有测试覆盖。
- 报告明确展示截断、置信度和未知项。

## 18. 风险与待确认项

| 风险 | 处理 |
|---|---|
| 多租户 PAT 管理复杂 | V1 明确 PAT 为过渡方案，后续 GitHub App |
| 影响分析准确度不足 | V1 明确置信度，V2 引入 Code Graph |
| Semgrep 在单容器中运行不安全 | V1 设资源上限，V2 独立沙箱 |
| AI 误报或漏报安全问题 | 以静态扫描为主，AI 只做补充和解释 |
| 大型提交成本过高 | 文件过滤、截断、Map-Reduce 和配额 |
| 快速连续 push 产生大量任务 | 按 SHA 去重，可配置只分析最新 head |
| 服务重启导致 running 悬挂 | 启动恢复扫描和超时失败机制 |

开发前需要最终确认：

1. V1 是否接受项目级 Fine-grained PAT。
2. 默认分析哪些分支。
3. 是否接受报告最长等待 5 分钟。
4. 是否把 Semgrep 作为后端内置依赖，还是独立 Worker。
5. V1 是否只支持 GitHub。

---

本方案是技术设计文档，不代表业务代码已经实现。确认上述待确认项后，再按 TDD 进入数据模型、Webhook 和最小报告闭环的实现。
