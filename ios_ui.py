# -*- coding: utf-8 -*-
"""iOS 风格 UI 辅助：毛玻璃(acrylic)背景、圆角卡片/按钮图片、iOS 配色。"""

import ctypes
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageFont, ImageTk

# ---- 极简低饱和灰蓝配色（浅色工具风）----
BG = "#f5f7fa"        # 窗口浅灰白背景
CARD = "#ffffff"      # 卡片纯白
PRIMARY = "#2563eb"   # 稳重深蓝（唯一强调色）
PRIMARY_D = "#1d4ed8" # 按压深蓝
OK = "#10b981"        # 低饱和绿（状态对勾）
ERR = "#dc2626"       # 错误红
WARN = "#d97706"      # 警告橙
TEXT = "#1f2937"      # 主文字（深灰）
SUB = "#6b7280"       # 次要文字（中灰）
SUB2 = "#9ca3af"      # 辅助说明（浅灰）
BORDER = "#e8edf3"    # 细浅灰边框
LINK = "#3b82f6"      # 提示链接浅蓝
HEADER_TOP = "#ffffff"  # 顶部浅色
HEADER_BOTTOM = "#f5f7fa"
SYNC_BG = "#e0e7ff"   # 同步官方按钮 浅灰蓝底
SYNC_FG = "#2563eb"   # 同步官方按钮 深蓝字
BTN_GRAY = "#f1f5f9"  # 浅灰按钮底
BTN_GRAY_FG = "#1f2937"  # 浅灰按钮深字

_FONT = "Microsoft YaHei UI"


def enable_acrylic(hwnd, tint=0x00F5F7FA):
    """启用 Windows 10/11 acrylic 毛玻璃窗口背景（失败静默）。
    浅色低透明度 tint，保持浅色极简风格。"""
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                        ("color", ctypes.c_uint), ("animation", ctypes.c_int)]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [("attrib", ctypes.c_int), ("data", ctypes.c_void_p),
                        ("size", ctypes.c_size_t)]

        accent = ACCENT_POLICY()
        accent.state = 4            # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.flags = 2
        accent.color = tint         # 半透明底色（ARGB）
        wcad = WINDOWCOMPOSITIONATTRIBDATA()
        wcad.attrib = 19            # WCA_ACCENT_POLICY
        wcad.data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        wcad.size = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(
            ctypes.c_void_p(hwnd), ctypes.byref(wcad))
    except Exception:  # noqa: BLE001
        pass


def rounded_rect_image(width, height, radius, fill=CARD, outline=None, bg="#FFFFFF"):
    """生成圆角矩形图片（背景色 bg，圆角色块 fill；tk 不支持透明，背景色与所在容器一致）。"""
    img = Image.new("RGB", (max(width, 1), max(height, 1)), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, max(width - 1, 0), max(height - 1, 0)],
                        radius=radius, fill=fill,
                        outline=outline or None)
    return ImageTk.PhotoImage(img)


def button_img(width, height, radius=10, color=PRIMARY, press_color=PRIMARY_D):
    """生成 iOS 风格圆角按钮图片（普通 + 按压两张）。返回 (normal, pressed)。"""
    n = rounded_rect_image(width, height, radius, fill=color)
    p = rounded_rect_image(width, height, radius, fill=press_color)
    return n, p


def aa_button_image(width, height, fill, inset=2, scale=5, radius=None):
    """抗锯齿圆角按钮图片：PIL 超采样渲染后 LANCZOS 缩回原尺寸，
    圆角边缘平滑无颗粒锯齿（Tk canvas 的 create_polygon 走 GDI，不抗锯齿）。
    radius 指定圆角半径（像素，逻辑尺寸）；缺省为胶囊(高一半)。
    小按钮(窄)用更小圆角使弧线平缓，放大查看与宽按钮视觉一致、不显颗粒。"""
    w, h, s = max(width, 1), max(height, 1), max(scale, 1)
    if radius is None:
        radius = (h - inset * 2) // 2
    radius = max(1, radius)
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = radius * s
    d.rounded_rectangle(
        [inset * s, inset * s, w * s - inset * s - 1, h * s - inset * s - 1],
        radius=r, fill=fill)
    # 先用双线性平滑过渡，再 LANCZOS 缩回，进一步柔化圆角边缘
    img = img.resize((max(1, w * 2), max(1, h * 2)), Image.BILINEAR)
    img = img.resize((w, h), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


class iOSButton:
    """Canvas 绘制的 iOS 圆角胶囊按钮（Windows 下 tk.Button 背景色会被主题忽略，Canvas 颜色可靠）。"""

    def __init__(self, parent, text, command=None, color=PRIMARY, press_color=None,
                 width=104, height=32, fg="#ffffff", font_size=10):
        self.text = text
        self.command = command
        self.color = color
        self.press_color = press_color or _darken(color)
        self.fg = fg
        self.width = width
        self.height = height
        self.font_size = font_size
        self.cv = tk.Canvas(parent, width=width, height=height, highlightthickness=0,
                            bg=parent.cget("bg"))
        # 圆角半径固定为胶囊形（高的一半），所有按钮统一成“添加账号”同款的圆滑药丸外轮廓
        radius = (height - 4) // 2
        # 抗锯齿按钮背景图（普通 + 按压），替代 GDI 多边形避免圆角像素颗粒
        self._imgs = {"normal": aa_button_image(width, height, color, radius=radius),
                      "pressed": aa_button_image(width, height, self.press_color, radius=radius)}
        self._img_ref = self._imgs["normal"]   # 保存 PhotoImage 引用防回收
        self._label = None
        self._draw(self.color)
        self.cv.bind("<Button-1>", self._on_press)
        self.cv.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, fill):
        self.cv.delete("all")
        img = self._imgs["pressed"] if fill == self.press_color else self._imgs["normal"]
        self._img_ref = img
        self.cv.create_image(self.width // 2, self.height // 2, image=img)
        # 文本用 Label（自动适配、可靠渲染，不裁剪）；字号自适应按钮宽度
        fs = self.font_size
        f = tkfont.Font(family=_FONT, size=fs, weight="bold")
        while f.measure(self.text) > (self.width - 22) and fs > 7:
            fs -= 1
            f = tkfont.Font(family=_FONT, size=fs, weight="bold")
        if self._label is None:
            self._label = tk.Label(self.cv, text=self.text, bg=fill, fg=self.fg,
                                   font=(_FONT, fs, "bold"))
            self._label.bind("<Button-1>", self._on_press)
            self._label.bind("<ButtonRelease-1>", self._on_release)
        else:
            self._label.config(text=self.text, bg=fill, fg=self.fg,
                               font=(_FONT, fs, "bold"))
        self.cv.create_window(self.width // 2, self.height // 2, window=self._label)

    def _on_press(self, _e):
        self._draw(self.press_color)

    def _on_release(self, _e):
        self._draw(self.color)
        if self.command:
            self.command()

    def set_text(self, text):
        """动态修改按钮文字（不改动布局），用于显示当前选择。"""
        if text == self.text:
            return
        self.text = text
        self._draw(self.color)

    def pack(self, **kw):
        self.cv.pack(**kw)

    def pack_configure(self, **kw):
        self.cv.pack_configure(**kw)


def _darken(color):
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (max(0, int(r * 0.85)), max(0, int(g * 0.85)),
                                  max(0, int(b * 0.85)))
    except Exception:  # noqa: BLE001
        return color
