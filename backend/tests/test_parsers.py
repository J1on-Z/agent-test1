"""文档解析器测试：用 sample_docs 真实生成文件覆盖 5 种格式。"""
import pytest

from app.config import settings
from app.services.ingest.parsers import ParseError, parse_file

SAMPLE_DIR = settings.resolve_path("data/sample_docs")


def _find(name_part: str):
    matches = list(SAMPLE_DIR.glob(f"*{name_part}*"))
    if not matches:
        pytest.skip(f"示例文档未生成: {name_part}")
    return matches[0]


class TestParsers:
    def test_parse_pdf(self):
        path = _find("星辰X1Pro智能手机-商品详情.pdf")
        sections, title = parse_file(path, "pdf")
        assert len(sections) >= 1
        assert any("星辰X1 Pro" in s.text for s in sections)
        assert sections[0].meta["page"] == 1
        assert title  # 标题不为空

    def test_parse_md(self):
        path = _find("商品详情.md")
        sections, title = parse_file(path, "md")
        assert any(sections)
        assert "# " in sections[0].text  # 保留 markdown 结构
        assert sections[0].meta.get("title")  # 提取首个 # 标题

    def test_parse_docx(self):
        path = _find("商品详情.docx")
        sections, title = parse_file(path, "docx")
        assert any(s.text for s in sections)
        assert title

    def test_parse_xlsx_structured_rows(self):
        path = _find("规格参数.xlsx")
        sections, title = parse_file(path, "xlsx")
        assert sections and sections[0].structured
        assert "参数项" in sections[0].text
        assert sections[0].meta["sheet"] == "规格参数"

    def test_parse_txt_gbk_fallback(self):
        path = _find("物流配送说明.txt")
        sections, title = parse_file(path, "txt")
        assert "发货" in sections[0].text

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ParseError):
            parse_file(empty, "txt")

    def test_unsupported_type_raises(self, tmp_path):
        f = tmp_path / "x.exe"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ParseError):
            parse_file(f, "exe")
