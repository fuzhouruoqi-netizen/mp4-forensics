# -*- coding: utf-8 -*-
"""单元测试：python -m unittest discover -s tests -t . -v"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mp4forensics import analyze, collect, parse_file  # noqa: E402
from mp4forensics.compare import CONSISTENT, INCONSISTENT, build  # noqa: E402
from mp4forensics.media import fmt_duration  # noqa: E402
from mp4forensics.report import hex_dump, render_html, to_json  # noqa: E402
from tests import build_sample  # noqa: E402


class SampleMixin:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mp4f-")
        cls.path = build_sample.build(os.path.join(cls.tmp, "sample.mp4"))


class TestBoxParser(SampleMixin, unittest.TestCase):
    def test_top_level(self):
        root, size = parse_file(self.path)
        types = [b.type for b in root.children]
        self.assertIn("ftyp", types)
        self.assertIn("moov", types)
        self.assertIn("mdat", types)
        self.assertEqual(size, os.path.getsize(self.path))

    def test_tree_paths(self):
        root, _ = parse_file(self.path)
        mdhd = root.find("moov/trak/mdia/mdhd")
        self.assertIsNotNone(mdhd)
        self.assertEqual(mdhd.type, "mdhd")

    def test_find_all(self):
        root, _ = parse_file(self.path)
        self.assertEqual(len(root.find_all("moov/trak")), 2)

    def test_64bit_size(self):
        """size==1 的 largesize 必须按 64 位读，不能溢出成负数。"""
        payload = b"\x00" * 32
        data = build_sample.large_box("mdat", payload)
        f = os.path.join(self.tmp, "large.mp4")
        with open(f, "wb") as fh:
            fh.write(data)
        root, _ = parse_file(f)
        mdat = root.children[0]
        self.assertEqual(mdat.type, "mdat")
        self.assertEqual(mdat.size, 16 + len(payload))
        self.assertGreater(mdat.size, 0)

    def test_truncated_file(self):
        with open(self.path, "rb") as fh:
            data = fh.read()
        f = os.path.join(self.tmp, "trunc.mp4")
        with open(f, "wb") as fh:
            fh.write(data[: len(data) // 2])
        root, _ = parse_file(f)          # 不应抛异常
        self.assertTrue(len(root.children) > 0)


class TestMetadata(SampleMixin, unittest.TestCase):
    def setUp(self):
        self.info = analyze(self.path)

    def test_container(self):
        self.assertEqual(self.info.major_brand, "isom")
        self.assertIn("iso2", self.info.compatible_brands)
        self.assertAlmostEqual(self.info.duration_s, 10.0, places=3)

    def test_video_track(self):
        v = self.info.video
        self.assertIsNotNone(v)
        self.assertEqual(v.codec, "AVC")
        self.assertEqual((v.width, v.height), (1920, 1080))
        self.assertAlmostEqual(v.frame_rate, 30.0, places=3)
        self.assertIn("恒定", v.frame_rate_mode)
        self.assertEqual(v.sync_samples, [1, 61, 121])
        self.assertEqual(v.sample_count, 300)
        self.assertAlmostEqual(v.bitrate, 1500 * 300 * 8 / 10.0, delta=1)

    def test_audio_track(self):
        a = self.info.audio
        self.assertIsNotNone(a)
        self.assertEqual(a.codec, "AAC")
        self.assertEqual(a.sample_rate, 48000)   # 取自 AudioSpecificConfig
        self.assertEqual(a.channels, 2)
        self.assertEqual(a.bitrate, 192000)

    def test_duration_format(self):
        self.assertEqual(fmt_duration(8.819), "8 秒 819 毫秒")
        self.assertEqual(fmt_duration(0.5), "0 秒 500 毫秒")


class TestCompare(SampleMixin, unittest.TestCase):
    def test_rows(self):
        info = analyze(self.path)
        facts = collect(self.path)
        rows = build(info, facts)
        fields = [r.field for r in rows]
        self.assertIn("总时长", fields)
        self.assertIn("帧率", fields)
        self.assertIn("音频编码", fields)
        dur = next(r for r in rows if r.field == "总时长")
        self.assertEqual(dur.status, CONSISTENT)
        codec = next(r for r in rows if r.field == "视频编码")
        self.assertEqual(codec.system, "—")       # 系统属性看不到编码

    def test_size_mismatch_detected(self):
        info = analyze(self.path)
        facts = collect(self.path)
        facts.size = 123                    # 人为制造不一致
        rows = build(info, facts)
        size = next(r for r in rows if r.field == "文件大小")
        self.assertEqual(size.status, INCONSISTENT)


class TestReport(SampleMixin, unittest.TestCase):
    def test_html_and_json(self):
        info = analyze(self.path)
        facts = collect(self.path)
        rows = build(info, facts)
        html = render_html(info, facts, rows)
        self.assertIn("三口径对比", html)
        self.assertIn("sha-256", html.lower())
        self.assertIn("stss", html)
        data = to_json(info, facts, rows)
        self.assertEqual(data["container"]["major_brand"], "isom")
        self.assertEqual(len(data["tracks"]), 2)

    def test_hex_dump(self):
        out = hex_dump(b"\x00\x01\x02ABC", base=0)
        self.assertIn("00000000", out)
        self.assertIn("ABC", out)


class TestRealFile(unittest.TestCase):
    """仓库里带的小样本（MPEG-4 Visual，无音轨）。"""

    real = ROOT.parent / "video-forensics" / "test.mp4"

    @unittest.skipUnless(real.exists(), "缺少 samples/test.mp4")
    def test_real(self):
        info = analyze(str(self.real))
        self.assertGreater(info.duration_s, 0)
        self.assertIsNotNone(info.video)
        self.assertEqual(info.video.width, 640)


if __name__ == "__main__":
    unittest.main()
