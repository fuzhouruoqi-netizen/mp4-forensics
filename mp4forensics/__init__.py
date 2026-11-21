# -*- coding: utf-8 -*-
"""mp4-forensics —— MP4 视听数据解析与取证。

一个工具覆盖实验里的四类软件：
  * MediaInfo      → 容器/流参数（编码、码率、帧率、采样率、声道…）
  * ExifToolGui    → 文件系统与容器底层时间戳（File:* / CreateDate / TimeScale…）
  * MP4 Inspector  → box 结构树、mdhd/stss 原始值、十六进制
  * Windows 属性   → 最表面的那几项，用于对照差异
"""

__version__ = "1.0.0"

from .media import analyze, MediaInfo, Track, fmt_duration  # noqa: F401
from .boxes import parse_file, Box  # noqa: F401
from .system import collect, FileFacts  # noqa: F401
from .compare import build, Row  # noqa: F401

__all__ = [
    "analyze", "MediaInfo", "Track", "fmt_duration",
    "parse_file", "Box", "collect", "FileFacts", "build", "Row",
    "__version__",
]
