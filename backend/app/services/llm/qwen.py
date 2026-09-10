"""通义千问 LLM 工厂：ChatOpenAI 指向 DashScope compatible-mode 端点。

特性：
- 全局并发信号量（DashScope 有 RPM/TPM 限速）
- 限流时自动降级到备用模型（LLM_FALLBACK_MODEL）
- 思考模式（enable_thinking）：reasoning_content 从 additional_kwargs 提取，
  供前端「思考过程」折叠块展示
"""
import logging
import threading
from functools import lru_cache

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# 全局并发信号量：跨请求限制同时进行的 LLM 调用数
_llm_semaphore = threading.Semaphore(settings.llm_max_concurrency)

# 全局用量收集：从回调聚合 token 统计（用于 request_logs / 成本估算）
_usage_registry: dict[str, dict] = {}
_usage_lock = threading.Lock()


class UsageCollector(BaseCallbackHandler):
    """收集一次 LLM 调用的 token 用量到注册表（按 run_id 聚合流式增量）。"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        usage = (response.llm_output or {}).get("token_usage") or {}
        self._usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        with _usage_lock:
            _usage_registry[self.run_id] = self._usage

    @property
    def usage(self) -> dict:
        return self._usage


def pop_usage(run_id: str) -> dict:
    """取出并清除某次调用的用量统计。"""
    with _usage_lock:
        return _usage_registry.pop(run_id, None)


@lru_cache
def get_llm(model: str, thinking: bool = False) -> ChatOpenAI:
    """按模型名/思考开关构建 ChatOpenAI（lru_cache 复用实例）。"""
    kwargs: dict = dict(
        model=model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        stream_usage=True,  # 流式响应追加 include_usage，末尾 chunk 携带 token 统计
    )
    if thinking:
        # 思考模式：reasoning_content 出现在 AIMessage.additional_kwargs 中
        kwargs["extra_body"] = {"enable_thinking": True}
        kwargs["temperature"] = 0.0
    else:
        # qwen3.x 系列默认开启思考，非思考模式需显式关闭（提速 + 省 token）；
        # 额外参数必须走 extra_body 透传（openai SDK 严格校验顶层参数）
        kwargs["extra_body"] = {"enable_thinking": False}
    return ChatOpenAI(**kwargs)


def resolve_model(model: str | None) -> str:
    """校验并解析用户请求的模型名（白名单，防止任意模型注入）。"""
    allowed = {settings.llm_model, settings.llm_model_strong, settings.llm_fallback_model}
    allowed.discard("")
    if model and model in allowed:
        return model
    return settings.llm_model
