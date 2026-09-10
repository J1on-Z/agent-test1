"""集中管理全部配置项，从 .env / 环境变量读取（pydantic-settings）。"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/），所有相对路径均以此为基准
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 基础 ----------
    app_name: str = "ECommerceRAG"
    app_env: str = "dev"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    log_level: str = "INFO"
    log_dir: str = "./logs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- 安全 ----------
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    bcrypt_rounds: int = 12
    admin_username: str = "admin"
    admin_password: str = "123456"

    # ---------- 数据库与存储 ----------
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    chroma_dir: str = "./data/chroma"
    upload_dir: str = "./data/uploads"
    max_upload_size_mb: int = 20
    allowed_extensions: str = ".pdf,.docx,.xlsx,.md,.txt"

    # ---------- LLM（阿里云百炼 DashScope 通义千问） ----------
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # rerank 走 DashScope 原生协议（非 OpenAI 兼容），端点通常与 base_url 同域
    dashscope_native_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    llm_model: str = "qwen-plus"
    llm_model_strong: str = "qwen-max"
    llm_fallback_model: str = ""  # 限流时自动降级（留空 = 不降级）
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3
    llm_max_concurrency: int = 3
    llm_thinking_enabled: bool = False

    # ---------- Embedding（DashScope 通义千问） ----------
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embedding_batch_size: int = 10  # compatible-mode 单请求最多 10 条

    # ---------- Rerank（DashScope qwen3.7-text-rerank，原生协议） ----------
    rerank_enabled: bool = True
    rerank_model: str = "qwen3.7-text-rerank"
    # 工作空间网关路径为双段 text-rerank/text-rerank；公共云为 /services/rerank/text-rerank
    rerank_path: str = "/services/rerank/text-rerank/text-rerank"
    rerank_top_n: int = 5
    rerank_score_threshold: float = 0.35

    # ---------- 检索 ----------
    vector_search_k: int = 10
    bm25_search_k: int = 10
    rrf_k: int = 60
    candidate_k: int = 12
    final_top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 80
    max_context_chars: int = 12000  # 上下文预算（约 8K token）

    # ---------- 流水线开关 ----------
    query_rewrite_enabled: bool = True
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.92
    semantic_cache_ttl_hours: int = 24
    semantic_cache_memory_aware: bool = True
    memory_window_messages: int = 6
    summary_trigger_messages: int = 10

    # ---------- 限流（slowapi） ----------
    rate_limit_global: str = "120/minute"
    rate_limit_chat: str = "10/minute"
    rate_limit_login: str = "5/minute"

    # ---------- 成本与后台 ----------
    price_input_per_1m: float = 0.8   # qwen-plus 输入单价（元/百万 token）
    price_output_per_1m: float = 2.0  # qwen-plus 输出单价（元/百万 token）
    ingest_workers: int = 2

    # ---------- 派生属性 ----------
    @property
    def allowed_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def chroma_path(self) -> Path:
        return self.resolve_path(self.chroma_dir)

    @property
    def upload_path(self) -> Path:
        return self.resolve_path(self.upload_dir)

    def resolve_path(self, raw: str) -> Path:
        """相对路径统一解析到 backend/ 下，避免 CWD 漂移。"""
        p = Path(raw)
        return p if p.is_absolute() else (BASE_DIR / p)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
