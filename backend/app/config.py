from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "雅秩"
    database_url: str = "sqlite+aiosqlite:///./projecthub.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    dify_api_url: str = "http://localhost:5001/v1"
    dify_api_key: str = ""
    # AI 引擎选择：dify（Dify CE headless）| openai_compatible（DeepSeek/通义等）
    ai_provider: str = "dify"
    openai_compatible_base_url: str = "https://api.deepseek.com"
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "deepseek-chat"
    # 定时调度时区（单 worker 进程内 APScheduler）
    scheduler_timezone: str = "Asia/Shanghai"
    # Agent fetch_url 工具
    agent_fetch_timeout: float = 15
    agent_fetch_max_chars: int = 8000
    # 知识库 RAG（R8/R9/R10）
    rag_top_k: int = 5
    rag_chunk_chars: int = 600
    rag_scan_extensions: list[str] = ["md", "txt", "markdown"]
    rag_max_upload_mb: int = 10
    # AI 对话副驾（Copilot）
    copilot_max_history: int = 6  # 意图路由/流式回答保留的对话历史条数
    copilot_agent_timeout: float = 90  # 副驾内运行智能体的总超时（秒），单次 LLM 缺口 <120s
    copilot_stream_read_timeout: float = 60  # 流式读取「字节间隔」超时（秒），非总时长
    # AI 写作（续写/润色/总结）：单次处理文本上限，超限续写截尾部、改写报错
    writing_max_chars: int = 12000
    # 限流（进程内滑动窗口，按来源 IP + scope，单 worker 部署有效）
    ratelimit_enabled: bool = True
    ratelimit_auth_per_min: int = 10  # 登录/注册，防爆破
    ratelimit_llm_per_min: int = 20  # AI 对话/知识问答，控成本
    ratelimit_run_per_min: int = 10  # Agent/工作流触发，防误触
    ratelimit_upload_per_min: int = 30  # 文档上传
    # 访客体验入口（POST /api/auth/guest）：免注册进入共享演示租户。
    # 公开部署上这是一个对匿名访客开放的门，不需要时置 false 关掉。
    guest_access_enabled: bool = True
    # 远程触发 GitHub Actions 部署（POST /api/projects/{id}/deploy）
    # 留空 = 功能整体关闭，端点返回 503，前端不显示「部署」按钮。
    # 这个 token 能触发本组织下仓库的 workflow，务必用 fine-grained PAT
    # 且只勾 Actions:write、只授权需要部署的仓库 —— 不要用全权限经典 PAT。
    github_deploy_token: str = ""
    # GitHub API 基址。独立成配置项是为了测试能指向 mock server。
    github_api_base: str = "https://api.github.com"
    # 微信小程序订阅消息（R16）
    wechat_appid: str = ""
    wechat_secret: str = ""
    wechat_template_due: str = ""


settings = Settings()
