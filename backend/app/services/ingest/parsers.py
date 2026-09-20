"""多格式文档解析器：pdf / docx / xlsx / md / txt → 结构化文本段。

统一输出 list[ParsedSection]，meta 携带来源定位信息（页码/工作表/行号/标题），
随分块一路透传到引文展示（回答中可定位「《xxx.pdf》第 2 页」）。
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = ("pdf", "docx", "xlsx", "md", "txt")


@dataclass
class ParsedSection:
    """解析出的一段文本及其来源定位信息。"""

    text: str
    meta: dict = field(default_factory=dict)
    structured: bool = False  # 表格类结构化文本（分块时按行分组，避免切断行）


class ParseError(BizError):
    def __init__(self, message: str):
        super().__init__("parse_error", message, 422)


def parse_file(path: Path, file_type: str) -> tuple[list[ParsedSection], str]:
    """解析文件，返回 (文本段列表, 文档标题)。"""
    file_type = file_type.lower()
    if file_type not in SUPPORTED_TYPES:
        raise ParseError(f"不支持的文件类型: {file_type}")
    parser = _PARSERS[file_type]
    sections = parser(path)
    if not sections or not any(s.text.strip() for s in sections):
        hint = (
            "；可在 .env 设置 OCR_ENABLED=true 自动识别扫描件"
            if not settings.ocr_enabled
            else ""
        )
        raise ParseError("未能从文件中提取到任何文本（可能为扫描件或空文件）" + hint)
    title = _extract_title(sections, path, file_type)
    return sections, title


# ---------------------------------------------------------------- 各格式解析

def _parse_pdf(path: Path) -> list[ParsedSection]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    sections = []
    empty_pages: list[int] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            sections.append(ParsedSection(text=text, meta={"page": i + 1}))
        else:
            empty_pages.append(i + 1)

    # 扫描件回退：无文字层的页面渲染成图片，交给多模态模型识别（同步，线程池内运行）
    if empty_pages and settings.ocr_enabled:
        if len(empty_pages) > settings.ocr_max_pages:
            raise ParseError(
                f"扫描页数（{len(empty_pages)} 页）超过 OCR 上限（{settings.ocr_max_pages} 页），"
                "请拆分文档或调整 OCR_MAX_PAGES"
            )
        ocr_sections = _ocr_pdf_pages(path, empty_pages)
        sections.extend(ocr_sections)
        sections.sort(key=lambda s: s.meta.get("page", 0))
    return sections


def _ocr_pdf_pages(path: Path, pages: list[int]) -> list[ParsedSection]:
    """渲染指定 PDF 页为图片，逐页调用多模态模型识别文字。"""
    import base64

    import pymupdf

    logger.info("扫描件 OCR 回退：%s 共 %d 页（模型 %s）", path.name, len(pages), settings.ocr_model)
    doc = pymupdf.open(str(path))
    try:
        out: list[ParsedSection] = []
        for pno in pages:
            pix = doc[pno - 1].get_pixmap(dpi=settings.ocr_dpi)
            b64 = base64.b64encode(pix.tobytes("png")).decode()
            text = _call_ocr(b64)
            if text.strip():
                out.append(ParsedSection(text=text.strip(), meta={"page": pno}))
            else:
                logger.warning("OCR 第 %d 页无结果", pno)
        return out
    finally:
        doc.close()


def _call_ocr(image_b64: str) -> str:
    """多模态识别（compatible-mode，图片以 data URL 传入），失败重试一次。"""
    import httpx

    body = {
        "model": settings.ocr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请完整识别图片中的所有文字内容（包含表格时按行列输出）。"
                            "只输出识别出的文字，不要任何解释或补充。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 4096,
    }
    last_err = ""
    for _ in range(2):
        try:
            resp = httpx.post(
                f"{settings.dashscope_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
                json=body,
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"] or ""
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.HTTPError as exc:
            last_err = str(exc)
    raise ParseError(f"扫描页 OCR 识别失败（模型 {settings.ocr_model}）：{last_err}")


def _parse_docx(path: Path) -> list[ParsedSection]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(str(path))
    sections: list[ParsedSection] = []

    def iter_block_items(parent):
        """按文档顺序遍历段落与表格（python-docx 官方推荐写法）。"""
        for child in parent.element.body.iterchildren():
            if child.tag.endswith("}p"):
                yield Paragraph(child, parent)
            elif child.tag.endswith("}tbl"):
                yield Table(child, parent)

    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                style = block.style.name if block.style else ""
                meta = {"title": text} if style.lower().startswith("heading") else {}
                sections.append(ParsedSection(text=text, meta=meta))
        else:  # 表格：每行一条 "列名: 值" 文本，保证结构完整
            rows = []
            for row in block.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                # 去掉相邻重复单元格（合并单元格产生的重复值）
                cells = [c for i, c in enumerate(cells) if i == 0 or c != cells[i - 1]]
                line = " | ".join(c for c in cells if c)
                if line:
                    rows.append(line)
            if rows:
                sections.append(
                    ParsedSection(text="\n".join(rows), meta={}, structured=True)
                )
    return sections


def _parse_xlsx(path: Path) -> list[ParsedSection]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    sections: list[ParsedSection] = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            values = [str(v).strip() if v is not None else "" for v in row]
            if any(values):
                rows.append(" | ".join(values))
        if rows:
            sections.append(
                ParsedSection(
                    text="\n".join(rows), meta={"sheet": ws.title}, structured=True
                )
            )
    return sections


def _parse_md(path: Path) -> list[ParsedSection]:
    text = _read_text(path)
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return [ParsedSection(text=text, meta={"title": title})]


def _parse_txt(path: Path) -> list[ParsedSection]:
    text = _read_text(path)
    return [ParsedSection(text=text, meta={})]


def _read_text(path: Path) -> str:
    """文本文件读取：优先 UTF-8，失败回退 GBK（Windows 常见编码）。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("文件编码无法识别（既不是 UTF-8 也不是 GBK）")


def _extract_title(sections: list[ParsedSection], path: Path, file_type: str) -> str:
    """文档标题：md 取首个 # 标题；docx 取首个 heading；其他用文件名去扩展名。"""
    for s in sections:
        t = s.meta.get("title", "")
        if t:
            return t
    return path.stem


_PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "xlsx": _parse_xlsx,
    "md": _parse_md,
    "txt": _parse_txt,
}
