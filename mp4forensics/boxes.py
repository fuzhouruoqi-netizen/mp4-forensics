# -*- coding: utf-8 -*-
"""MP4 box 结构解析器。

设计要点：
* 只用文件头做递归，叶子节点按需读取，**不会把整个文件读进内存**；
* size 字段统一用 64 位处理（支持 size==1 的 largesize 和 4GB 以上文件），
  避免 32 位整型溢出——这正是 MP4 Inspector 0.1.2 在 4K 60fps 大文件上崩溃的原因；
* 对畸形/截断文件做容错，返回 partial 结果而不是抛异常。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator, Optional

U32 = struct.Struct(">I")
U64 = struct.Struct(">Q")
HEADER = struct.Struct(">I4s")

# 容器型 box：payload 里还是 box，需要继续递归
CONTAINERS = {
    "moov", "trak", "mdia", "minf", "stbl", "mvex", "moof", "traf", "mfra",
    "udta", "edts", "dinf", "ipro", "sinf", "schi", "meco", "hnti", "hinf",
    "strk", "stri", "tref", "gmhd", "wave", "ilst", "rinf", "emeb",
}

# FullBox 容器：payload 前 4 字节是 version+flags
FULLBOX_CONTAINERS = {"meta"}

MAX_DEPTH = 12


@dataclass
class Box:
    type: str
    offset: int                 # box 起始（含头部）
    size: int                   # 整个 box 的字节数
    header_size: int            # 8 / 16 / 24(uuid)
    payload_offset: int
    payload_size: int
    children: list["Box"] = field(default_factory=list)
    uuid: Optional[str] = None
    parent: Optional["Box"] = None
    malformed: Optional[str] = None

    @property
    def path(self) -> str:
        parts = []
        node: Optional[Box] = self
        while node:
            parts.append(node.type + (f"[{node.uuid[:8]}]" if node.uuid else ""))
            node = node.parent
        return "/".join(reversed(parts))

    @property
    def depth(self) -> int:
        d, node = 0, self.parent
        while node:
            d += 1
            node = node.parent
        return d

    def walk(self) -> Iterator["Box"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def find(self, path: str) -> Optional["Box"]:
        """按 'moov/trak/mdia/mdhd' 查找；同层多个 trak 时返回第一个匹配。"""
        node: Optional[Box] = self
        for part in [p for p in path.strip("/").split("/") if p]:
            if node is None:
                return None
            if node.type == part:
                continue
            nxt = None
            for c in node.children:
                if c.type == part:
                    nxt = c
                    break
            node = nxt
        return node

    def find_all(self, path: str) -> list["Box"]:
        """按路径查找所有匹配（例如所有 trak 下的 mdhd）。"""
        parts = [p for p in path.strip("/").split("/") if p]
        result: list[Box] = []

        def rec(node: Box, idx: int):
            if idx >= len(parts) or node.type == parts[idx]:
                idx += 1
                if idx == len(parts):
                    result.append(node)
                    return
            for c in node.children:
                rec(c, idx)

        rec(self, 0)
        return result

    def read_payload(self, f, limit: int = 4096) -> bytes:
        f.seek(self.payload_offset)
        return f.read(min(self.payload_size, limit))


class BoxParser:
    def __init__(self, fileobj, file_size: int):
        self.f = fileobj
        self.file_size = file_size

    def parse(self) -> Box:
        root = Box(type="<root>", offset=0, size=self.file_size, header_size=0,
                   payload_offset=0, payload_size=self.file_size)
        self._parse_children(root, 0, self.file_size)
        return root

    def _parse_children(self, parent: Box, start: int, end: int):
        pos = start
        guard = 0
        while pos + 8 <= end:
            guard += 1
            if guard > 100_000:           # 防御性上限
                break
            try:
                box = self._read_box(pos, end, parent)
            except (struct.error, ValueError):
                break
            if box is None:
                break
            parent.children.append(box)
            pos = box.offset + box.size
            if box.size <= 0:
                break

    def _read_box(self, pos: int, end: int, parent: Box) -> Optional[Box]:
        self.f.seek(pos)
        head = self.f.read(8)
        if len(head) < 8:
            return None
        size32, typ = HEADER.unpack(head)
        typ = typ.decode("latin-1")
        if not typ.isprintable() and not all(32 <= ord(c) < 127 for c in typ):
            # 非法类型，说明已经跑偏了
            return None

        header_size = 8
        size = size32
        if size32 == 1:                      # 64 位大 box
            large = self.f.read(8)
            if len(large) < 8:
                return None
            size = U64.unpack(large)[0]
            header_size = 16
        elif size32 == 0:                    # 一直到文件末尾
            size = end - pos

        uuid = None
        if typ == "uuid":
            raw = self.f.read(16)
            if len(raw) < 16:
                return None
            uuid = raw.hex()
            header_size += 16

        if size < header_size:
            return Box(type=typ, offset=pos, size=end - pos, header_size=header_size,
                       payload_offset=pos + header_size,
                       payload_size=max(0, end - pos - header_size),
                       uuid=uuid, parent=parent,
                       malformed="size 字段小于 box 头长度")
        if pos + size > end:
            size = end - pos                    # 截断文件：按可用长度处理

        box = Box(type=typ, offset=pos, size=size, header_size=header_size,
                  payload_offset=pos + header_size,
                  payload_size=size - header_size, uuid=uuid, parent=parent)

        if box.depth < MAX_DEPTH:
            if typ in CONTAINERS:
                self._parse_children(box, box.payload_offset, pos + size)
            elif typ in FULLBOX_CONTAINERS:
                self._parse_children(box, box.payload_offset + 4, pos + size)
            elif typ == "stsd":
                # FullBox(4) + entry_count(4)，之后是 sample entry（本身也是 box）
                self._parse_children(box, box.payload_offset + 8, pos + size)
            elif typ in ("avc1", "avc3", "hvc1", "hev1", "mp4v", "encv"):
                # 视觉 sample entry：78 字节固定字段后是子 box
                if box.payload_size > 78:
                    self._parse_children(box, box.payload_offset + 78, pos + size)
            elif typ in ("mp4a", "enca", "ac-3", "ec-3"):
                # 音频 sample entry：28 字节后是子 box（esds 等）
                if box.payload_size > 28:
                    self._parse_children(box, box.payload_offset + 28, pos + size)
        return box


def parse_file(path: str) -> tuple[Box, int]:
    import os

    size = os.path.getsize(path)
    with open(path, "rb") as f:
        root = BoxParser(f, size).parse()
    return root, size


def top_level(root: Box) -> list[Box]:
    return root.children
