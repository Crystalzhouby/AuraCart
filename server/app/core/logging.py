"""
核心日志配置模块。

在应用启动时配置 structlog + 标准库 logging 双通道输出：
- 控制台：彩色人类可读格式（ConsoleRenderer）
- 文件：纯文本格式，写入 server/log/ 目录，按启动时间命名

通过 `setup_logging(level, log_dir)` 在 main.py 中调用一次。
支持 DEBUG / INFO / WARNING / ERROR 四个等级。
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import structlog


def _ensure_log_dir(log_dir: str) -> Path:
    """确保日志目录存在并返回其绝对路径。"""
    log_path = Path(log_dir)
    if not log_path.is_absolute():
        # 相对于 server/ 目录解析
        log_path = Path(__file__).resolve().parents[2] / log_dir
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def setup_logging(level: str = "INFO", log_dir: str = "log"):
    """配置 structlog + 标准库双通道日志。

    控制台输出使用 structlog ConsoleRenderer（彩色），
    文件输出使用纯文本格式，写入 ``log_dir/app_YYYYMMDD_HHMMSS.log``。

    参数：
        level: 日志级别名称 — "DEBUG" / "INFO" / "WARNING" / "ERROR"。
        log_dir: 日志文件输出目录。相对路径基于 server/ 解析。
    """
    level_value = getattr(logging, level.upper(), logging.INFO)

    # ---- 确保日志目录存在 ----
    log_path = _ensure_log_dir(log_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"app_{timestamp}.log"

    # ---- 文件 Handler：纯文本格式 ----
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(level_value)
    # 自定义 Formatter：去除结构化日志中嵌入的 ANSI 颜色码
    class _PlainFormatter(logging.Formatter):
        _ansi_re = re.compile(r"\x1b\[[0-9;]*m")

        def format(self, record):
            msg = super().format(record)
            return self._ansi_re.sub("", msg)

    file_handler.setFormatter(_PlainFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # ---- 控制台 Handler：structlog 接管渲染 ----
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level_value)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    # ---- 根 Logger 配置 ----
    root_logger = logging.getLogger()
    root_logger.setLevel(level_value)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # 抑制第三方库的 DEBUG 日志，避免终端刷屏
    for noisy in ("sse_starlette", "httpcore", "httpx", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ---- structlog 配置 ----
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 启动日志记录
    logger = structlog.get_logger()
    logger.info(f"log file created", path=str(log_file), level=level.upper())
