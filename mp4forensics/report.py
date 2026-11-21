# -*- coding: utf-8 -*-
"""输出：HTML 报告 / JSON / Excel 对比表。"""
from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Optional

from .boxes import Box
from .compare import INCONSISTENT, ONLY_PRO, CONSISTENT, Row, summary
from .media import MediaInfo, fmt_bitrate, fmt_duration
from .system import FileFacts, fmt_size

CSS = """
:root{--ink:#141b26;--muted:#6b7688;--line:#e4e9f2;--bg:#f5f7fb;--brand:#2f6feb;--ok:#0f9d58;--warn:#d93025;--amber:#b06b00}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:28px 20px 80px}
header{background:linear-gradient(135deg,#1b2a4a,#2f4f8f);color:#fff;border-radius:16px;padding:26px 28px;margin-bottom:20px}
header h1{margin:0 0 6px;font-size:22px;letter-spacing:.3px}
header .path{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;opacity:.85;word-break:break-all}
header .meta{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:14px;font-size:13px;opacity:.92}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:16px;box-shadow:0 1px 3px rgba(20,30,50,.05)}
.card h2{margin:0 0 14px;font-size:16px;display:flex;align-items:center;gap:8px}
.card h2 .tag{font-size:11.5px;font-weight:600;color:var(--brand);background:#eaf1ff;border-radius:999px;padding:2px 9px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eef1f7;vertical-align:top}
th{background:#fafbfe;color:var(--muted);font-weight:600;font-size:12.5px;white-space:nowrap}
td.k{color:#33405a;font-weight:600;white-space:nowrap;width:130px}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.pos{background:#e9f7ef;color:var(--ok);font-weight:600;border-radius:6px;padding:1px 8px;font-size:12px;display:inline-block}
.neg{background:#fdecea;color:var(--warn);font-weight:600;border-radius:6px;padding:1px 8px;font-size:12px;display:inline-block}
.pro{background:#eef2fb;color:#3b5aa8;font-weight:600;border-radius:6px;padding:1px 8px;font-size:12px;display:inline-block}
.note{color:var(--muted);font-size:12.5px;margin-top:4px}
.warn{background:#fff8e6;border:1px solid #f3e2b3;color:#7a5400;border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:13px}
.tree{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.75;overflow-x:auto;white-space:pre}
.tree .box{color:#1b2a4a}.tree .off{color:#98a2b3}.tree .sz{color:#6b7688}
.hex{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:#0f172a;color:#cbd5e1;border-radius:10px;padding:14px 16px;overflow-x:auto;line-height:1.7}
.hex .a{color:#64748b;margin-right:10px}.hex .t{color:#7dd3fc}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.kv{background:#fafbfe;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kv .k{color:var(--muted);font-size:12px}.kv .v{font-size:13.5px;font-weight:600;margin-top:2px;word-break:break-all}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:26px}
"""

STATUS_CLASS = {CONSISTENT: "pos", INCONSISTENT: "neg", ONLY_PRO: "pro"}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def tree_html(root: Box, max_depth: int = 6, max_nodes: int = 400) -> str:
    lines = []
    count = 0

    def rec(box: Box, prefix: str, last: bool):
        nonlocal count
        if box.depth > max_depth or count >= max_nodes:
            return
        count += 1
        branch = "└─ " if last else "├─ "
        kids = [c for c in box.children]
        label = box.type + (f"[{box.uuid[:8]}]" if box.uuid else "")
        lines.append(
            f'<span class="off">{prefix}{branch}</span>'
            f'<span class="box">{_e(label)}</span> '
            f'<span class="off">offset=0x{box.offset:X}</span> '
            f'<span class="sz">size={box.size}</span>'
        )
        nxt = prefix + ("   " if last else "│  ")
        for i, c in enumerate(kids):
            rec(c, nxt, i == len(kids) - 1)

    lines.append(f'<span class="box">&lt;root&gt;</span> <span class="sz">size={root.size}</span>')
    kids = [c for c in root.children]
    for i, c in enumerate(kids):
        rec(c, "", i == len(kids) - 1)
    if count >= max_nodes:
        lines.append('<span class="off">…（节点过多，已截断）</span>')
    return "\n".join(lines)


def hex_dump(data: bytes, base: int = 0, width: int = 16, max_bytes: int = 512) -> str:
    out = []
    data = data[:max_bytes]
    printable = set(range(32, 127))
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart = hexpart.ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if b in printable else "." for b in chunk)
        out.append(f'<span class="a">{base + i:08x}</span>{hexpart}  <span class="t">{_e(ascii_part)}</span>')
    return "\n".join(out)


def render_html(info: MediaInfo, facts: FileFacts, rows: list, hex_block: Optional[dict] = None,
                tree_depth: int = 6) -> str:
    v, a = info.video, info.audio
    stat = summary(rows)

    warn = ""
    if info.warnings:
        warn = "".join(f'<div class="warn">⚠ {_e(w)}</div>' for w in info.warnings)

    # 证据固定
    facts_grid = f"""
    <div class="grid">
      <div class="kv"><div class="k">文件大小</div><div class="v">{_e(fmt_size(facts.size))} <span class="mono">({facts.size} 字节)</span></div></div>
      <div class="kv"><div class="k">SHA-256</div><div class="v mono">{_e(facts.sha256 or "—")}</div></div>
      <div class="kv"><div class="k">创建时间（文件系统）</div><div class="v">{_e(facts.created.strftime("%Y-%m-%d %H:%M:%S") if facts.created else "—")}</div></div>
      <div class="kv"><div class="k">修改时间</div><div class="v">{_e(facts.modified.strftime("%Y-%m-%d %H:%M:%S") if facts.modified else "—")}</div></div>
    </div>
    <div class="note">MD5 {_e(facts.md5 or "—")} · SHA-1 {_e(facts.sha1 or "—")} · {_e(facts.platform_note)}</div>
    """

    # 概览
    overview = f"""
    <table>
      <tr><td class="k">容器格式</td><td>{_e(info.container)} <span class="mono">({_e(info.major_brand)})</span></td>
          <td class="k">总体码率</td><td>{_e(fmt_bitrate(info.overall_bitrate))}</td></tr>
      <tr><td class="k">时长</td><td>{_e(fmt_duration(info.duration_s))}</td>
          <td class="k">轨道数</td><td>{len(info.tracks)}</td></tr>
      <tr><td class="k">录制时间（容器）</td><td>{_e(info.created.strftime("%Y-%m-%d %H:%M:%S") if info.created else "—")}</td>
          <td class="k">兼容品牌</td><td class="mono">{_e(" ".join(info.compatible_brands) or "—")}</td></tr>
    </table>
    """

    # 视频轨
    video_html = ""
    if v:
        video_html = f"""
        <table>
          <tr><td class="k">编码</td><td>{_e(v.codec_label)}</td><td class="k">码率</td><td>{(v.bitrate or 0) / 1e6:.2f} Mb/s</td></tr>
          <tr><td class="k">分辨率</td><td>{v.width}×{v.height}</td><td class="k">帧率</td><td>{f"{v.frame_rate:.3f} FPS（{v.frame_rate_mode}）" if v.frame_rate else "—"}</td></tr>
          <tr><td class="k">时长</td><td>{_e(v.duration_text)}</td><td class="k">时基 / 时长单位</td><td class="mono">{v.timescale} / {v.duration}</td></tr>
          <tr><td class="k">样本数</td><td>{v.sample_count}</td><td class="k">旋转</td><td>{v.rotation:.0f}°</td></tr>
          <tr><td class="k">语言</td><td>{_e(v.language or "und")}</td><td class="k">关键帧数</td><td>{len(v.sync_samples)}</td></tr>
        </table>"""

    audio_html = ""
    if a:
        audio_html = f"""
        <table>
          <tr><td class="k">编码</td><td>{_e(a.codec_label)}</td><td class="k">码率</td><td>{(a.bitrate or 0) / 1e3:.0f} kb/s</td></tr>
          <tr><td class="k">采样率</td><td>{(a.sample_rate or 0) / 1000:.1f} kHz</td><td class="k">声道数</td><td>{a.channels or "—"}</td></tr>
          <tr><td class="k">时长</td><td>{_e(a.duration_text)}</td><td class="k">时基 / 时长单位</td><td class="mono">{a.timescale} / {a.duration}</td></tr>
        </table>"""

    # 对比表
    rows_html = "".join(
        f"""<tr>
          <td class="k">{_e(r.field)}</td>
          <td>{_e(r.system)}</td>
          <td>{_e(r.stream)}</td>
          <td class="mono">{_e(r.box)}</td>
          <td><span class="{STATUS_CLASS.get(r.status, "pro")}">{_e(r.status or "—")}</span>
          {f'<div class="note">{_e(r.note)}</div>' if r.note else ''}</td>
        </tr>""" for r in rows
    )

    keys_html = ""
    if v and v.sync_samples:
        keys = v.sync_samples
        keys_html = (f'<div class="note">共 {len(keys)} 个同步样本，前 40 个：</div>'
                     f'<div class="mono" style="margin-top:6px">{_e(", ".join(map(str, keys[:40])))}</div>')

    hex_html = ""
    if hex_block:
        hex_html = f"""<div class="card"><h2>十六进制 <span class="tag">{_e(hex_block["path"])}</span></h2>
        <div class="note">offset=0x{hex_block["offset"]:X}，共 {hex_block["size"]} 字节，显示前 {hex_block["shown"]} 字节</div>
        <div class="hex">{hex_dump(hex_block["data"], hex_block["offset"])}</div></div>"""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(facts.name)} · MP4 取证报告</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>{_e(facts.name)}</h1>
  <div class="path">{_e(facts.path)}</div>
  <div class="meta">
    <span>{_e(info.container)} {_e(info.major_brand)}</span>
    <span>{_e(fmt_duration(info.duration_s))}</span>
    <span>{_e(fmt_size(facts.size))}</span>
    <span>{f"{v.width}×{v.height}" if v else "—"}</span>
    <span>{f"{v.frame_rate:.3f} FPS" if v and v.frame_rate else "—"}</span>
  </div>
</header>
{warn}
<div class="card"><h2>证据固定 <span class="tag">哈希 · 时间戳</span></h2>{facts_grid}</div>
<div class="card"><h2>容器概览 <span class="tag">MediaInfo 口径</span></h2>{overview}</div>
{f'<div class="card"><h2>视频轨 <span class="tag">MediaInfo 口径</span></h2>{video_html}</div>' if video_html else ''}
{f'<div class="card"><h2>音频轨 <span class="tag">MediaInfo 口径</span></h2>{audio_html}</div>' if audio_html else ''}
<div class="card"><h2>三口径对比 <span class="tag">系统属性 / 流层 / 底层</span></h2>
  <div class="note" style="margin-bottom:10px">一致 {stat.get(CONSISTENT,0)} 项 · 不一致 {stat.get(INCONSISTENT,0)} 项 · 仅专业工具可见 {stat.get(ONLY_PRO,0)} 项</div>
  <table><thead><tr><th>字段</th><th>系统属性（Windows）</th><th>流层（MediaInfo）</th><th>底层（ExifTool / MP4 Inspector）</th><th>结论</th></tr></thead>
  <tbody>{rows_html}</tbody></table>
</div>
{f'<div class="card"><h2>关键帧（stss） <span class="tag">仅底层可见</span></h2>{keys_html}</div>' if keys_html else ''}
{hex_html}
<div class="card"><h2>Box 结构 <span class="tag">MP4 Inspector 口径</span></h2><div class="tree">{tree_html(info.root, tree_depth)}</div></div>
<footer>由 mp4-forensics 生成 · {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</footer>
</div></body></html>"""


def to_json(info: MediaInfo, facts: FileFacts, rows: list) -> dict:
    return {
        "file": {
            "path": facts.path, "name": facts.name, "size": facts.size,
            "created": str(facts.created), "modified": str(facts.modified),
            "md5": facts.md5, "sha1": facts.sha1, "sha256": facts.sha256,
        },
        "container": {
            "format": info.container, "major_brand": info.major_brand,
            "compatible_brands": info.compatible_brands,
            "duration_s": round(info.duration_s, 6),
            "overall_bitrate": round(info.overall_bitrate, 2),
            "created": str(info.created), "modified": str(info.modified),
        },
        "tracks": [
            {
                "track_id": t.track_id, "kind": t.kind, "handler": t.handler,
                "codec": t.codec, "codec_detail": t.codec_detail,
                "width": t.width, "height": t.height, "rotation": t.rotation,
                "timescale": t.timescale, "duration_units": t.duration,
                "duration_s": round(t.duration_s, 6),
                "frame_rate": round(t.frame_rate, 6) if t.frame_rate else None,
                "frame_rate_mode": t.frame_rate_mode,
                "sample_count": t.sample_count, "stts_entries": t.stts_entries,
                "bitrate": round(t.bitrate, 2) if t.bitrate else None,
                "channels": t.channels, "sample_rate": t.sample_rate,
                "audio_object": t.audio_object, "language": t.language,
                "sync_samples": t.sync_samples[:200],
                "created": str(t.created), "modified": str(t.modified),
            } for t in info.tracks
        ],
        "compare": [
            {"field": r.field, "system": r.system, "stream": r.stream,
             "box": r.box, "status": r.status, "note": r.note} for r in rows
        ],
        "box_tree": [{"type": b.type, "offset": b.offset, "size": b.size} for b in info.root.walk()][:2000],
    }


def to_xlsx(info: MediaInfo, facts: FileFacts, rows: list, path: str) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return False

    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2F4F8F")
    wrap = Alignment(wrap_text=True, vertical="top")

    def head(ws, cols):
        ws.append(cols)
        for c in ws[1]:
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")

    ws = wb.active
    ws.title = "概览"
    head(ws, ["项目", "值"])
    for k, val in [
        ("文件", facts.name), ("路径", facts.path), ("大小", f"{fmt_size(facts.size)} ({facts.size} B)"),
        ("容器", f"{info.container} ({info.major_brand})"), ("时长", fmt_duration(info.duration_s)),
        ("总体码率", f"{_e(fmt_bitrate(info.overall_bitrate))}"), ("录制时间", str(info.created)),
        ("SHA-256", facts.sha256),
    ]:
        ws.append([k, val])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 70

    ws2 = wb.create_sheet("三口径对比")
    head(ws2, ["字段", "系统属性（Windows）", "流层（MediaInfo）", "底层（ExifTool / MP4 Inspector）", "结论", "说明"])
    for r in rows:
        ws2.append([r.field, r.system, r.stream, r.box, r.status, r.note])
        for c in ws2[ws2.max_row]:
            c.alignment = wrap
    for col, w in zip("ABCDEF", (18, 30, 34, 46, 14, 40)):
        ws2.column_dimensions[col].width = w

    ws3 = wb.create_sheet("轨道")
    head(ws3, ["类型", "编码", "分辨率", "帧率", "采样率", "声道", "码率", "时长", "时基", "时长单位", "旋转", "关键帧数"])
    for t in info.tracks:
        ws3.append([
            t.kind, f"{t.codec} {t.codec_detail}".strip(),
            f"{t.width}×{t.height}" if t.width else "—",
            f"{t.frame_rate:.3f}" if t.frame_rate else "—",
            f"{t.sample_rate}" if t.sample_rate else "—",
            t.channels or "—",
            f"{(t.bitrate or 0) / 1e6:.2f} Mb/s",
            t.duration_text, t.timescale, t.duration, f"{t.rotation:.0f}°", len(t.sync_samples),
        ])

    ws4 = wb.create_sheet("Box树")
    head(ws4, ["层级", "Box", "offset(hex)", "size"])
    for b in info.root.walk():
        ws4.append([b.depth, b.type, f"0x{b.offset:X}", b.size])

    wb.save(path)
    return True
