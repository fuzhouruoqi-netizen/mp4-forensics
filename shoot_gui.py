# -*- coding: utf-8 -*-
"""直接抓取目标窗口内容（PrintWindow，不受遮挡影响）。开发用。"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

from PIL import Image

TITLE = "MP4 视听数据解析 · 取证工具"
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002

hwnd = 0
for _ in range(40):
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        break
    time.sleep(0.25)
if not hwnd:
    print("window not found")
    sys.exit(1)

time.sleep(0.8)
rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w, h = rect.right - rect.left, rect.bottom - rect.top
if w <= 0 or h <= 0:
    print("bad size", w, h)
    sys.exit(1)

hdc_screen = user32.GetWindowDC(hwnd)
hdc = gdi32.CreateCompatibleDC(hdc_screen)
bmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
gdi32.SelectObject(hdc, bmp)

ok = user32.PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)
print("PrintWindow:", ok)

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]

bi = BITMAPINFOHEADER()
bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bi.biWidth = w
bi.biHeight = -h
bi.biPlanes = 1
bi.biBitCount = 32
bi.biCompression = 0

buf = ctypes.create_string_buffer(w * h * 4)
got = gdi32.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
print("GetDIBits rows:", got)

img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
out = sys.argv[1] if len(sys.argv) > 1 else "gui.png"
img.save(out)
print("saved", img.size, "->", out)

gdi32.DeleteObject(bmp)
gdi32.DeleteDC(hdc)
user32.ReleaseDC(hwnd, hdc_screen)
user32.PostMessageW(hwnd, 0x0010, 0, 0)
