"""Embedding 封装：OpenAIEmbeddings 指向 DashScope compatible-mode 端点。

qwen3.7-text-embedding 输出 1024 维；批量调用受 DashScope 单请求 10 条限制，
langchain 内部会按 chunk_size 分批（tenacity 重试由 OpenAI 客户端内置）。
"""
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import settings


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        chunk_size=settings.embedding_batch_size,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        # 非 OpenAI 官方服务的关键开关（langchain-openai 官方文档建议）：
        # check_embedding_ctx_length=False → 直接发原始文本而非 token 数组
        # encoding_format="float" → 返回普通浮点数组而非 base64（部分网关不支持）
        check_embedding_ctx_length=False,
        encoding_format="float",
    )
