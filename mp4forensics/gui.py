# -*- coding: utf-8 -*-
"""图形界面：把视频拖进来，出报告。打包成 exe 后零依赖。"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:                                   # 没有拖拽库也能用（点按钮选择）
    HAS_DND = False
    DND_FILES = None
    TkinterDnD = None

from mp4forensics import analyze, collect
from mp4forensics.compare import build as build_rows
from mp4forensics.media import fmt_bitrate, fmt_duration
from mp4forensics.report import render_html, to_xlsx
from mp4forensics.system import fmt_size

APP_TITLE = "MP4 视听数据解析 · 取证工具"
ACCENT = "#2f6feb"
BG = "#f5f7fb"
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".3gp")


class App:
    def __init__(self, root):
        self.root = root
        self.files: list[str] = []
        self.reports: list[str] = []
        self.queue = queue.Queue()
        self.running = False

        root.title(APP_TITLE)
        root.geometry("760x620")
        root.minsize(680, 540)
        root.configure(bg=BG)

        style = ttk.Style()
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Sub.TLabel", foreground="#6b7688", font=("Microsoft YaHei UI", 9))
        style.configure("TCheckbutton", background=BG, font=("Microsoft YaHei UI", 10))

        self._build_ui()
        self._poll()
        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 18}

        head = ttk.Frame(self.root)
        head.pack(fill="x", pady=(16, 6), **pad)
        ttk.Label(head, text="MP4 视听数据解析", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            head,
            text="集 MediaInfo / ExifTool / MP4 Inspector 于一体 · 输出三口径对比报告",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # 拖放区
        self.drop = tk.Frame(self.root, bg="#ffffff", highlightthickness=2,
                             highlightbackground="#c8d4ea", highlightcolor=ACCENT, bd=0)
        self.drop.pack(fill="x", pady=10, **pad)
        inner = tk.Frame(self.drop, bg="#ffffff")
        inner.pack(pady=18)
        tk.Label(inner, text="把视频拖到这里", bg="#ffffff", fg="#1b2330",
                 font=("Microsoft YaHei UI", 12, "bold")).pack()
        tk.Label(inner, text="或点击下面按钮选择（支持 MP4 / MOV，可多选）",
                 bg="#ffffff", fg="#6b7688", font=("Microsoft YaHei UI", 9)).pack(pady=(4, 10))
        ttk.Button(inner, text="选择视频文件", command=self._pick_files).pack()
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)
            inner.drop_target_register(DND_FILES)
            inner.dnd_bind("<<Drop>>", self._on_drop)

        # 文件列表
        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=False, **pad)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="待解析文件").pack(anchor="w")
        self.listbox = tk.Listbox(left, height=5, font=("Microsoft YaHei UI", 9),
                                  activestyle="none", selectmode="extended",
                                  bg="#ffffff", highlightthickness=1,
                                  highlightbackground="#e3e8f0", bd=0)
        self.listbox.pack(fill="both", expand=True, pady=(4, 6))

        btns = ttk.Frame(left)
        btns.pack(fill="x")
        ttk.Button(btns, text="移除选中", command=self._remove_selected).pack(side="left")
        ttk.Button(btns, text="清空", command=self._clear).pack(side="left", padx=6)

        # 选项 + 开始
        opts = ttk.Frame(self.root)
        opts.pack(fill="x", pady=(12, 0), **pad)
        self.var_html = tk.BooleanVar(value=True)
        self.var_xlsx = tk.BooleanVar(value=False)
        self.var_hash = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="生成 HTML 报告", variable=self.var_html).pack(side="left")
        ttk.Checkbutton(opts, text="导出 Excel", variable=self.var_xlsx).pack(side="left", padx=12)
        ttk.Checkbutton(opts, text="计算哈希", variable=self.var_hash).pack(side="left")

        self.start_btn = tk.Button(
            opts, text="开始解析", command=self._start,
            bg=ACCENT, fg="white", activebackground="#1f56c4", activeforeground="white",
            relief="flat", bd=0, padx=22, pady=7, cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.start_btn.pack(side="right")

        # 底部状态栏（先 pack 到底部，保证窗口变小时不被挤掉）
        bar = ttk.Frame(self.root)
        bar.pack(side="bottom", fill="x", pady=(0, 12), **pad)
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.open_btn = ttk.Button(bar, text="打开报告", command=self._open_last, state="disabled")
        self.open_btn.pack(side="right", padx=(10, 0))
        self.status = ttk.Label(bar, text="就绪", style="Sub.TLabel", width=22)
        self.status.pack(side="right", padx=(10, 0))

        # 日志
        logf = ttk.Frame(self.root)
        logf.pack(fill="both", expand=True, pady=(12, 6), **pad)
        self.log = tk.Text(logf, height=9, font=("Consolas", 9), bg="#0f172a", fg="#cbd5e1",
                           insertbackground="#cbd5e1", bd=0, padx=12, pady=10, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    # ---------------- 事件 ----------------
    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        self._add([p for p in paths if p.lower().endswith(VIDEO_EXT)] or list(paths))

    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="选择视频",
            filetypes=[("视频文件", "*.mp4 *.mov *.m4v *.3gp"), ("所有文件", "*.*")],
        )
        self._add(list(files))

    def _add(self, paths):
        for p in paths:
            if os.path.isfile(p) and p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", f"  {os.path.basename(p)}")
        self._log(f"已添加 {len(self.files)} 个文件")
        self.status.configure(text=f"{len(self.files)} 个文件")

    def _remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            self.files.pop(i)

    def _clear(self):
        self.files.clear()
        self.reports.clear()
        self.listbox.delete(0, "end")
        self._set_log("")
        self.progress["value"] = 0
        self.status.configure(text="就绪")
        self.open_btn.configure(state="disabled")

    # ---------------- 解析 ----------------
    def _start(self):
        if self.running:
            return
        if not self.files:
            messagebox.showinfo(APP_TITLE, "先把视频拖进来，或点「选择视频文件」。")
            return
        self.running = True
        self.start_btn.configure(state="disabled")
        self.reports.clear()
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._set_log("")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            total = len(self.files)
            for idx, path in enumerate(self.files, 1):
                self.queue.put(("log", f"\n[{idx}/{total}] {os.path.basename(path)}"))
                self.queue.put(("status", f"解析 {idx}/{total}"))
                try:
                    self._process_one(path, idx, total)
                except Exception as e:
                    self.queue.put(("log", f"  ✗ 失败：{e}"))
                    self.queue.put(("log", traceback.format_exc().splitlines()[-1]))
                self.queue.put(("progress", int(idx / total * 100)))
            self.queue.put(("done", None))
        except Exception:
            self.queue.put(("log", "✗ 出错：" + traceback.format_exc()))

    def _process_one(self, path, idx, total):
        info = analyze(path)
        facts = collect(path, hashes=self.var_hash.get())
        rows = build_rows(info, facts)

        self.queue.put(("log", f"  容器 {info.container} · 时长 {fmt_duration(info.duration_s)} · "
                              f"{fmt_size(facts.size)}"))

        if info.video:
            v = info.video
            self.queue.put(("log", f"  视频 {v.codec_label} · {v.width}×{v.height} · "
                                  f"{v.frame_rate:.3f} FPS · {fmt_bitrate(v.bitrate)}"))
        if info.audio:
            a = info.audio
            self.queue.put(("log", f"  音频 {a.codec_label} · {a.sample_rate} Hz · {a.channels} 声道 · "
                                  f"{fmt_bitrate(a.bitrate)}"))

        n_ok = sum(1 for r in rows if r.status == "一致")
        n_bad = sum(1 for r in rows if r.status == "不一致")
        n_pro = len(rows) - n_ok - n_bad
        self.queue.put(("log", f"  三口径：一致 {n_ok} · 不一致 {n_bad} · 仅专业工具 {n_pro}"))

        out_dir = os.path.dirname(os.path.abspath(path))
        base = os.path.splitext(os.path.basename(path))[0]
        if self.var_html.get():
            out = os.path.join(out_dir, f"{base}_报告.html")
            try:
                with open(out, "w", encoding="utf-8") as f:
                    f.write(render_html(info, facts, rows))
            except OSError:
                out = os.path.join(os.path.expanduser("~"), "Desktop", f"{base}_报告.html")
                with open(out, "w", encoding="utf-8") as f:
                    f.write(render_html(info, facts, rows))
            self.reports.append(out)
            self.queue.put(("log", f"  ✓ 报告 {out}"))

        if self.var_xlsx.get():
            try:
                xls = os.path.join(out_dir, f"{base}_对比表.xlsx")
                if to_xlsx(info, facts, rows, xls):
                    self.queue.put(("log", f"  ✓ Excel {xls}"))
                else:
                    self.queue.put(("log", "  ! 未安装 openpyxl，跳过 Excel"))
            except Exception as e:
                self.queue.put(("log", f"  ! Excel 导出失败：{e}"))

    # ---------------- 队列刷新 ----------------
    def _poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self._finish()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _finish(self):
        self.running = False
        self.start_btn.configure(state="normal")
        self.progress["value"] = 100
        self.status.configure(text=f"完成 · {len(self.reports)} 份报告")
        if self.reports:
            self.open_btn.configure(state="normal")
            self._open_last()

    # ---------------- 小工具 ----------------
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_log(self, text):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        if text:
            self.log.insert("end", text)
        self.log.configure(state="disabled")

    def _open_last(self):
        if not self.reports:
            return
        target = self.reports[-1]
        try:
            os.startfile(target)          # Windows
        except AttributeError:
            import subprocess
            subprocess.Popen(["xdg-open", target])


def selftest(path):
    info = analyze(path)
    facts = collect(path)
    rows = build_rows(info, facts)
    print("容器:", info.container, info.major_brand, f"{info.duration_s:.3f}s")
    if info.video:
        v = info.video
        print("视频:", v.codec_label, f"{v.width}x{v.height}", f"{v.frame_rate:.3f} FPS")
    if info.audio:
        a = info.audio
        print("音频:", a.codec_label, a.sample_rate, "Hz", a.channels, "ch")
    print("对比行数:", len(rows), "不一致:", sum(1 for r in rows if r.status == "不一致"))
    out = os.path.join(os.path.dirname(os.path.abspath(path)), "selftest_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render_html(info, facts, rows))
    print("HTML:", out)
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2]))
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
