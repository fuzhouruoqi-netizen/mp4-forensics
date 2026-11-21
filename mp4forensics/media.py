# -*- coding: utf-8 -*-
"""从 box 树里读出人可读的元数据（相当于 MediaInfo + ExifToolGui + MP4 Inspector 的解析结果）。"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .boxes import Box, parse_file

MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)

AAC_SAMPLE_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000,
                    22050, 16000, 12000, 11025, 8000, 7350]
AAC_OBJECT_TYPES = {
    1: "AAC Main", 2: "AAC LC", 3: "AAC SSR", 4: "AAC LTP",
    5: "HE-AAC (SBR)", 6: "AAC Scalable", 17: "ER AAC LC",
    23: "ER AAC LD", 29: "HE-AACv2 (PS)", 39: "ER AAC ELD",
}
ESDS_OBJECT_TYPES = {
    0x20: "MPEG-4 Visual", 0x21: "AVC", 0x23: "HEVC",
    0x40: "AAC", 0x66: "AAC (MPEG-2)", 0x67: "AAC (MPEG-2 LC)",
    0x69: "MPEG-1 Audio", 0x6B: "MP3", 0xA5: "AC-3", 0xA6: "E-AC-3",
    0xA9: "DTS", 0xDD: "Vorbis",
}
HANDLERS = {"vide": "视频", "soun": "音频", "hint": "提示", "meta": "元数据", "text": "字幕", "sbtl": "字幕"}


def _u8(b, i=0):
    return b[i] if i < len(b) else 0


def _u16(b, i=0):
    return struct.unpack_from(">H", b, i)[0] if i + 2 <= len(b) else 0


def _u32(b, i=0):
    return struct.unpack_from(">I", b, i)[0] if i + 4 <= len(b) else 0


def _u64(b, i=0):
    return struct.unpack_from(">Q", b, i)[0] if i + 8 <= len(b) else 0


def _s32(b, i=0):
    return struct.unpack_from(">i", b, i)[0] if i + 4 <= len(b) else 0


def mp4_time(v: int) -> Optional[datetime]:
    """MP4 时间戳是 1904-01-01 起的秒数（UTC）。"""
    if not v:
        return None
    try:
        return MP4_EPOCH + timedelta(seconds=int(v))
    except OverflowError:
        return None


def fmt_duration(seconds: float) -> str:
    if seconds is None:
        return "—"
    total_ms = int(round(seconds * 1000))
    s, ms = divmod(total_ms, 1000)
    if s >= 3600:
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h} 小时 {m} 分 {s} 秒 {ms} 毫秒"
    if s >= 60:
        m, s = divmod(s, 60)
        return f"{m} 分 {s} 秒 {ms} 毫秒"
    return f"{s} 秒 {ms} 毫秒"


def fmt_bitrate(bps: Optional[float]) -> str:
    """码率格式化：大于 1 Mb/s 用 Mb/s，否则用 kb/s（小文件不会显示成 0.00 Mb/s）。"""
    if not bps:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1e6:.2f} Mb/s"
    if bps >= 1000:
        return f"{bps / 1e3:.0f} kb/s"
    return f"{bps:.0f} b/s"


@dataclass
class Track:
    track_id: int = 0
    handler: str = ""
    kind: str = "未知"
    timescale: int = 0
    duration: int = 0
    duration_s: float = 0.0
    codec: str = ""
    codec_detail: str = ""
    width: int = 0
    height: int = 0
    rotation: float = 0.0
    sample_count: int = 0
    stts_entries: int = 0
    frame_rate: Optional[float] = None
    frame_rate_mode: str = ""
    bitrate: Optional[float] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    audio_object: str = ""
    language: str = ""
    media_bytes: int = 0
    sync_samples: list = field(default_factory=list)
    created: Optional[datetime] = None
    modified: Optional[datetime] = None

    @property
    def duration_text(self) -> str:
        return fmt_duration(self.duration_s)

    @property
    def codec_label(self) -> str:
        """避免出现「AAC AAC LC」这种重复。"""
        ao = (self.audio_object or "").strip()
        codec = (self.codec or "").strip()
        if ao and ao.lower().startswith(codec.lower()) and codec:
            label = ao
        elif ao and codec:
            label = f"{codec} {ao}"
        else:
            label = codec or ao
        detail = (self.codec_detail or "").strip()
        return f"{label} {detail}".strip()


@dataclass
class MediaInfo:
    path: str = ""
    file_size: int = 0
    root: Optional[Box] = None
    major_brand: str = ""
    minor_version: int = 0
    compatible_brands: list = field(default_factory=list)
    movie_timescale: int = 0
    movie_duration: int = 0
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    tracks: list = field(default_factory=list)
    container: str = "MP4"
    warnings: list = field(default_factory=list)

    # ---------- 便捷属性 ----------
    @property
    def duration_s(self) -> float:
        if self.movie_timescale:
            return self.movie_duration / self.movie_timescale
        if self.tracks:
            return max(t.duration_s for t in self.tracks)
        return 0.0

    @property
    def video(self) -> Optional[Track]:
        return next((t for t in self.tracks if t.handler == "vide"), None)

    @property
    def audio(self) -> Optional[Track]:
        return next((t for t in self.tracks if t.handler == "soun"), None)

    @property
    def overall_bitrate(self) -> float:
        d = self.duration_s
        return (self.file_size * 8 / d) if d else 0.0


# --------------------------------------------------------------------- 解析
def _payload(f, box: Box, limit: int = 65536) -> bytes:
    return box.read_payload(f, limit)


def parse_ftyp(info: MediaInfo, f, box: Box):
    b = _payload(f, box, 256)
    if len(b) >= 8:
        info.major_brand = b[0:4].decode("latin-1", "replace").strip()
        info.minor_version = _u32(b, 4)
        brands = []
        for i in range(8, len(b) - 3, 4):
            br = b[i:i + 4].decode("latin-1", "replace").strip()
            if br:
                brands.append(br)
        info.compatible_brands = brands


def parse_mvhd(info: MediaInfo, f, box: Box):
    b = _payload(f, box, 128)
    ver = _u8(b, 0)
    if ver == 1:
        info.created = mp4_time(_u64(b, 4))
        info.modified = mp4_time(_u64(b, 12))
        info.movie_timescale = _u32(b, 20)
        info.movie_duration = _u64(b, 24)
    else:
        info.created = mp4_time(_u32(b, 4))
        info.modified = mp4_time(_u32(b, 8))
        info.movie_timescale = _u32(b, 12)
        info.movie_duration = _u32(b, 16)


def parse_mdhd(track: Track, f, box: Box):
    b = _payload(f, box, 128)
    ver = _u8(b, 0)
    if ver == 1:
        track.created = mp4_time(_u64(b, 4))
        track.modified = mp4_time(_u64(b, 12))
        track.timescale = _u32(b, 20)
        track.duration = _u64(b, 24)
        lang = _u16(b, 32)
    else:
        track.created = mp4_time(_u32(b, 4))
        track.modified = mp4_time(_u32(b, 8))
        track.timescale = _u32(b, 12)
        track.duration = _u32(b, 16)
        lang = _u16(b, 20)
    if track.timescale:
        track.duration_s = track.duration / track.timescale
    if lang:
        # ISO 639-2/T：5 位一组 +0x60
        c1 = ((lang >> 10) & 0x1F) + 0x60
        c2 = ((lang >> 5) & 0x1F) + 0x60
        c3 = (lang & 0x1F) + 0x60
        s = "".join(chr(c) for c in (c1, c2, c3) if 0x61 <= c <= 0x7A)
        track.language = s or "und"


def parse_tkhd(track: Track, f, box: Box):
    b = _payload(f, box, 128)
    ver = _u8(b, 0)
    if ver == 1:
        track.track_id = _u32(b, 20)
        m = b[52:88]
        w = _u32(b, 88)
        h = _u32(b, 92)
    else:
        track.track_id = _u32(b, 12)
        m = b[40:76]
        w = _u32(b, 76)
        h = _u32(b, 80)
    track.width = w >> 16
    track.height = h >> 16
    if len(m) == 36:
        a = _s32(m, 0) / 65536.0
        bb = _s32(m, 4) / 65536.0
        if a or bb:
            deg = math.degrees(math.atan2(bb, a))
            # 归一化到 0/90/180/270
            track.rotation = round((deg + 360) % 360, 2)
            if abs(track.rotation - 360) < 0.5:
                track.rotation = 0.0


def parse_hdlr(track: Track, f, box: Box):
    b = _payload(f, box, 64)
    if len(b) >= 12:
        track.handler = b[8:12].decode("latin-1", "replace")
        track.kind = HANDLERS.get(track.handler, track.handler or "未知")


def parse_stts(track: Track, f, box: Box):
    b = _payload(f, box, 8 + 8 * 100000)
    count = _u32(b, 4)
    track.stts_entries = count
    total = 0
    for i in range(count):
        off = 8 + i * 8
        if off + 8 > len(b):
            break
        total += _u32(b, off)
    track.sample_count = track.sample_count or total
    if count == 1:
        track.frame_rate_mode = "恒定 (CFR)"
    elif count > 1:
        track.frame_rate_mode = "可变 (VFR)"


def parse_stsz(track: Track, f, box: Box):
    b = _payload(f, box, 12)
    sample_size = _u32(b, 4)
    count = _u32(b, 8)
    if sample_size:
        track.media_bytes = sample_size * count
        if not track.sample_count:
            track.sample_count = count
        return
    # 变长样本：分块读，避免大文件把内存打满
    remaining = count
    pos = box.payload_offset + 12
    total = 0
    while remaining > 0:
        chunk_n = min(remaining, 65536)
        f.seek(pos)
        data = f.read(chunk_n * 4)
        if len(data) < chunk_n * 4:
            break
        total += sum(struct.unpack(f">{chunk_n}I", data))
        pos += chunk_n * 4
        remaining -= chunk_n
    track.media_bytes = total
    if not track.sample_count:
        track.sample_count = count


def parse_stss(track: Track, f, box: Box):
    b = _payload(f, box, 8 + 4 * 200000)
    count = _u32(b, 4)
    nums = []
    for i in range(min(count, (len(b) - 8) // 4)):
        nums.append(_u32(b, 8 + i * 4))
    track.sync_samples = nums


def parse_avcc(track: Track, f, box: Box):
    b = _payload(f, box, 16)
    if len(b) >= 4:
        profile, compat, level = b[1], b[2], b[3]
        track.codec_detail = f"profile={profile} level={level / 10:.1f}"
        if profile == 66:
            track.codec_detail = f"Baseline@{level / 10:.1f}"
        elif profile == 77:
            track.codec_detail = f"Main@{level / 10:.1f}"
        elif profile == 100:
            track.codec_detail = f"High@{level / 10:.1f}"
        elif profile == 244:
            track.codec_detail = f"High 4:4:4@{level / 10:.1f}"


def _parse_descriptor(data: bytes, pos: int):
    """解析 MPEG-4 descriptor（tag + 变长长度），返回 (tag, body, next_pos)。"""
    if pos >= len(data):
        return None, b"", pos
    tag = data[pos]
    pos += 1
    size = 0
    for _ in range(4):
        if pos >= len(data):
            return tag, b"", pos
        c = data[pos]
        pos += 1
        size = (size << 7) | (c & 0x7F)
        if not (c & 0x80):
            break
    return tag, data[pos:pos + size], pos + size


def parse_esds(track: Track, f, box: Box):
    b = _payload(f, box, 512)
    if len(b) < 4:
        return
    data = b[4:]                      # 跳过 version+flags
    tag, body, _ = _parse_descriptor(data, 0)
    if tag != 0x03:
        return
    # ES_Descriptor: ES_ID(2) + flags(1) [+ 可选字段]
    flags = body[2] if len(body) > 2 else 0
    p = 3
    if flags & 0x80:
        p += 2
    if flags & 0x40:
        p += 1 + (body[p] if p < len(body) else 0)
    if flags & 0x20:
        p += 2
    tag2, body2, _ = _parse_descriptor(body, p)
    if tag2 != 0x04:
        return
    obj_type = body2[0] if body2 else 0
    if track.handler == "soun":
        track.codec = ESDS_OBJECT_TYPES.get(obj_type, f"0x{obj_type:02X}")
    elif obj_type in ESDS_OBJECT_TYPES:
        # 视频轨的 esds 用 objectTypeIndication 表示编码（如 0x20 = MPEG-4 Visual）
        track.codec = ESDS_OBJECT_TYPES[obj_type]
    if len(body2) >= 13:
        max_br = _u32(body2, 5)
        avg_br = _u32(body2, 9)
        if avg_br:
            track.bitrate = float(avg_br)
        elif max_br:
            track.bitrate = float(max_br)
    # DecoderSpecificInfo -> AudioSpecificConfig（仅音频轨有意义）
    if track.handler == "soun" and len(body2) > 13:
        tag3, asc, _ = _parse_descriptor(body2, 13)
        if tag3 == 0x05 and len(asc) >= 2:
            bits = "".join(f"{c:08b}" for c in asc[:4])
            aot = int(bits[0:5], 2)
            freq_idx = int(bits[5:9], 2)
            chan = int(bits[9:13], 2)
            track.audio_object = AAC_OBJECT_TYPES.get(aot, f"AAC (type {aot})")
            if freq_idx == 15:
                track.sample_rate = 0
            else:
                track.sample_rate = AAC_SAMPLE_RATES[freq_idx] if freq_idx < len(AAC_SAMPLE_RATES) else 0
            track.channels = chan


def parse_sample_entry(track: Track, f, box: Box):
    typ = box.type
    if typ in ("avc1", "avc3"):
        track.codec = "AVC"
    elif typ in ("hvc1", "hev1"):
        track.codec = "HEVC"
    elif typ in ("mp4v",):
        track.codec = "MPEG-4 Visual"
    elif typ in ("mp4a", "enca"):
        track.codec = track.codec or "AAC"
    else:
        track.codec = track.codec or typ.upper()

    payload = _payload(f, box, 128)
    if track.handler == "vide" and len(payload) >= 78:
        track.width = track.width or _u16(payload, 24)
        track.height = track.height or _u16(payload, 26)
    if track.handler == "soun" and len(payload) >= 28:
        track.channels = track.channels or _u16(payload, 16)
        sr = _u32(payload, 24) >> 16
        track.sample_rate = track.sample_rate or sr

    for child in box.children:
        if child.type == "avcC":
            parse_avcc(track, f, child)
        elif child.type == "esds":
            parse_esds(track, f, child)


# --------------------------------------------------------------------- 主入口
def analyze(path: str) -> MediaInfo:
    info = MediaInfo(path=path)
    root, size = parse_file(path)
    info.root = root
    info.file_size = size

    with open(path, "rb") as f:
        ftyp = next((b for b in root.children if b.type == "ftyp"), None)
        if not ftyp:
            info.warnings.append("缺少 ftyp box，可能不是标准 MP4/MOV 文件")
        else:
            parse_ftyp(info, f, ftyp)

        moov = next((b for b in root.children if b.type == "moov"), None)
        if not moov:
            info.warnings.append("缺少 moov box，文件可能损坏或仍在录制")
            return info

        mvhd = next((b for b in moov.children if b.type == "mvhd"), None)
        if mvhd:
            parse_mvhd(info, f, mvhd)

        for trak in [b for b in moov.children if b.type == "trak"]:
            t = Track()
            # 先 mdia/mdhd 拿 timescale
            mdia = next((b for b in trak.children if b.type == "mdia"), None)
            if not mdia:
                continue
            tkhd = next((b for b in trak.children if b.type == "tkhd"), None)
            if tkhd:
                parse_tkhd(t, f, tkhd)
            hdlr = next((b for b in mdia.children if b.type == "hdlr"), None)
            if hdlr:
                parse_hdlr(t, f, hdlr)
            mdhd = next((b for b in mdia.children if b.type == "mdhd"), None)
            if mdhd:
                parse_mdhd(t, f, mdhd)

            minf = next((b for b in mdia.children if b.type == "minf"), None)
            stbl = None
            if minf:
                stbl = next((b for b in minf.children if b.type == "stbl"), None)
            if stbl:
                for child in stbl.children:
                    if child.type == "stsd":
                        for entry in child.children:
                            parse_sample_entry(t, f, entry)
                    elif child.type == "stts":
                        parse_stts(t, f, child)
                    elif child.type == "stsz":
                        parse_stsz(t, f, child)
                    elif child.type == "stss":
                        parse_stss(t, f, child)

            # 派生值
            if t.sample_count and t.duration_s:
                t.frame_rate = t.sample_count / t.duration_s
                if not t.frame_rate_mode:
                    t.frame_rate_mode = "推算"
            if t.media_bytes and t.duration_s:
                t.bitrate = t.bitrate or (t.media_bytes * 8 / t.duration_s)
            info.tracks.append(t)

    brands = " ".join(info.compatible_brands)
    if "qt" in brands.split():
        info.container = "QuickTime (MOV)"
    elif info.major_brand in ("isom", "iso2", "iso4", "iso5", "iso6", "mp41", "mp42"):
        info.container = "MPEG-4"
    return info
