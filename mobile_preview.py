# -*- coding: utf-8 -*-
"""大模型余额监控 —— 手机版界面预览 v6（紧凑布局,主色背景,圆形功能按钮）。

纯 UI 美化。余额/已消费背景随模型图标主色变化(DeepSeek=蓝)。
"""

import base64
import ctypes
import io
import math
import tkinter as tk

from PIL import Image, ImageTk

from logo_data import DS_LOGO_B64, GEAR_B64, KEYLOCK_B64

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

BG = "#f1f2f6"
CARD = "#ffffff"
MODEL_MAIN = "#4d6bfe"      # 当前模型主色(DeepSeek=蓝,切换模型后变)
MODEL_BG = "#eaf1fe"        # 主色淡背景
TEXT = "#1c1c1e"
SUB = "#8e8e93"
F = "Microsoft YaHei UI"


def load_logo(b64, height):
    if not b64:
        return None
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    w, h = img.size
    nw = max(1, int(w * height / h))
    img = img.resize((nw, height), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def main():
    root = tk.Tk()
    root.title("大模型余额监控 - 手机预览版")
    root.geometry("390x844+120+30")
    root.configure(bg="#000000")

    phone = tk.Frame(root, bg=BG)
    phone.pack(fill="both", expand=True, padx=8, pady=8)

    # 顶部状态栏
    tk.Label(phone, text="9:41", bg=BG, fg=TEXT,
             font=("Helvetica", 12, "bold")).pack(anchor="w", padx=18, pady=2)

    # 模型行:文字 + 右侧鲸鱼
    model_row = tk.Frame(phone, bg=BG)
    model_row.pack(fill="x", padx=18, pady=(2, 6))
    tk.Label(model_row, text="当前模型：DeepSeek", bg=BG, fg=SUB,
             font=(F, 12)).pack(side="left")
    _ds = load_logo(DS_LOGO_B64, 16)
    if _ds:
        _l = tk.Label(model_row, image=_ds, bg=BG)
        _l.pack(side="left", padx=(6, 0))
        _l.image = _ds

    # 余额卡(主色淡背景,居中)
    bal = tk.Frame(phone, bg=MODEL_BG)
    bal.pack(fill="x", padx=16, pady=4)
    tk.Label(bal, text="账户余额", bg=MODEL_BG, fg=SUB,
             font=(F, 12)).pack(pady=(12, 2))
    row = tk.Frame(bal, bg=MODEL_BG)
    row.pack()
    tk.Label(row, text="¥", bg=MODEL_BG, fg=TEXT,
             font=("Helvetica", 20, "bold")).pack(side="left")
    tk.Label(row, text="12.34", bg=MODEL_BG, fg=TEXT,
             font=("Helvetica", 34, "bold")).pack(side="left")
    # 已消费一行(Canvas 防裁切)
    bcv = tk.Canvas(bal, bg=MODEL_BG, highlightthickness=0, width=330, height=22)
    bcv.pack(pady=(2, 12))
    bcv.create_text(165, 11, text="已消费 ¥999.99 · Token 9999万",
                    anchor="center", fill=SUB, font=(F, 11))

    # 当前模型累计已消费(主色淡背景,紧凑)
    spent = tk.Frame(phone, bg=MODEL_BG)
    spent.pack(fill="x", padx=16, pady=3)
    tk.Label(spent, text="当前模型累计已消费", bg=MODEL_BG, fg=SUB,
             font=(F, 11)).pack(anchor="w", padx=16, pady=(8, 1))
    tk.Label(spent, text="¥ 20.00", bg=MODEL_BG, fg=TEXT,
             font=("Helvetica", 20, "bold")).pack(anchor="w", padx=16, pady=(0, 8))

    # 功能卡片(紧凑)
    grid = tk.Frame(phone, bg=BG)
    grid.pack(fill="x", padx=16, pady=4)
    for i, (icon, title) in enumerate([("📅", "每日用量"), ("🔔", "余额预警")]):
        r, c = i // 2, i % 2
        card = tk.Frame(grid, bg=CARD, highlightbackground="#e3e4e8",
                        highlightthickness=1, height=84)
        card.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
        grid.rowconfigure(r, weight=1)
        grid.columnconfigure(c, weight=1)
        tk.Label(card, text=icon, bg=CARD, fg=TEXT,
                 font=(F, 18)).pack(pady=(12, 2))
        tk.Label(card, text=title, bg=CARD, fg=TEXT,
                 font=(F, 13, "bold")).pack()

    # 底部:设置(⚙ 静态) + API管理(🔑钥匙 + 锁 开锁动画,风格统一)
    bottom = tk.Frame(phone, bg=BG)
    bottom.pack(side="bottom", pady=12)

    # 底部:设置/API管理(⚙🔑 字符图标,删掉外圈圆圈)
    for icon in ["⚙", "🔑"]:
        ic = tk.Label(bottom, text=icon, bg=BG, fg=TEXT, font=(F, 22), cursor="hand2")
        ic.pack(side="left", padx=26)

    root.mainloop()


if __name__ == "__main__":
    main()
