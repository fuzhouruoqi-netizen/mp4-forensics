# -*- coding: utf-8 -*-
"""文件系统层面的信息：时间戳、哈希、大小（对应 ExifTool 的 File:* 标签和 Windows 属性）。"""
from __future__ import annotations

import hashlib
import os
import platform
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class FileFacts:
    path: str = ""
    name: str = ""
    ext: str = ""
    size: int = 0
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    accessed: Optional[datetime] = None
    md5: str = ""
    sha1: str = ""
    sha256: str = ""
    platform_note: str = ""


def _dt(ts: float) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        return None


def collect(path: str, hashes: bool = True) -> FileFacts:
    st = os.stat(path)
    f = FileFacts(
        path=os.path.abspath(path),
        name=os.path.basename(path),
        ext=os.path.splitext(path)[1].lstrip(".").lower(),
        size=st.st_size,
    )
    system = platform.system()
    f.modified = _dt(st.st_mtime)
    f.accessed = _dt(st.st_atime)
    if system == "Windows":
        # Windows 上 st_ctime 是「创建时间」
        f.created = _dt(st.st_ctime)
        f.platform_note = "Windows：创建时间取自 st_ctime"
    else:
        birth = getattr(st, "st_birthtime", None)
        f.created = _dt(birth) if birth else None
        f.platform_note = "非 Windows：创建时间取自 st_birthtime（可能不可用）"

    if hashes:
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        sha256 = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(4 * 1024 * 1024):
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
        f.md5, f.sha1, f.sha256 = md5.hexdigest(), sha1.hexdigest(), sha256.hexdigest()
    return f


def fmt_size(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"
