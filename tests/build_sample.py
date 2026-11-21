# -*- coding: utf-8 -*-
"""构造一个最小但结构完整的 MP4（H.264 + AAC），用于测试解析器。"""
from __future__ import annotations

import struct

IDENTITY = struct.pack(">9i", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)


def box(typ: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ.encode("latin-1") + payload


def large_box(typ: str, payload: bytes = b"") -> bytes:
    """64 位 size 的 box（size==1 + largesize），用来验证溢出安全。"""
    return struct.pack(">I", 1) + typ.encode("latin-1") + struct.pack(">Q", 16 + len(payload)) + payload


def full(typ: str, version: int, flags: int, payload: bytes) -> bytes:
    return box(typ, struct.pack(">B", version) + struct.pack(">I", flags)[1:] + payload)


def desc(tag: int, body: bytes) -> bytes:
    n = len(body)
    return bytes([tag, n & 0x7F]) + body


def mvhd(timescale=1000, duration=10000) -> bytes:
    payload = (
        struct.pack(">I", 0)          # creation
        + struct.pack(">I", 0)        # modification
        + struct.pack(">I", timescale)
        + struct.pack(">I", duration)
        + struct.pack(">I", 0x00010000)   # rate 1.0
        + struct.pack(">H", 0x0100)       # volume 1.0
        + b"\x00" * 10
        + IDENTITY
        + b"\x00" * 24
        + struct.pack(">I", 3)            # next track id
    )
    return full("mvhd", 0, 0, payload)


def tkhd(track_id, duration, width=0, height=0, volume=0) -> bytes:
    payload = (
        struct.pack(">I", 0) + struct.pack(">I", 0)
        + struct.pack(">I", track_id) + struct.pack(">I", 0)
        + struct.pack(">I", duration)
        + b"\x00" * 8
        + struct.pack(">h", 0) + struct.pack(">h", 0)
        + struct.pack(">H", volume) + struct.pack(">H", 0)
        + IDENTITY
        + struct.pack(">I", width << 16) + struct.pack(">I", height << 16)
    )
    return full("tkhd", 0, 3, payload)


def mdhd(timescale, duration, language=0x55C4) -> bytes:
    payload = (
        struct.pack(">I", 0) + struct.pack(">I", 0)
        + struct.pack(">I", timescale) + struct.pack(">I", duration)
        + struct.pack(">H", language) + struct.pack(">H", 0)
    )
    return full("mdhd", 0, 0, payload)


def hdlr(handler: str) -> bytes:
    return full("hdlr", 0, 0, struct.pack(">I", 0) + handler.encode() + b"\x00" * 12 + b"name\x00")


def dinf() -> bytes:
    url = full("url ", 0, 1, b"")
    dref = full("dref", 0, 0, struct.pack(">I", 1) + url)
    return box("dinf", dref)


def stts(entries) -> bytes:
    body = struct.pack(">I", len(entries))
    for count, delta in entries:
        body += struct.pack(">II", count, delta)
    return full("stts", 0, 0, body)


def stsz(sizes) -> bytes:
    body = struct.pack(">I", 0) + struct.pack(">I", len(sizes))
    for s in sizes:
        body += struct.pack(">I", s)
    return full("stsz", 0, 0, body)


def stss(numbers) -> bytes:
    body = struct.pack(">I", len(numbers)) + b"".join(struct.pack(">I", n) for n in numbers)
    return full("stss", 0, 0, body)


def stsc() -> bytes:
    return full("stsc", 0, 0, struct.pack(">I", 1) + struct.pack(">III", 1, 1, 1))


def stco(offset=0) -> bytes:
    return full("stco", 0, 0, struct.pack(">I", 1) + struct.pack(">I", offset))


def avcc(profile=100, level=31) -> bytes:
    return box("avcC", bytes([1, profile, 0x00, level, 0xFF, 0xE1, 0x00, 0x04, 0x67, 0x64, 0x00, 0x1F]))


def video_sample_entry(width=1920, height=1080) -> bytes:
    fixed = (
        b"\x00" * 6
        + struct.pack(">H", 1)
        + b"\x00" * 16
        + struct.pack(">H", width) + struct.pack(">H", height)
        + struct.pack(">I", 0x00480000) + struct.pack(">I", 0x00480000)
        + b"\x00" * 4
        + struct.pack(">H", 1)
        + b"\x00" * 32
        + struct.pack(">H", 0x0018) + struct.pack(">h", -1)
    )
    assert len(fixed) == 78
    return box("avc1", fixed + avcc())


def esds() -> bytes:
    asc = bytes([0x11, 0x90])              # AAC LC / 48000 / 2ch
    dsi = desc(0x05, asc)
    dcd = desc(0x04, bytes([0x40, 0x15]) + b"\x00\x00\x00"
               + struct.pack(">I", 192000) + struct.pack(">I", 192000) + dsi)
    esd = desc(0x03, struct.pack(">H", 7) + b"\x00" + dcd)
    return full("esds", 0, 0, esd)


def audio_sample_entry(channels=2, rate=48000) -> bytes:
    fixed = (
        b"\x00" * 6
        + struct.pack(">H", 1)
        + b"\x00" * 8
        + struct.pack(">H", channels)
        + struct.pack(">H", 16)
        + struct.pack(">H", 0)
        + struct.pack(">H", 0)
        + struct.pack(">I", rate << 16)
    )
    assert len(fixed) == 28
    return box("mp4a", fixed + esds())


def build_video_track(sample_count=300, delta=512, timescale=15360) -> bytes:
    stbl = box("stbl",
               full("stsd", 0, 0, struct.pack(">I", 1) + video_sample_entry())
               + stts([(sample_count, delta)])
               + stss([1, 61, 121])
               + stsc() + stsz([1500] * sample_count) + stco(0x28))
    minf = box("minf", full("vmhd", 0, 1, b"\x00" * 8) + dinf() + stbl)
    mdia = box("mdia", mdhd(timescale, sample_count * delta) + hdlr("vide") + minf)
    return box("trak", tkhd(1, 10000, 1920, 1080) + mdia)


def build_audio_track(sample_count=470, delta=1024, timescale=48000) -> bytes:
    stbl = box("stbl",
               full("stsd", 0, 0, struct.pack(">I", 1) + audio_sample_entry())
               + stts([(sample_count, delta)])
               + stsc() + stsz([400] * sample_count) + stco(0x1000))
    minf = box("minf", full("smhd", 0, 0, b"\x00" * 4) + dinf() + stbl)
    mdia = box("mdia", mdhd(timescale, sample_count * delta) + hdlr("soun") + minf)
    return box("trak", tkhd(2, 10000, volume=0x0100) + mdia)


def build(path: str) -> str:
    ftyp = box("ftyp", b"isom" + struct.pack(">I", 512) + b"isom" + b"iso2" + b"avc1" + b"mp41")
    mdat = box("mdat", b"\x00" * 1024)
    moov = box("moov", mvhd() + build_video_track() + build_audio_track())
    data = ftyp + mdat + moov
    with open(path, "wb") as f:
        f.write(data)
    return path


if __name__ == "__main__":
    print(build("sample_avc_aac.mp4"))
