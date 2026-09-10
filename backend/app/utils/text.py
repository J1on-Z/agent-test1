"""文本工具：引文编号解析、中文清洗、标题截断。

引文约定：生成提示词要求模型在引用知识库内容时标注【数字】，
数字与上下文模板中的分块编号一一对应（【】而非 []，避开 Markdown 链接语法）。
解析在流式结束后对完整回答做一次全量正则，比边流边解析简单可靠。
"""
import re

_CITE_RE = re.compile(r"【(\d{1,2})】")


def parse_citation_indexes(answer: str, max_index: int) -> list[int]:
    """提取回答中的引文编号：首次出现顺序去重、过滤越界编号。

    :param answer: 完整回答文本
    :param max_index: 上下文分块总数 K（编号合法范围 1..K）
    :return: 去重且有序的合法编号列表
    """
    seen: list[int] = []
    for m in _CITE_RE.finditer(answer):
        idx = int(m.group(1))
        if 1 <= idx <= max_index and idx not in seen:
            seen.append(idx)
    return seen


def clean_text(text: str) -> str:
    """清洗解析出的文档文本：压缩多余空白、统一换行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_title(text: str, max_len: int = 20) -> str:
    """首条用户消息截断为会话标题。"""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def count_tokens_approx(text: str) -> int:
    """无 tokenizer 时的近似 token 估算（中文约 1 字 1 token，英文约 4 字符 1 token）。"""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + other // 4
