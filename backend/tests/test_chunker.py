"""分块器测试：中文标点边界、块大小限制、结构化行不切断、元数据透传。"""
from app.services.ingest.chunker import chunk_sections
from app.services.ingest.parsers import ParsedSection


def _mk_section(text: str, structured: bool = False, **meta) -> ParsedSection:
    return ParsedSection(text=text, meta=meta, structured=structured)


class TestChunker:
    def test_chinese_sentence_boundary(self):
        # 500+ 字长文本，分隔符为中文标点
        text = "这是一段测试文本。" * 80
        chunks = chunk_sections([_mk_section(text)], "测试文档", "test.txt")
        assert len(chunks) > 1
        # 块尾通常以中文标点结尾（keep_separator="end"）
        for c in chunks:
            assert len(c["content"]) <= 600  # chunk_size 500 + overlap 容忍

    def test_meta_passthrough(self):
        text = "内容" * 100
        chunks = chunk_sections(
            [_mk_section(text, page=3)], "文档标题", "doc.txt"
        )
        for c in chunks:
            assert c["meta"]["page"] == 3
            assert c["meta"]["doc_title"] == "文档标题"
            assert c["meta"]["doc_name"] == "doc.txt"
            assert c["token_count"] > 0
            assert c["hash"]

    def test_structured_rows_not_split(self):
        rows = "\n".join(f"行{i} | 值{i}" for i in range(60))
        chunks = chunk_sections(
            [_mk_section(rows, structured=True, sheet="参数")], "表", "spec.xlsx"
        )
        assert len(chunks) == 3  # 60 行 / 每块 20 行
        first = chunks[0]["content"]
        assert first.startswith("行0 |")
        assert first.endswith("行19 | 值19")  # 行边界完整
        assert chunks[0]["meta"]["row_start"] == 1
        assert chunks[0]["meta"]["row_end"] == 20
