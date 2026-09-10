"""日志配置：控制台 + 滚动文件。

Windows 下控制台/文件默认 GBK 编码，中文路径与中文日志会乱码，
因此文件 handler 显式指定 encoding="utf-8"，控制台由 PYTHONUTF8=1 兜底。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    log_dir = settings.resolve_path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 降低第三方库噪音
    for noisy in ("httpx", "httpcore", "chromadb", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
