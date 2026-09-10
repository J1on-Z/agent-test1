"""中文友好分块器。

- 文本段：RecursiveCharacterTextSplitter，分隔符按中文标点优先级（段落→换行→。？！；→，→空格）
- 结构化段（表格）：按行分组切片，行永不切断，meta 记录行号范围
- 输出 chunk dict：{content, meta{...来源定位, title}, token_count, hash}
"""
import logging

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.utils.hashing import sha256_text
from app.utils.text import count_tokens_approx

logger = logging.getLogger(__name__)

# 结构化段按行分组的目标行数（约 500 字/块）
_STRUCT_ROW_BUDGET = 20


def build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "？", "！", "；", "，", " ", ""],
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        keep_separator="end",  # 标点留在句尾，避免句号孤悬在下一块开头
        strip_whitespace=True,
    )


def chunk_sections(
    sections: list, doc_title: str, doc_filename: str
) -> list[dict]:
    """把解析出的文本段切分为最终入库的 chunk 列表。

    :return: [{content, meta, token_count, hash}]，meta 含 page/sheet/row/title/doc_title
    """
    splitter = build_splitter()
    chunks: list[dict] = []
    for section in sections:
        section_meta = dict(section.meta)
        if section.structured:
            _chunk_structured(section.text, section_meta, doc_title, chunks)
        else:
            pieces = splitter.split_text(section.text)
            for piece in pieces:
                chunks.append(
                    _make_chunk(piece, {**section_meta, "doc_title": doc_title})
                )
    # 记录来源文件名（与 doc_title 分离：title 用于定位章节，filename 用于引文展示）
    for c in chunks:
        c["meta"]["doc_name"] = doc_filename
    return chunks


def _chunk_structured(text: str, meta: dict, doc_title: str, out: list[dict]) -> None:
    """表格类文本按行分组，保证每一行完整落在某个 chunk 内。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for i in range(0, len(lines), _STRUCT_ROW_BUDGET):
        group = lines[i : i + _STRUCT_ROW_BUDGET]
        row_meta = {
            **meta,
            "doc_title": doc_title,
            "row_start": i + 1,
            "row_end": i + len(group),
        }
        out.append(_make_chunk("\n".join(group), row_meta))


def _make_chunk(content: str, meta: dict) -> dict:
    return {
        "content": content,
        "meta": meta,
        "token_count": count_tokens_approx(content),
        "hash": sha256_text(content),
    }
