"""哈希工具：文件去重（sha256）与记忆感知缓存 key。"""
import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """分块读取文件计算 sha256，大文件不占内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(_CHUNK):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
