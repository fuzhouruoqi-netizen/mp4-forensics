# -*- coding: utf-8 -*-
"""三口径对比：系统属性（Windows）/ 流层（MediaInfo）/ 底层（ExifTool + MP4 Inspector）。

实验报告里的核心结论就是「同一文件，不同工具显示的字段、单位、精度、缺失情况不同」，
这里把这三种解析口径放进同一张表，自动标注 一致 / 不一致 / 仅某层可见。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .media import MediaInfo, fmt_bitrate, fmt_duration
from .system import FileFacts, fmt_size

CONSISTENT = "一致"
INCONSISTENT = "不一致"
ONLY_PRO = "仅专业工具"
ONLY_SYS = "仅系统属性"


@dataclass
class Row:
    field: str
    system: str = "—"
    stream: str = "—"
    box: str = "—"
    status: str = ""
    note: str = ""

    @property
    def has_any(self) -> bool:
        return any(v not in ("—", "", None) for v in (self.system, self.stream, self.box))


_fmt_bitrate = fmt_bitrate


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def build(info: MediaInfo, facts: FileFacts) -> list:
    rows: list = []
    v = info.video
    a = info.audio
    dur = info.duration_s

    # 1 容器格式
    rows.append(Row(
        "容器格式",
        system=facts.ext.upper() or "—",
        stream=f"{info.container} ({info.major_brand})" if info.major_brand else info.container,
        box="ftyp: " + " ".join([info.major_brand] + info.compatible_brands),
        status=CONSISTENT,
        note="系统只看扩展名，专业工具看 ftyp 里的 brand",
    ))

    # 2 文件大小
    rows.append(Row(
        "文件大小",
        system=f"{fmt_size(facts.size)}（{facts.size} 字节）",
        stream=f"{fmt_size(info.file_size)}（{info.file_size} 字节）",
        box=f"实际字节数 {info.file_size}",
        status=CONSISTENT if facts.size == info.file_size else INCONSISTENT,
        note="三者必须完全一致，否则说明读的不是同一个文件",
    ))

    # 3 总时长
    sys_dur = f"{round(dur)} 秒" if dur else "—"
    rows.append(Row(
        "总时长",
        system=sys_dur,
        stream=fmt_duration(dur),
        box=f"mvhd timescale={info.movie_timescale}, duration={info.movie_duration} → {dur:.3f}s",
        status=INCONSISTENT if dur and abs(round(dur) - dur) > 0.05 else CONSISTENT,
        note="系统属性直接取整到秒，专业工具精确到毫秒；底层是整数时基换算",
    ))

    # 4 分辨率
    if v:
        wh = f"{v.width}×{v.height}"
        rows.append(Row(
            "分辨率",
            system=wh,
            stream=wh,
            box=f"tkhd width/height = {v.width}.0×{v.height}.0（16.16 定点）",
            status=CONSISTENT,
        ))
        # 5 帧率
        fps = v.frame_rate
        rows.append(Row(
            "帧率",
            system=f"{round(fps)} 帧/秒" if fps else "—",
            stream=f"{fps:.3f} FPS（{v.frame_rate_mode}）" if fps else "—",
            box=f"stts {v.stts_entries} 项, 样本数={v.sample_count}, mdhd {v.timescale}/{v.duration} → {fps:.3f}" if fps else "—",
            status=(INCONSISTENT if fps and abs(round(fps) - fps) > 0.5 else CONSISTENT) if fps else ONLY_PRO,
            note="ntsc 类 59.94 与 60 的差异就是从这里来的",
        ))
        # 6 视频编码
        rows.append(Row(
            "视频编码",
            system="—",
            stream=v.codec_label,
            box=f"stsd/{v.codec.lower()} + avcC {v.codec_detail}",
            status=ONLY_PRO,
        ))
        # 7 视频码率
        rows.append(Row(
            "视频码率",
            system="—",
            stream=_fmt_bitrate(v.bitrate),
            box=f"stsz 合计 {v.media_bytes} 字节 / {dur:.3f}s",
            status=ONLY_PRO if v.bitrate else ONLY_PRO,
        ))
        # 8 旋转
        if v.rotation:
            rows.append(Row(
                "旋转",
                system="—",
                stream=f"{v.rotation:.0f}°",
                box="tkhd matrix（16.16 定点矩阵）",
                status=ONLY_PRO,
            ))

    if a:
        # 9 音频编码
        rows.append(Row(
            "音频编码",
            system="—",
            stream=a.codec_label,
            box=f"stsd/{a.codec.lower()}/esds objectType",
            status=ONLY_PRO,
        ))
        # 10 采样率
        sr = a.sample_rate or 0
        rows.append(Row(
            "采样率",
            system=f"{sr / 1000:.0f} kHz" if sr else "—",
            stream=f"{sr / 1000:.1f} kHz" if sr else "—",
            box=f"sample entry 里 16.16 定点 = {sr}",
            status=CONSISTENT if sr else ONLY_PRO,
            note="系统属性显示 kHz 整数，专业工具保留一位小数",
        ))
        # 11 声道
        rows.append(Row(
            "声道数",
            system="—",
            stream=f"{a.channels} 声道" if a.channels else "—",
            box=f"AudioSpecificConfig channelConfig={a.channels}",
            status=ONLY_PRO,
        ))
        # 12 音频码率
        rows.append(Row(
            "音频码率",
            system="—",
            stream=_fmt_bitrate(a.bitrate),
            box="esds avgBitrate",
            status=ONLY_PRO,
        ))

    # 13 创建时间
    box_created = info.created.strftime("%Y-%m-%d %H:%M:%S") if info.created else "—"
    sys_created = facts.created.strftime("%Y-%m-%d %H:%M:%S") if facts.created else "—"
    if facts.created and info.created:
        diff = abs((facts.created - info.created.replace(tzinfo=None)).total_seconds())
        created_status = CONSISTENT if diff <= 60 else INCONSISTENT
    elif facts.created:
        created_status = ONLY_SYS
    elif info.created:
        created_status = ONLY_PRO
    else:
        created_status = CONSISTENT
    rows.append(Row(
        "创建时间",
        system=f"文件创建时间 {sys_created}",
        stream="—",
        box=f"mvhd creation_time {box_created}（1904 纪元）",
        status=created_status,
        note="文件系统时间会被复制/传输改写，容器内时间是录制当时写的，取证价值更高",
    ))

    # 14 修改时间
    box_mod = info.modified.strftime("%Y-%m-%d %H:%M:%S") if info.modified else "—"
    sys_mod = facts.modified.strftime("%Y-%m-%d %H:%M:%S") if facts.modified else "—"
    rows.append(Row(
        "修改时间",
        system=sys_mod,
        stream="—",
        box=f"mvhd modification_time {box_mod}",
        status=(CONSISTENT if (facts.modified and info.modified) else (ONLY_SYS if facts.modified else ONLY_PRO)),
    ))

    # 15 同步样本
    if v and v.sync_samples:
        preview = ", ".join(str(n) for n in v.sync_samples[:10])
        more = "…" if len(v.sync_samples) > 10 else ""
        rows.append(Row(
            "关键帧（同步样本）",
            system="—",
            stream="—",
            box=f"stss 共 {len(v.sync_samples)} 个：{preview}{more}",
            status=ONLY_PRO,
            note="只有底层工具能看到，用于判断剪辑点与关键帧间隔",
        ))

    return rows


def summary(rows: list) -> dict:
    stat = {CONSISTENT: 0, INCONSISTENT: 0, ONLY_PRO: 0, ONLY_SYS: 0}
    for r in rows:
        stat[r.status] = stat.get(r.status, 0) + 1
    return stat
