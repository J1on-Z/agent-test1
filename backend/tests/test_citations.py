"""引文机制测试：编号解析与上下文编号一致性。"""
from app.services.llm.prompts import build_context_blocks
from app.utils.text import parse_citation_indexes


class TestParseCitationIndexes:
    def test_normal(self):
        assert parse_citation_indexes("答案是【1】，另外【2】也提到", 3) == [1, 2]

    def test_out_of_range_filtered(self):
        assert parse_citation_indexes("【1】【99】【2】", 3) == [1, 2]

    def test_duplicates_removed_keep_first_order(self):
        assert parse_citation_indexes("【2】…【1】…【2】", 3) == [2, 1]

    def test_zero_citations(self):
        assert parse_citation_indexes("没有引用任何知识", 5) == []

    def test_mixed_english_brackets_ignored(self):
        # 英文方括号 [1] 与 markdown 链接不影响【】解析
        assert parse_citation_indexes("详见 [链接](url) 与【3】", 5) == [3]


class TestContextBlocks:
    def test_numbering_matches_index(self):
        chunks = [
            {"chunk_id": "c1", "content": "块一", "meta": {"doc_name": "a.pdf", "page": 2, "doc_title": "标题A"}, "score": 0.9},
            {"chunk_id": "c2", "content": "块二", "meta": {"doc_name": "b.md"}, "score": 0.8},
        ]
        blocks = build_context_blocks(chunks)
        assert "【1】《a.pdf》第2页 · 标题A（相关度 0.90）" in blocks
        assert "【2】《b.md》（相关度 0.80）" in blocks
        assert "块一" in blocks and "块二" in blocks
