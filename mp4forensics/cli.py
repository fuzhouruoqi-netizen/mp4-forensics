# -*- coding: utf-8 -*-
"""命令行入口：mp4-forensics"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from datetime import datetime

from . import __version__
from .boxes import parse_file
from .compare import INCONSISTENT, ONLY_PRO, CONSISTENT, build, summary
from .media import analyze, fmt_bitrate, fmt_duration
from .report import CSS, hex_dump, render_html, to_json, to_xlsx, tree_html
from .system import collect, fmt_size

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


def h1(t):
    print("\n" + c(t, "1;36"))


def kv(k, v, width=16):
    print(f"  {c(k.ljust(width), '90')} {v}")


def bar():
    print(c("─" * 72, "90"))


def _ensure_parent(path: str):
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def cmd_info(args):
    path = args.file
    if not os.path.isfile(path):
        sys.exit(f"文件不存在：{path}")

    info = analyze(path)
    facts = collect(path, hashes=not args.no_hash)
    rows = build(info, facts)

    h1("文件")
    kv("路径", facts.path)
    kv("大小", f"{fmt_size(facts.size)} ({facts.size} 字节)")
    kv("创建时间", facts.created.strftime("%Y-%m-%d %H:%M:%S") if facts.created else "—")
    kv("修改时间", facts.modified.strftime("%Y-%m-%d %H:%M:%S") if facts.modified else "—")
    if facts.sha256:
        kv("SHA-256", facts.sha256)

    h1("容器")
    kv("格式", f"{info.container} ({info.major_brand})")
    kv("兼容品牌", " ".join(info.compatible_brands) or "—")
    kv("时长", f"{fmt_duration(info.duration_s)}  ({info.duration_s:.3f}s)")
    kv("总体码率", fmt_bitrate(info.overall_bitrate))
    kv("录制时间", info.created.strftime("%Y-%m-%d %H:%M:%S") if info.created else "—")
    kv("轨道数", len(info.tracks))

    for t in info.tracks:
        h1(f"{t.kind}轨 #{t.track_id}")
        kv("编码", t.codec_label)
        if t.width:
            kv("分辨率", f"{t.width}×{t.height}" + (f"  旋转 {t.rotation:.0f}°" if t.rotation else ""))
        if t.frame_rate:
            kv("帧率", f"{t.frame_rate:.3f} FPS（{t.frame_rate_mode}）")
        if t.sample_rate:
            kv("采样率", f"{t.sample_rate / 1000:.1f} kHz")
        if t.channels:
            kv("声道", f"{t.channels}")
        if t.audio_object:
            kv("音频对象", t.audio_object)
        bitrate = t.bitrate or 0
        kv("码率", fmt_bitrate(bitrate))
        kv("时长", f"{t.duration_text} (mdhd {t.duration}/{t.timescale})")
        kv("样本数", t.sample_count)
        if t.sync_samples:
            kv("关键帧", f"{len(t.sync_samples)} 个，前 10: {', '.join(map(str, t.sync_samples[:10]))}")

    h1("三口径对比")
    stat = summary(rows)
    print(f"  一致 {c(stat.get(CONSISTENT, 0), '32')} · 不一致 {c(stat.get(INCONSISTENT, 0), '31')}"
          f" · 仅专业工具 {c(stat.get(ONLY_PRO, 0), '34')}\n")
    print(f"  {'字段'.ljust(14)}{'系统属性'.ljust(26)}{'流层'.ljust(30)}结论")
    bar()
    for r in rows:
        tag = {"一致": c("一致", "32"), "不一致": c("不一致", "31"),
               "仅系统属性": c("仅系统属性", "33")}.get(r.status, c(r.status, "34"))
        print(f"  {r.field.ljust(14)}{r.system[:24].ljust(26)}{r.stream[:28].ljust(30)}{tag}")

    if info.warnings:
        print()
        for w in info.warnings:
            print("  " + c("⚠ " + w, "33"))

    made = []
    if args.html:
        hex_block = _hex_block(path, args.hex, args.hex_length) if args.hex else None
        _ensure_parent(args.html)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(render_html(info, facts, rows, hex_block, args.tree_depth))
        made.append(args.html)
    if args.json:
        import json as _json
        _ensure_parent(args.json)
        with open(args.json, "w", encoding="utf-8") as f:
            _json.dump(to_json(info, facts, rows), f, ensure_ascii=False, indent=2)
        made.append(args.json)
    if args.xlsx:
        _ensure_parent(args.xlsx)
        if to_xlsx(info, facts, rows, args.xlsx):
            made.append(args.xlsx)
        else:
            print(c("  ！未安装 openpyxl，跳过 Excel 导出", "33"))

    if made:
        print()
        for m in made:
            print("  " + c("已生成", "32") + " " + os.path.abspath(m))


def _hex_block(path, box_path, length):
    root = parse_file(path)[0]
    box = root.find(box_path)
    if not box:
        sys.exit(f"找不到 box：{box_path}")
    with open(path, "rb") as f:
        f.seek(box.payload_offset)
        data = f.read(min(box.payload_size, length))
    return {"path": box_path, "offset": box.payload_offset, "size": box.payload_size,
            "data": data, "shown": len(data)}


def cmd_tree(args):
    root, size = parse_file(args.file)

    def rec(box, prefix, last):
        if box.depth > args.depth:
            return
        branch = "└─ " if last else "├─ "
        print(f"{prefix}{branch}{c(box.type, '36')}  offset=0x{box.offset:X}  size={box.size}")
        nxt = prefix + ("   " if last else "│  ")
        kids = box.children
        for i, ch in enumerate(kids):
            rec(ch, nxt, i == len(kids) - 1)

    print(f"{c('<root>', '36')}  size={size}")
    kids = root.children
    for i, ch in enumerate(kids):
        rec(ch, "", i == len(kids) - 1)


def cmd_hex(args):
    block = _hex_block(args.file, args.box, args.length)
    print(f"{c(block['path'], '36')}  offset=0x{block['offset']:X}  size={block['size']}")
    data = block["data"]
    printable = set(range(32, 127))
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk).ljust(47)
        ascii_part = "".join(chr(b) if b in printable else "." for b in chunk)
        print(f"{block['offset'] + i:08x}  {hexpart}  {ascii_part}")


def cmd_hash(args):
    facts = collect(args.file, hashes=True)
    print(f"文件   {facts.path}")
    print(f"大小   {facts.size} 字节 ({fmt_size(facts.size)})")
    print(f"MD5    {facts.md5}")
    print(f"SHA1   {facts.sha1}")
    print(f"SHA256 {facts.sha256}")


def cmd_batch(args):
    files = []
    for pattern in args.targets:
        if os.path.isdir(pattern):
            files += sorted(glob.glob(os.path.join(pattern, "*.mp4")) + glob.glob(os.path.join(pattern, "*.mov")))
        else:
            files += sorted(glob.glob(pattern))
    if not files:
        sys.exit("没有找到视频文件")

    infos, factss = [], []
    for p in files:
        print("分析", os.path.basename(p), "…")
        infos.append(analyze(p))
        factss.append(collect(p, hashes=not args.no_hash))

    cols = [os.path.basename(i.path) for i in infos]
    fields = [
        ("容器", lambda i, f: f"{i.container}"),
        ("大小", lambda i, f: f"{fmt_size(f.size)}"),
        ("时长", lambda i, f: f"{i.duration_s:.3f}s"),
        ("分辨率", lambda i, f: f"{i.video.width}×{i.video.height}" if i.video else "—"),
        ("帧率", lambda i, f: f"{i.video.frame_rate:.3f}" if i.video and i.video.frame_rate else "—"),
        ("视频编码", lambda i, f: i.video.codec if i.video else "—"),
        ("视频码率", lambda i, f: f"{(i.video.bitrate or 0) / 1e6:.2f} Mb/s" if i.video else "—"),
        ("音频编码", lambda i, f: i.audio.codec if i.audio else "—"),
        ("采样率", lambda i, f: f"{i.audio.sample_rate / 1000:.1f} kHz" if i.audio and i.audio.sample_rate else "—"),
        ("时基/时长", lambda i, f: f"{i.movie_timescale}/{i.movie_duration}"),
    ]

    print()
    print("字段".ljust(12) + "".join(cn[:16].ljust(18) for cn in cols))
    bar()
    for name, fn in fields:
        print(name.ljust(12) + "".join(str(fn(i, f))[:16].ljust(18) for i, f in zip(infos, factss)))

    if args.html:
        parts = [f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>批量对比</title><style>{CSS}</style></head><body><div class="wrap">
<header><h1>批量对比 · {len(files)} 个文件</h1><div class="meta"><span>{datetime.now().strftime("%Y-%m-%d %H:%M")}</span></div></header>
<div class="card"><h2>横向对比</h2><table><thead><tr><th>字段</th>"""]
        parts.append("".join(f"<th>{cname}</th>" for cname in cols))
        parts.append("</tr></thead><tbody>")
        for name, fn in fields:
            parts.append(f"<tr><td class='k'>{name}</td>" + "".join(f"<td>{fn(i, f)}</td>" for i, f in zip(infos, factss)) + "</tr>")
        parts.append("</tbody></table></div>")
        for i, f in zip(infos, factss):
            rows = build(i, f)
            parts.append(f"<div class='card'><h2>{os.path.basename(i.path)}</h2><table><thead><tr><th>字段</th><th>系统</th><th>流层</th><th>底层</th><th>结论</th></tr></thead><tbody>")
            for r in rows:
                parts.append(f"<tr><td class='k'>{r.field}</td><td>{r.system}</td><td>{r.stream}</td><td class='mono'>{r.box}</td><td>{r.status}</td></tr>")
            parts.append("</tbody></table></div>")
        parts.append("</div></body></html>")
        _ensure_parent(args.html)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write("".join(parts))
        print("\n已生成 " + os.path.abspath(args.html))


def build_parser():
    p = argparse.ArgumentParser(
        prog="mp4-forensics",
        description="MP4 视听数据解析 / 取证工具（集 MediaInfo + ExifTool + MP4 Inspector 于一体）",
    )
    p.add_argument("-V", "--version", action="version", version=f"mp4-forensics {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("info", help="解析元数据（默认输出到终端）")
    q.add_argument("file")
    q.add_argument("--html", help="生成 HTML 报告")
    q.add_argument("--json", help="导出 JSON")
    q.add_argument("--xlsx", help="导出 Excel 对比表（需要 openpyxl）")
    q.add_argument("--hex", metavar="BOX", help="附带某个 box 的十六进制，如 moov/trak/mdia/mdhd")
    q.add_argument("--hex-length", type=int, default=256)
    q.add_argument("--tree-depth", type=int, default=6)
    q.add_argument("--no-hash", action="store_true", help="跳过哈希计算（大文件更快）")
    q.set_defaults(func=cmd_info)

    q = sub.add_parser("tree", help="打印 box 结构树")
    q.add_argument("file")
    q.add_argument("--depth", type=int, default=6)
    q.set_defaults(func=cmd_tree)

    q = sub.add_parser("hex", help="查看某个 box 的十六进制")
    q.add_argument("file")
    q.add_argument("--box", required=True, help="如 moov/trak/mdia/mdhd")
    q.add_argument("--length", type=int, default=256)
    q.set_defaults(func=cmd_hex)

    q = sub.add_parser("hash", help="计算文件哈希")
    q.add_argument("file")
    q.set_defaults(func=cmd_hash)

    q = sub.add_parser("batch", help="批量分析并横向对比")
    q.add_argument("targets", nargs="+", help="目录或通配符")
    q.add_argument("--html", help="生成 HTML 对比报告")
    q.add_argument("--xlsx", help="生成 Excel（暂未实现）")
    q.add_argument("--no-hash", action="store_true")
    q.set_defaults(func=cmd_batch)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
