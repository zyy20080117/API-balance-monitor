# -*- coding: utf-8 -*-
"""大模型余额监控 —— 桌面 GUI（中文界面）"""

import calendar
import datetime
import json
import math
import os
import queue
import re

from PIL import Image as PILImage, ImageDraw, ImageFont, ImageTk
import threading
import time
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

import ctypes

import browser_sync
import ios_ui
import kimi_sync
import logger
import openrouter_sync
import providers
import siliconflow_sync
import storage
import zhipu_sync

# ---- iOS 风格配色（毛玻璃/柔和苹果风）----
COLOR_BG = ios_ui.BG
COLOR_CARD = ios_ui.CARD
COLOR_PRIMARY = ios_ui.PRIMARY
COLOR_OK = ios_ui.OK
COLOR_ERR = ios_ui.ERR
COLOR_TEXT = ios_ui.TEXT
COLOR_SUB = ios_ui.SUB
COLOR_SUB2 = ios_ui.SUB2
COLOR_BORDER = ios_ui.BORDER
COLOR_HEADER = ios_ui.HEADER_TOP

FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_CARD_NAME = ("Microsoft YaHei UI", 11, "bold")
FONT_CARD_BALANCE = ("Microsoft YaHei UI", 20, "bold")
FONT_NORMAL = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)


def _provider_id_to_name(pid):
    p = providers.get_provider(pid)
    return p["name"] if p else (pid or "")


def _provider_short_name(pid):
    """服务商显示短名：只取名称首段（如「硅基流动 SiliconFlow」→「硅基流动」）。"""
    name = _provider_id_to_name(pid)
    return (name.split(" ")[0] if name else (pid or "")).strip()


def _provider_name_to_id(name):
    for p in providers.PROVIDERS:
        if p["name"] == name:
            return p["id"]
    return name


def _heat(ratio):
    """消耗程度 0~1 渐变：低绿 → 中黄 → 高红。"""
    ratio = max(0.0, min(1.0, ratio))
    if ratio < 0.5:
        r = int(255 * ratio * 2)
        g = 255
    else:
        r = 255
        g = int(255 * (1 - (ratio - 0.5) * 2))
    b = 40
    return "#%02x%02x%02x" % (r, g, b)


# GB2312 区位码 → 拼音首字母分段表（用于中文账号名称排序）
_PINYIN_TABLE = [
    (1601, 1636, 'a'), (1637, 1832, 'b'), (1833, 2078, 'c'),
    (2079, 2274, 'd'), (2275, 2302, 'e'), (2303, 2433, 'f'),
    (2434, 2594, 'g'), (2595, 2787, 'h'), (2788, 3106, 'j'),
    (3107, 3210, 'k'), (3211, 3370, 'l'), (3371, 3613, 'm'),
    (3614, 3648, 'n'), (3649, 3653, 'o'), (3654, 3661, 'p'),
    (3662, 3898, 'q'), (3899, 3909, 'r'), (3910, 4109, 's'),
    (4110, 4150, 't'), (4151, 4305, 'w'), (4306, 4477, 'x'),
    (4478, 4671, 'y'), (4672, 5600, 'z'),
]


def _py_first(ch):
    """返回单个字符的排序键：英文/数字原样小写，中文返回拼音首字母。"""
    if not ch:
        return ''
    if 'a' <= ch.lower() <= 'z':
        return ch.lower()
    if '0' <= ch <= '9':
        return ch
    try:
        gb = ch.encode('gb2312')
    except Exception:  # noqa: BLE001
        return ch
    if len(gb) != 2:
        return ch
    code = (gb[0] - 0xA0) * 100 + (gb[1] - 0xA0)
    for lo, hi, letter in _PINYIN_TABLE:
        if lo <= code <= hi:
            return letter
    return 'z'


class BalanceApp:
    def __init__(self, root, scale=1.0):
        self.root = root
        self.root.title("大模型余额监控")
        # DPI 感知下 tk 按物理像素解释 geometry，按屏幕 DPI 系数放大窗口尺寸
        self.root.geometry(f"{int(540 * scale)}x{int(680 * scale)}")
        self.root.minsize(int(460 * scale), int(500 * scale))
        self.root.configure(bg=COLOR_BG)
        self._btn_imgs = []   # 保存 PhotoImage 引用，防止被垃圾回收
        # 深色模式下全局默认前景/输入框配色（避免黑字在深色背景不可见）
        root.option_add("*foreground", COLOR_TEXT)
        root.option_add("*Entry.background", COLOR_CARD)
        root.option_add("*Entry.foreground", COLOR_TEXT)
        root.option_add("*Listbox.background", COLOR_CARD)
        root.option_add("*Listbox.foreground", COLOR_TEXT)
        root.option_add("*Combobox*Listbox.background", COLOR_CARD)
        root.option_add("*Combobox*Listbox.foreground", COLOR_TEXT)
        self._enable_acrylic()

        logger.log("程序启动，开始加载账号…")
        self.accounts = storage.load_accounts()
        logger.log(f"加载到 {len(self.accounts)} 个账号")
        self.results = {}
        self.official_data = None
        self.daily_data = None
        # Kimi 浏览器同步结果（已消费/余额）：优先读缓存，启动即有数据显示，避免冷启动等待
        self.kimi_data = self._load_kimi_cache()
        # 智谱浏览器同步结果：同样优先读缓存
        self.zhipu_data = self._load_zhipu_cache()
        # 硅基流动浏览器同步结果：同样优先读缓存
        self.siliconflow_data = self._load_siliconflow_cache()
        # OpenRouter 浏览器同步结果（每日用量）缓存
        self.openrouter_data = self._load_openrouter_cache()
        self.last_update = None
        self.refresh_lock = threading.Lock()
        _settings = storage.load_settings()
        self.auto_minutes = tk.IntVar(value=1 if _settings["auto_refresh"] else 0)
        self._saved_minutes = int(_settings.get("auto_minutes", 10))
        self.auto_job = None
        self.sync_enabled = tk.IntVar(value=1 if _settings.get("auto_sync") else 0)
        self._saved_sync_minutes = int(_settings.get("auto_sync_minutes", 30))
        self.sync_job = None
        # 主账号（精准到某一模型的具体 API）与「按主账号」的费用预警阈值
        self._master_id = str(_settings.get("master_account_id", "") or "")
        self._master_api = str(_settings.get("master_api_name", "") or "")
        self._alerts = dict(_settings.get("alerts", {}) or {})
        # 列表排序模式（空=默认添加顺序；time/balance/name），数据更新后保持重排
        self._sort_mode = str(_settings.get("sort_mode", "") or "")
        self._net_retry = 0   # 开机网络未就绪时的自动重试计数
        # 兼容旧版本单一预警阈值：迁移到主账号
        old_th = float(_settings.get("alert_threshold", 0) or 0)
        if not self._alerts and old_th > 0 and self._master_id:
            self._alerts[self._master_id] = old_th

        # 线程安全：工作线程把结果放进队列，主线程轮询执行
        self.ui_queue = queue.Queue()

        # 启动时恢复上次选择的排序方式，保证显示顺序与排序菜单一致
        # （此后顺序固定，刷新/同步等行为不改变）
        self._apply_sort_order()
        self._build_header()
        self._build_list()
        self._build_footer()
        self._poll_queue()
        self._schedule_auto_refresh()
        self.refresh_all()

    def _enable_acrylic(self):
        """极简浅色风格：禁用毛玻璃，使用纯色浅灰白背景，避免透出桌面导致过曝/全白。"""
        pass

    # ------------------------------------------------------------------ 界面
    def _build_header(self):
        head = tk.Frame(self.root, bg=COLOR_HEADER)
        head.pack(fill="x")

        left = tk.Frame(head, bg=COLOR_HEADER)
        left.pack(side="left", fill="x", expand=True, padx=18, pady=12)
        tk.Label(left, text="💰 大模型余额监控", bg=COLOR_HEADER,
                 fg=COLOR_TEXT, font=FONT_TITLE).pack(anchor="w")
        # 标题下不再显示状态小字（用户要求精简界面）

        # 同步官方：浅灰蓝底深蓝字；刷新余额：深蓝底白字
        ios_ui.iOSButton(head, "同步官方", self.sync_official, color=ios_ui.SYNC_BG,
                         fg=ios_ui.SYNC_FG, width=104, height=32).pack(side="right", padx=(0, 10))
        ios_ui.iOSButton(head, "刷新余额", self.refresh_all, color=COLOR_PRIMARY,
                         width=96, height=32).pack(side="right", padx=14)

    def _build_list(self):
        wrap = tk.Frame(self.root, bg=COLOR_BG)
        wrap.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        self.canvas = tk.Canvas(wrap, bg=COLOR_BG, highlightthickness=0,
                                yscrollincrement=20)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                          bg="#e8edf3", troughcolor=COLOR_BG, activebackground="#d1d5db",
                          relief="flat", bd=0, width=10)
        self.list_frame = tk.Frame(self.canvas, bg=COLOR_BG)
        self.list_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind(
            "<Configure>", lambda e: self.canvas.itemconfig("all", width=e.width))

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _bind_scroll(self, widget=None):
        """递归给列表及其所有子控件绑定滚轮事件，使鼠标停在卡片上也能上下滚动。"""
        widget = widget or self.list_frame
        widget.bind("<MouseWheel>", self._on_wheel)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _build_footer(self):
        foot = tk.Frame(self.root, bg=COLOR_BG)
        foot.pack(fill="x", padx=14, pady=12)

        # 功能按钮行（iOS 深灰胶囊）
        func_row = tk.Frame(foot, bg=COLOR_BG)
        func_row.pack(fill="x", pady=(0, 8))
        for text, cmd in (("每日用量", self.show_daily), ("预警设置", self.set_alert)):
            ios_ui.iOSButton(func_row, text, cmd, color=ios_ui.BTN_GRAY,
                             fg=ios_ui.BTN_GRAY_FG, width=92, height=30, font_size=9).pack(side="left", padx=(0, 8))
        # 主账号功能区：点击选择主账号（每日用量 / 预警设置都跟随它）
        self.master_btn = ios_ui.iOSButton(func_row, self._master_label(),
                                           self.open_master_dialog, color=ios_ui.BTN_GRAY,
                                           fg=ios_ui.BTN_GRAY_FG, width=120, height=30, font_size=9)
        self.master_btn.pack(side="left", padx=(0, 8))

        ios_ui.iOSButton(foot, "＋ 添加账号", self.open_add_dialog, color=COLOR_PRIMARY,
                         width=110, height=34, font_size=10).pack(side="left")
        # 排序按钮：配色/形状与「添加账号」一致，点击弹出排序选项
        self.sort_btn = ios_ui.iOSButton(foot, "排序", self.open_sort_menu, color=COLOR_PRIMARY,
                                         width=70, height=34, font_size=10)
        self.sort_btn.pack(side="left", padx=(8, 0))

        auto_frame = tk.Frame(foot, bg=COLOR_BG)
        auto_frame.pack(side="right")

        # 行1：自动刷新（余额接口）
        row1 = tk.Frame(auto_frame, bg=COLOR_BG)
        row1.pack(anchor="e")
        tk.Checkbutton(
            row1, text="自动刷新余额", variable=self.auto_minutes, command=self._toggle_auto,
            onvalue=1, offvalue=0, bg=COLOR_BG, font=FONT_NORMAL,
            activebackground=COLOR_BG).pack(side="left")
        self.auto_var = tk.StringVar(value=str(self._saved_minutes))
        self.auto_spin = tk.Spinbox(
            row1, from_=1, to=120, width=5, textvariable=self.auto_var,
            font=FONT_NORMAL, bg=COLOR_CARD, fg=COLOR_TEXT,
            buttonbackground="#e8edf3", relief="flat", bd=1, highlightthickness=0)
        self.auto_spin.pack(side="left", padx=(6, 2))
        self.auto_spin.bind("<<Increment>>", lambda e: self._on_minutes_change())
        self.auto_spin.bind("<<Decrement>>", lambda e: self._on_minutes_change())
        # 允许手动输入分钟数：回车或失焦即保存生效
        self.auto_spin.bind("<Return>", lambda e: self._on_minutes_change())
        self.auto_spin.bind("<FocusOut>", lambda e: self._on_minutes_change())
        tk.Label(row1, text="分钟", bg=COLOR_BG, font=FONT_NORMAL).pack(side="left")

        # 行2：自动同步官方（浏览器抓取，较慢，间隔建议大些）
        row2 = tk.Frame(auto_frame, bg=COLOR_BG)
        row2.pack(anchor="e", pady=(4, 0))
        tk.Checkbutton(
            row2, text="自动同步官方", variable=self.sync_enabled, command=self._toggle_sync,
            onvalue=1, offvalue=0, bg=COLOR_BG, font=FONT_NORMAL,
            activebackground=COLOR_BG).pack(side="left")
        self.sync_minutes_var = tk.StringVar(value=str(self._saved_sync_minutes))
        self.sync_spin = tk.Spinbox(
            row2, from_=1, to=120, width=5, textvariable=self.sync_minutes_var,
            font=FONT_NORMAL, bg=COLOR_CARD, fg=COLOR_TEXT,
            buttonbackground="#e8edf3", relief="flat", bd=1, highlightthickness=0)
        self.sync_spin.pack(side="left", padx=(6, 2))
        self.sync_spin.bind("<<Increment>>", lambda e: self._on_sync_minutes_change())
        self.sync_spin.bind("<<Decrement>>", lambda e: self._on_sync_minutes_change())
        # 允许手动输入分钟数：回车或失焦即保存生效
        self.sync_spin.bind("<Return>", lambda e: self._on_sync_minutes_change())
        self.sync_spin.bind("<FocusOut>", lambda e: self._on_sync_minutes_change())
        tk.Label(row2, text="分钟", bg=COLOR_BG, font=FONT_NORMAL).pack(side="left")

        self._toggle_auto()
        self._toggle_sync()
        # 点击任意处（包括不接收焦点的空白）都把输入框里的时间立即保存，
        # 避免必须按回车/退出软件才生效
        self.root.bind("<Button-1>", self._on_global_click, add="+")

    def _on_global_click(self, event):
        """全局点击：点击输入框以外的任意地方（含不接收焦点的空白）时，
        立即保存输入框里的时间，并把焦点移出输入框（光标不再停留在时间那）。"""
        try:
            w = self.root.focus_get()
        except Exception:  # noqa: BLE001
            return
        if w is self.auto_spin:
            if event.widget is not w:
                self._on_minutes_change()
                self._clear_spin_focus()
        elif w is self.sync_spin:
            if event.widget is not w:
                self._on_sync_minutes_change()
                self._clear_spin_focus()

    def _clear_spin_focus(self):
        """把焦点移到窗口根，让光标离开时间输入框。"""
        try:
            self.root.focus_set()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 列表
    def _rebuild_list(self):
        # 重建时不重排：同步官方/刷新过程中保持稳定（避免中间态乱序）。
        # 排序只在用户点击排序、启动、以及同步官方/刷新全部完成后应用
        try:
            ypos = self.canvas.yview()[0]   # 记住滚动位置，重建后恢复，避免跳回顶部
        except Exception:  # noqa: BLE001
            ypos = 0.0
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self.accounts:
            empty = tk.Frame(self.list_frame, bg=COLOR_BG)
            empty.pack(fill="both", expand=True, pady=60)
            tk.Label(empty, text="还没有账号\n\n点击下方「＋ 添加账号」\n选择服务商并粘贴你的 API Key",
                     bg=COLOR_BG, fg=COLOR_SUB2, font=("Microsoft YaHei UI", 12),
                     justify="center").pack()
            return
        for acc in self.accounts:
            try:
                self._make_card(acc)
            except Exception as e:
                # 单张卡片出错不影响其它卡片
                err_card = tk.Label(self.list_frame, text=f"卡片渲染失败：{e}",
                                    bg="#fee2e2", fg=COLOR_ERR, font=FONT_SMALL)
                err_card.pack(fill="x", pady=(0, 10))
        # 卡片多时保证鼠标停在卡片上也能滚轮滚动
        self._bind_scroll()
        # 恢复滚动位置（比例），避免重建后列表跳回顶部
        try:
            self.canvas.yview_moveto(ypos)
        except Exception:  # noqa: BLE001
            pass

    def _update_card(self, acc_id):
        """只重建某一张账号卡片，避免同步/刷新时整屏闪烁。"""
        for child in self.list_frame.winfo_children():
            if getattr(child, "_acc_id", None) == acc_id:
                child.destroy()
                break
        # 找到该账号之后的下一个已存在卡片，把新卡插回原位（避免乱跳 + 免全量重排）
        acc_idx = next((i for i, a in enumerate(self.accounts) if a["id"] == acc_id), None)
        before = None
        if acc_idx is not None:
            for a in self.accounts[acc_idx + 1:]:
                for child in self.list_frame.winfo_children():
                    if getattr(child, "_acc_id", None) == a["id"]:
                        before = child
                        break
                if before is not None:
                    break
        for acc in self.accounts:
            if acc["id"] == acc_id:
                card = self._make_card(acc, before=before)
                self._bind_card_scroll(card)   # 新卡补绑滚轮，避免停在该卡上无法滚动
                break

    def _bind_card_scroll(self, card):
        """给一张卡片及其所有子控件绑定滚轮（重建后的新卡不会自动继承滚动绑定）。"""
        try:
            card.bind("<MouseWheel>", self._on_wheel)
            for child in card.winfo_children():
                self._bind_card_scroll(child)
        except Exception:  # noqa: BLE001
            pass

    def _reorder_cards(self):
        """按 accounts 顺序重新摆放卡片，保证数据更新后顺序不乱跳。"""
        cards = {}
        for child in list(self.list_frame.winfo_children()):
            cid = getattr(child, "_acc_id", None)
            cards[cid] = child
            child.pack_forget()
        for acc in self.accounts:
            c = cards.get(acc["id"])
            if c is not None:
                c.pack(fill="x", pady=(0, 10))

    def _make_card(self, acc, before=None):
        provider_name = _provider_id_to_name(acc.get("provider"))
        card_name = acc.get("name") or provider_name

        card = tk.Frame(self.list_frame, bg=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1)
        if before is not None:
            # 重建单卡时插回原位置，避免 _make_card 默认加到末尾导致顺序乱跳
            card.pack(fill="x", pady=(0, 10), before=before)
        else:
            card.pack(fill="x", pady=(0, 10))
        card._acc_id = acc["id"]   # 供按卡片局部更新（避免整屏闪烁）
        card.bind("<Button-3>", lambda e, a=acc: self._card_menu(e, a))

        res = self.results.get(acc["id"])
        # 智谱/硅基流动：无公开 HTTP 余额接口，余额/消费以浏览器同步数据为准
        is_zhipu = acc.get("provider") == "zhipu"
        z_ok = bool(is_zhipu and getattr(self, "zhipu_data", None) and self.zhipu_data.get("ok"))
        z_syncing = bool(is_zhipu and getattr(self, "_zhipu_syncing", False))
        is_siliconflow = acc.get("provider") == "siliconflow"
        s_ok = bool(is_siliconflow and getattr(self, "siliconflow_data", None)
                    and self.siliconflow_data.get("ok"))
        s_syncing = bool(is_siliconflow and getattr(self, "_siliconflow_syncing", False))
        is_openrouter = acc.get("provider") == "openrouter"

        # 顶行：名称 + 服务商 + 状态
        top = tk.Frame(card, bg=COLOR_CARD)
        top.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(top, text=card_name, bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=FONT_CARD_NAME).pack(side="left")
        tk.Label(top, text=provider_name, bg="#eef2ff", fg="#2563eb",
                 font=("Microsoft YaHei UI", 8), padx=6, pady=1).pack(side="left", padx=(8, 0))
        if acc.get("id") == getattr(self, "_master_id", ""):
            tk.Label(top, text="⭐ 主账号", bg="#ffedd5", fg="#d97706",
                     font=("Microsoft YaHei UI", 8), padx=6, pady=1).pack(side="left", padx=(8, 0))

        if is_zhipu:
            if z_ok:
                state_txt, state_color = "✔ 正常", COLOR_OK
            elif z_syncing:
                state_txt, state_color = "同步中…", "#d97706"
            else:
                state_txt, state_color = "需同步官方", "#d97706"
        elif is_siliconflow:
            if s_ok:
                state_txt, state_color = "✔ 正常", COLOR_OK
            elif s_syncing:
                state_txt, state_color = "同步中…", "#d97706"
            else:
                state_txt, state_color = "需同步官方", "#d97706"
        elif res is None:
            state_txt, state_color = "查询中…", "#d97706"
        elif res.get("ok"):
            state_txt, state_color = "✔ 正常", COLOR_OK
        elif self._is_network_error(res):
            # 开机/网络未就绪：不是账号问题，不标红叉，稍后自动重试
            state_txt, state_color = "⏳ 网络未就绪", "#d97706"
        else:
            state_txt, state_color = "✖ 异常", COLOR_ERR
        # 顶行右侧：状态 + 编辑/删除按钮（可直接改账号名称或删除）
        right = tk.Frame(top, bg=COLOR_CARD)
        right.pack(side="right")
        tk.Label(right, text=state_txt, bg=COLOR_CARD, fg=state_color,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        tk.Button(right, text="编辑", command=lambda a=acc: self.open_edit_dialog(a),
                  bg="#e0f2fe", fg="#0369a1", relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 8, "bold"), padx=6, pady=1,
                  cursor="hand2", activebackground="#bae6fd").pack(side="left", padx=(6, 0))
        tk.Button(right, text="🗑 删除", command=lambda a=acc: self.delete_account(a),
                  bg="#fee2e2", fg="#dc2626", relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 8, "bold"), padx=6, pady=1,
                  cursor="hand2", activebackground="#fecaca").pack(side="left", padx=(6, 0))

        # 余额行
        mid = tk.Frame(card, bg=COLOR_CARD)
        mid.pack(fill="x", padx=14, pady=(2, 0))
        if is_zhipu:
            if z_ok:
                bal_txt = "¥" + self.zhipu_data["data"].get("balance", "?")
            elif z_syncing:
                bal_txt = "同步中…"
            else:
                bal_txt = "——"
        elif is_siliconflow:
            if s_ok:
                bal_txt = "¥" + self.siliconflow_data["data"].get("balance", "?")
            elif s_syncing:
                bal_txt = "同步中…"
            elif res and res.get("ok"):
                # 未同步：先用 HTTP 接口余额（有就保留），已消费/每日用量需同步官方
                unit = res.get("unit") or ""
                symbol = "¥" if unit == "CNY" else ""
                val = res.get("value")
                try:
                    val = f"{float(val):.2f}"
                except (TypeError, ValueError):
                    pass
                bal_txt = f"{symbol}{val} {unit}" if unit else f"{val}"
            else:
                bal_txt = "——"
        elif res is None:
            bal_txt = "…"
        elif res.get("ok"):
            if acc.get("provider") == "deepseek" and self.official_data and self.official_data.get("ok"):
                # 已同步官方：余额统一用官方页面数据（更权威、和用量行一致）
                d = self.official_data["data"]
                bal_txt = f"¥{d.get('balance', res.get('value'))}"
            else:
                unit = res.get("unit") or ""
                symbol = ""
                if unit == "CNY":
                    symbol = "¥"
                elif unit == "USD":
                    symbol = "$"
                val = res.get("value")
                try:
                    val = f"{float(val):.2f}"
                except (TypeError, ValueError):
                    pass
                bal_txt = f"{symbol}{val} {unit}" if unit else f"{val}"
        else:
            bal_txt = "——"
        tk.Label(mid, text=bal_txt, bg=COLOR_CARD, fg=COLOR_PRIMARY,
                 font=FONT_CARD_BALANCE).pack(anchor="w")

        # 已消费金额：仅 DeepSeek 显示官方累计；其他服务商独立显示/无权限
        cost_line = tk.Frame(card, bg=COLOR_CARD)
        cost_line.pack(fill="x", padx=14, pady=(1, 0))
        is_deepseek = acc.get("provider") == "deepseek"
        if is_zhipu:
            if z_ok:
                cost_txt = "已消费：¥" + self.zhipu_data["data"].get("total_cost", "?")
            elif z_syncing:
                cost_txt = "已消费：同步中…"
            else:
                cost_txt = "已消费：——"
        elif is_siliconflow:
            if s_ok:
                cost_txt = "已消费：¥" + self.siliconflow_data["data"].get("total_cost", "?")
            elif s_syncing:
                cost_txt = "已消费：同步中…"
            else:
                cost_txt = "已消费：——"
        elif is_openrouter:
            od = getattr(self, "openrouter_data", None)
            if od and od.get("ok") and od["data"].get("total_cost") not in (None, ""):
                cost_txt = "已消费：$" + od["data"].get("total_cost", "?")
            elif res and res.get("ok"):
                used = ""
                for line in (res.get("lines") or []):
                    if "已使用" in line:
                        used = line.replace("已使用：", "")
                        break
                cost_txt = "已消费：$" + (used or "——")
            else:
                cost_txt = "已消费：——"
        elif is_deepseek and self.official_data and self.official_data.get("ok"):
            d = self.official_data["data"]
            cost_txt = f"已消费：¥{d.get('total_cost', '?')}"
        elif is_deepseek:
            # DeepSeek 未同步官方：引导同步
            cost_txt = "已消费：——"
        elif res and res.get("ok"):
            # Kimi：若已通过浏览器同步消费数据，显示真实已消费；否则引导同步
            if acc.get("provider") == "moonshot":
                if getattr(self, "kimi_data", None) and self.kimi_data.get("ok"):
                    cost_txt = "已消费：¥" + self.kimi_data["data"]["total_cost"]
                elif getattr(self, "_kimi_syncing", False):
                    cost_txt = "已消费：同步中…"
                else:
                    cost_txt = "已消费：——"
            else:
                used = ""
                for line in (res.get("lines") or []):
                    if "已使用" in line or "已消费" in line:
                        used = line
                        break
                cost_txt = "已消费：" + (used or "无权限查看")
        else:
            cost_txt = "已消费：——"
        tk.Label(cost_line, text=cost_txt, bg=COLOR_CARD, fg=COLOR_SUB,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")

        # 用量统计行：仅 DeepSeek 显示官方数据，其他服务商不套用
        stat_line = tk.Frame(card, bg=COLOR_CARD)
        stat_line.pack(fill="x", padx=14, pady=(1, 0))
        if is_zhipu:
            if z_ok:
                zd = self.zhipu_data["data"]
                today = zd.get("today_consume")
                if today is not None:
                    usage_txt = f"🌐 今日消费 ¥{today} · 累计 ¥{zd.get('total_cost', '?')}"
                else:
                    usage_txt = f"🌐 累计消费 ¥{zd.get('total_cost', '?')}"
            elif z_syncing:
                usage_txt = "正在同步智谱官方数据…"
            else:
                usage_txt = "📈 点击「🌐 同步官方」查看余额与消费"
        elif is_siliconflow:
            if s_ok:
                sd = self.siliconflow_data["data"]
                today = sd.get("today_consume")
                if today is not None:
                    usage_txt = f"🌐 今日消费 ¥{today} · 累计 ¥{sd.get('total_cost', '?')}"
                else:
                    usage_txt = f"🌐 累计消费 ¥{sd.get('total_cost', '?')}"
            elif s_syncing:
                usage_txt = "正在同步硅基流动官方数据…"
            else:
                usage_txt = "📈 点击「🌐 同步官方」查看余额与消费"
        elif is_openrouter:
            od = getattr(self, "openrouter_data", None)
            if od and od.get("ok"):
                d = od["data"]
                today = d.get("today_consume")
                if today is not None:
                    usage_txt = f"🌐 今日消费 ${today} · 累计 ${d.get('total_cost', '?')}"
                elif any(r.get("provider") == "openrouter" for r in (self.daily_data or [])):
                    usage_txt = f"🌐 累计消费 ${d.get('total_cost', '?')}"
                else:
                    usage_txt = "🌐 已同步官方 · 暂无用量记录"
            elif getattr(self, "_openrouter_syncing", False):
                usage_txt = "正在同步 OpenRouter 官方数据…"
            elif res and res.get("ok"):
                usage_txt = "📈 点击「🌐 同步官方」查看每日用量"
            else:
                usage_txt = "该服务商暂无用量统计权限"
        elif is_deepseek and self.official_data and self.official_data.get("ok"):
            # 不显示请求次数/Token（官网实时增长，软件是同步快照，无法一致）
            tstr = ""
            ts = self.official_data.get("synced_at")
            if ts:
                try:
                    tstr = "（更新于 " + datetime.datetime.fromtimestamp(ts).strftime("%H:%M") + "）"
                except Exception:  # noqa: BLE001
                    tstr = ""
            usage_txt = f"🌐 已同步官方{tstr}"
        elif is_deepseek:
            usage_txt = "📈 点击「🌐 同步官方」查看官方真实数据"
        elif res is None and acc:
            usage_txt = "正在连接服务器…"
        elif res and res.get("ok"):
            # 能查到用量数据就显示（DeepSeek=请求/Token，Kimi/智谱=消费金额），否则显示暂无权限
            if (acc.get("provider") == "moonshot" and getattr(self, "kimi_data", None)
                    and self.kimi_data.get("ok")):
                kd = self.kimi_data["data"]
                today = kd.get("today_consume")
                if today is not None:
                    usage_txt = f"🌐 今日消费 ¥{today} · 累计 ¥{kd.get('total_cost', '?')}"
                else:
                    usage_txt = f"🌐 累计消费 ¥{kd.get('total_cost', '?')}"
            else:
                usage_txt = "该服务商暂无用量统计权限"
        else:
            usage_txt = "——"
        tk.Label(stat_line, text=usage_txt, bg=COLOR_CARD, fg="#3b82f6",
                 font=FONT_SMALL, wraplength=470, justify="left").pack(anchor="w")

        # 明细行
        bot = tk.Frame(card, bg=COLOR_CARD)
        bot.pack(fill="x", padx=14, pady=(2, 10))
        if is_zhipu:
            if z_ok:
                zd = self.zhipu_data["data"]
                parts = []
                if zd.get("recharge") is not None:
                    parts.append(f"充值 ¥{zd['recharge']}")
                if zd.get("granted") is not None:
                    parts.append(f"赠送 ¥{zd['granted']}")
                detail = "  ·  ".join(parts) or "—"
            elif z_syncing:
                detail = "正在同步智谱官方数据…"
            else:
                detail = "余额与消费需点击「同步官方」查询"
        elif is_siliconflow:
            if s_ok:
                sd = self.siliconflow_data["data"]
                parts = []
                if sd.get("recharge") is not None:
                    parts.append(f"充值 ¥{sd['recharge']}")
                detail = "  ·  ".join(parts) or "—"
            elif s_syncing:
                detail = "正在同步硅基流动官方数据…"
            else:
                detail = "余额与消费需点击「同步官方」查询"
        elif res is None:
            detail = "正在连接服务器…"
        elif res.get("ok"):
            detail = "  ·  ".join(res.get("lines") or []) or "—"
        elif self._is_network_error(res):
            detail = "网络未连接，稍后自动重试"
        else:
            detail = res.get("error", "查询失败")
        tk.Label(bot, text=detail, bg=COLOR_CARD, fg=COLOR_SUB, font=FONT_SMALL,
                 wraplength=470, justify="left").pack(anchor="w")
        return card

    def _is_network_error(self, res):
        """判断查询结果是否为网络类错误（开机网络未就绪等），非账号本身问题。"""
        if not res:
            return False
        err = str(res.get("error", ""))
        return ("ConnectionError" in err or "无法连接服务器" in err
                or "Max retries" in err or "timeout" in err.lower()
                or "timed out" in err.lower())

    def _card_menu(self, event, acc):
        menu = tk.Menu(self.root, tearoff=0, font=FONT_NORMAL)
        menu.add_command(label="🔄 刷新此账号", command=lambda: self.refresh_one(acc))
        menu.add_command(label="✏️ 编辑", command=lambda: self.open_edit_dialog(acc))
        menu.add_separator()
        menu.add_command(label="🗑 删除", command=lambda: self.delete_account(acc))
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ 线程安全队列
    def _poll_queue(self):
        """主线程每 100ms 处理一次工作线程发来的任务。"""
        try:
            while True:
                job = self.ui_queue.get_nowait()
                job()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------ 刷新
    def refresh_all(self):
        if not self.accounts:
            self._update_status("还没有账号，点击下方按钮添加")
            return
        if self.refresh_lock.locked():
            self._update_status("正在刷新中，请稍候…")
            return
        self.refresh_lock.acquire()
        self._update_status("正在刷新…")
        for acc in self.accounts:
            self.results.pop(acc["id"], None)
        self._rebuild_list()
        threading.Thread(target=self._worker_all, daemon=True).start()

    def _worker_all(self):
        try:
            # 并行查询所有账号余额（账号多时避免串行导致「查询中」很久）
            threads = []
            for acc in self.accounts:
                def _query(a=acc):
                    res = providers.check_account(a["provider"], a["api_key"], a["base_url"])
                    self.ui_queue.put(lambda i=a["id"], r=res: self._finish_one(i, r))
                t = threading.Thread(target=_query, daemon=True)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
            self.ui_queue.put(self._finish_all)
        finally:
            self.refresh_lock.release()

    def refresh_one(self, acc):
        self.results[acc["id"]] = None
        self._rebuild_list()
        threading.Thread(target=self._worker_one, args=(acc,), daemon=True).start()

    def _worker_one(self, acc):
        res = providers.check_account(acc["provider"], acc["api_key"], acc["base_url"])
        self.ui_queue.put(lambda i=acc["id"], r=res: self._finish_one(i, r))
        self.ui_queue.put(self._finish_all)

    def _finish_one(self, acc_id, res):
        self.results[acc_id] = res
        # 立即重建该卡片，避免等 _finish_all 才显示、长时间停留在「查询中」
        try:
            self._update_card(acc_id)
        except Exception:  # noqa: BLE001
            pass

    def _finish_all(self):
        # 刷新全部完成后按所选排序方式重排（过程中保持稳定）
        self._apply_sort_order()
        self._rebuild_list()
        ok = sum(1 for r in self.results.values() if r and r.get("ok"))
        if self.last_update:
            self._update_status(
                f"共 {len(self.accounts)} 个账号 · 正常 {ok} 个 · 上次更新 {self.last_update}")
        else:
            self._update_status(f"共 {len(self.accounts)} 个账号 · 正常 {ok} 个")
        # 自动后台同步 Kimi（存在 Kimi 账号且未同步时），无需手动点同步官方
        if (any(a.get("provider") == "moonshot" for a in self.accounts)
                and self.kimi_data is None and not getattr(self, "_kimi_syncing", False)):
            threading.Thread(target=self._worker_kimi_sync, daemon=True).start()
        # 智谱同理
        if (any(a.get("provider") == "zhipu" for a in self.accounts)
                and self.zhipu_data is None and not getattr(self, "_zhipu_syncing", False)):
            threading.Thread(target=self._worker_zhipu_sync, daemon=True).start()
        # 硅基流动同理
        if (any(a.get("provider") == "siliconflow" for a in self.accounts)
                and self.siliconflow_data is None
                and not getattr(self, "_siliconflow_syncing", False)):
            threading.Thread(target=self._worker_siliconflow_sync, daemon=True).start()
        # OpenRouter 同理（每日用量浏览器同步）
        if (any(a.get("provider") == "openrouter" for a in self.accounts)
                and self.openrouter_data is None
                and not getattr(self, "_openrouter_syncing", False)):
            threading.Thread(target=self._worker_openrouter_sync, daemon=True).start()
        self._check_alert()
        # 开机网络未就绪：有网络错误账号时延迟自动重试（最多 3 次），避免一开机全是红叉
        if any(self._is_network_error(self.results.get(a["id"])) for a in self.accounts):
            n = getattr(self, "_net_retry", 0)
            if n < 3:
                self._net_retry = n + 1
                self.root.after(8000, self.refresh_all)

    # ------------------------------------------------------------------ 官方同步
    def sync_official(self):
        if getattr(self, "_syncing", False):
            self._update_status("正在同步官方数据，请稍候…")
            return
        self._syncing = True
        self._update_status("🌐 正在同步 DeepSeek 官方数据…")
        threading.Thread(target=self._worker_sync, daemon=True).start()

    def _worker_sync(self):
        out = {}

        def _run_usage():
            try:
                out["usage"] = browser_sync.fetch_deepseek_usage(headless=True, timeout=90)
            except Exception as e:
                out["usage"] = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}

        def _run_daily():
            try:
                d = browser_sync.fetch_deepseek_daily(headless=True, timeout=60)
                out["daily"] = d.get("data") if d.get("ok") else None
            except Exception:
                out["daily"] = None

        # 概览、逐日、Kimi、智谱、硅基流动、OpenRouter 同步并行启动；谁先完成谁先更新对应卡片，互不拖慢
        has_kimi = any(a.get("provider") == "moonshot" for a in self.accounts)
        has_zhipu = any(a.get("provider") == "zhipu" for a in self.accounts)
        has_sf = any(a.get("provider") == "siliconflow" for a in self.accounts)
        has_or = any(a.get("provider") == "openrouter" for a in self.accounts)
        t1 = threading.Thread(target=_run_usage, daemon=True)
        t2 = threading.Thread(target=_run_daily, daemon=True)
        t3 = threading.Thread(target=self._worker_kimi_sync, daemon=True)
        t4 = threading.Thread(target=self._worker_zhipu_sync, daemon=True)
        t5 = threading.Thread(target=self._worker_siliconflow_sync, daemon=True)
        t6 = threading.Thread(target=self._worker_openrouter_sync, daemon=True)
        t1.start()
        t2.start()
        if has_kimi:
            t3.start()   # Kimi 同步立即并行，不再等 DeepSeek 完成后才开始
        if has_zhipu:
            t4.start()   # 智谱同步同样并行
        if has_sf:
            t5.start()   # 硅基流动同步同样并行
        if has_or:
            t6.start()   # OpenRouter 同步同样并行
        # ① 用量完成即先更新（不等待逐日 / Kimi），快的先显示
        t1.join()
        r = out.get("usage") or {"ok": False, "error": "同步失败"}
        # 后台刷新官方页面 Token 缓存（累计口径），保持下次同步准确（不阻塞主流程）
        if r.get("ok"):
            threading.Thread(target=self._refresh_page_tokens_bg, args=(r,), daemon=True).start()
        self._syncing = False
        self.ui_queue.put(lambda rr=r: self._finish_sync(rr, None))
        # ② 逐日数据完成：更新缓存与日历
        t2.join()
        if out.get("daily"):
            self.ui_queue.put(lambda dd=out["daily"]: self._daily_synced(dd))
        # ③ Kimi / 智谱 / 硅基流动 / OpenRouter 同步完成：各自已入队 _finish_*
        if has_kimi:
            t3.join()
        if has_zhipu:
            t4.join()
        if has_sf:
            t5.join()
        if has_or:
            t6.join()
        # 所有同步完成后按最新数据重排一次（同步过程中不重排，避免中间态乱序）
        self.ui_queue.put(self._apply_sort_after_sync)

    def _apply_sort_after_sync(self):
        """同步官方全部完成后按最新数据重排一次（过程中保持稳定）。"""
        if getattr(self, "_sort_mode", ""):
            self._apply_sort_order()
            self._rebuild_list()

    def _worker_kimi_sync(self):
        self._kimi_syncing = True
        daily = []
        try:
            # 浏览器 profile 全局串行：Kimi 与智谱/DeepSeek 不能同时开浏览器
            with browser_sync._BROWSER_LOCK:
                r = kimi_sync.fetch_kimi_usage_daily(headless=True, timeout=90)
            k = {"ok": bool(r.get("ok")), "data": r.get("data") or {},
                 "error": r.get("error") or ""}
            daily = r.get("daily") or []
        except Exception as e:  # noqa: BLE001
            k = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        self.ui_queue.put(lambda kk=k, dd=daily: self._finish_kimi(kk, dd))

    def _finish_kimi(self, k, daily=None):
        self._kimi_syncing = False
        self.kimi_data = k
        self._save_kimi_cache()
        if daily:
            self._merge_daily(daily)
            if getattr(self, "_cal_win", None):
                try:
                    self._render_calendar()
                except Exception:  # noqa: BLE001
                    pass
        for acc in self.accounts:
            if acc.get("provider") == "moonshot":
                self._update_card(acc["id"])
        self._check_alert()

    def _worker_zhipu_sync(self):
        self._zhipu_syncing = True
        daily = []
        try:
            # 浏览器 profile 全局串行：与 Kimi/DeepSeek 不能同时开浏览器
            with browser_sync._BROWSER_LOCK:
                r = zhipu_sync.fetch_zhipu_usage_daily(headless=True, timeout=90)
            z = {"ok": bool(r.get("ok")), "data": r.get("data") or {},
                 "error": r.get("error") or ""}
            daily = r.get("daily") or []
        except Exception as e:  # noqa: BLE001
            z = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        self.ui_queue.put(lambda zz=z, dd=daily: self._finish_zhipu(zz, dd))

    def _finish_zhipu(self, z, daily=None):
        self._zhipu_syncing = False
        self.zhipu_data = z
        self._save_zhipu_cache()
        if daily:
            self._merge_daily(daily)
            if getattr(self, "_cal_win", None):
                try:
                    self._render_calendar()
                except Exception:  # noqa: BLE001
                    pass
        for acc in self.accounts:
            if acc.get("provider") == "zhipu":
                self._update_card(acc["id"])
        self._check_alert()

    def _worker_siliconflow_sync(self):
        self._siliconflow_syncing = True
        daily = []
        try:
            # 浏览器 profile 全局串行：与 Kimi/智谱/DeepSeek 不能同时开浏览器
            with browser_sync._BROWSER_LOCK:
                r = siliconflow_sync.fetch_siliconflow_usage_daily(headless=True, timeout=90)
            s = {"ok": bool(r.get("ok")), "data": r.get("data") or {},
                 "error": r.get("error") or ""}
            daily = r.get("daily") or []
        except Exception as e:  # noqa: BLE001
            s = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        self.ui_queue.put(lambda ss=s, dd=daily: self._finish_siliconflow(ss, dd))

    def _finish_siliconflow(self, s, daily=None):
        self._siliconflow_syncing = False
        self.siliconflow_data = s
        self._save_siliconflow_cache()
        if daily:
            self._merge_daily(daily)
            if getattr(self, "_cal_win", None):
                try:
                    self._render_calendar()
                except Exception:  # noqa: BLE001
                    pass
        for acc in self.accounts:
            if acc.get("provider") == "siliconflow":
                self._update_card(acc["id"])
        self._check_alert()

    def _worker_openrouter_sync(self):
        self._openrouter_syncing = True
        daily = []
        api_key = next((a.get("api_key", "") for a in self.accounts
                        if a.get("provider") == "openrouter"), "")
        try:
            # 浏览器 profile 全局串行：与 Kimi/智谱/硅基流动/DeepSeek 不能同时开浏览器
            with browser_sync._BROWSER_LOCK:
                r = openrouter_sync.fetch_openrouter_usage_daily(api_key, headless=True, timeout=90)
            o = {"ok": bool(r.get("ok")), "data": r.get("data") or {},
                 "error": r.get("error") or ""}
            daily = r.get("daily") or []
        except Exception as e:  # noqa: BLE001
            o = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        self.ui_queue.put(lambda oo=o, dd=daily: self._finish_openrouter(oo, dd))

    def _finish_openrouter(self, o, daily=None):
        self._openrouter_syncing = False
        self.openrouter_data = o
        self._save_openrouter_cache()
        if daily:
            self._merge_daily(daily)
            if getattr(self, "_cal_win", None):
                try:
                    self._render_calendar()
                except Exception:  # noqa: BLE001
                    pass
        for acc in self.accounts:
            if acc.get("provider") == "openrouter":
                self._update_card(acc["id"])
        self._check_alert()

    def _refresh_page_tokens_bg(self, r):
        try:
            new_tok = browser_sync._fetch_page_tokens(headless=True, timeout=60)
            changed = False
            if new_tok is not None and r.get("ok") and r.get("data"):
                r["data"]["tokens"] = str(new_tok)
                changed = True
            # 请求次数同样以官方页面统计卡为准
            new_req = browser_sync._page_requests_cached()
            if new_req is not None and r.get("ok") and r.get("data"):
                r["data"]["requests"] = str(new_req)
                changed = True
            if changed:
                r["synced_at"] = time.time()
                self.ui_queue.put(self._refresh_deepseek_card)
        except Exception:  # noqa: BLE001
            pass

    def _refresh_deepseek_card(self):
        """主线程：按最新页面值重建 DeepSeek 卡片（同步官方后立即刷新显示）。"""
        for acc in self.accounts:
            if acc.get("provider") == "deepseek":
                try:
                    self._update_card(acc["id"])
                except Exception:  # noqa: BLE001
                    pass

    def _finish_sync(self, result, daily=None):
        if isinstance(result, dict):
            result["synced_at"] = time.time()   # 记录同步时刻，让数据透明（官网是实时的）
        self.official_data = result
        if daily is not None:
            self.daily_data = daily
            self._save_daily_cache()
        # 同步完成只重建受影响卡片（DeepSeek/Kimi 局部更新），避免整屏闪烁
        for acc in self.accounts:
            if acc.get("provider") in ("deepseek", "moonshot"):
                self._update_card(acc["id"])
        if daily and getattr(self, "_cal_win", None):
            try:
                self._render_calendar()
            except Exception:  # noqa: BLE001
                pass
        if result.get("ok"):
            d = result["data"]
            status = (f"✅ 官方同步：余额 ¥{d.get('balance','?')} · 消费 ¥{d.get('total_cost','?')} · "
                      f"请求 {d.get('requests','?')} 次 · Token {int(float(d.get('tokens',0))):,}")
            self._update_status(status)
            self._check_alert()
        else:
            if result.get("need_login"):
                self._update_status("🔑 请在弹出的浏览器中登录 DeepSeek 后重试")
            else:
                self._update_status(f"⚠️ 同步失败：{result.get('error','未知')[:60]}")

    # ------------------------------------------------------------------ 每日数据缓存
    def _save_daily_cache(self):
        if not self.daily_data:
            return
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "daily_cache.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.daily_data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_daily_cache(self):
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "daily_cache.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data:
                self.daily_data = data
                return True
        except Exception:
            pass
        return False

    def _save_kimi_cache(self):
        if not self.kimi_data:
            return
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "kimi_cache.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.kimi_data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_kimi_cache(self):
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "kimi_cache.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data and data.get("ok"):
                return data
        except Exception:
            pass
        return None

    def _save_zhipu_cache(self):
        if not self.zhipu_data:
            return
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "zhipu_cache.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.zhipu_data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_zhipu_cache(self):
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "zhipu_cache.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data and data.get("ok"):
                return data
        except Exception:
            pass
        return None

    def _save_siliconflow_cache(self):
        if not self.siliconflow_data:
            return
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "siliconflow_cache.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.siliconflow_data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_siliconflow_cache(self):
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "siliconflow_cache.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data and data.get("ok"):
                return data
        except Exception:
            pass
        return None

    def _save_openrouter_cache(self):
        if not self.openrouter_data:
            return
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "openrouter_cache.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.openrouter_data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load_openrouter_cache(self):
        try:
            path = os.path.join(os.path.expanduser("~"), ".model_balance", "openrouter_cache.json")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data and data.get("ok"):
                return data
        except Exception:
            pass
        return None

    def _check_alert(self):
        """余额预警：主账号余额低于阈值时弹窗。"""
        threshold = self._alert_threshold_for()
        if threshold <= 0:
            return
        bal = self._master_balance()
        if bal is None:
            return
        if bal < threshold:
            master = self._get_master()
            mname = master.get("name") if master else "?"
            messagebox.showwarning(
                "余额预警",
                f"主账号「{mname}」当前余额 ¥{bal:.2f} 已低于预警阈值 ¥{threshold:.2f}！\n请及时充值，避免影响使用。",
                parent=self.root,
            )

    # ------------------------------------------------------------------ 主账号
    def _get_master(self):
        """返回当前主账号的账号 dict；未设置返回 None。"""
        if not self._master_id:
            return None
        for a in self.accounts:
            if a.get("id") == self._master_id:
                return a
        return None

    def _master_label(self):
        """主账号按钮文字。"""
        m = self._get_master()
        if not m:
            return "主账号 ▾"
        # 只显示账号名；没起名字时才用服务商短名，不显示服务商全名/模型名
        nm = m.get("name") or _provider_short_name(m.get("provider"))
        if self._master_api and m.get("provider") == "deepseek":
            nm = f"{nm}·{self._master_api}"
        return "主账号 ▾ " + nm

    def _alert_threshold_for(self):
        """当前主账号的预警阈值。"""
        if not self._master_id:
            return 0.0
        return float(self._alerts.get(self._master_id, 0) or 0)

    def _master_balance(self):
        """主账号当前余额（DeepSeek 走官方页面、Kimi 走浏览器同步、其他走余额接口）。"""
        m = self._get_master()
        if not m:
            return None
        p = m.get("provider")
        if p == "deepseek" and self.official_data and self.official_data.get("ok"):
            try:
                return float(self.official_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                return None
        if p == "moonshot" and self.kimi_data and self.kimi_data.get("ok"):
            try:
                return float(self.kimi_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                return None
        if p == "zhipu" and getattr(self, "zhipu_data", None) and self.zhipu_data.get("ok"):
            try:
                return float(self.zhipu_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                return None
        if p == "siliconflow" and getattr(self, "siliconflow_data", None) and self.siliconflow_data.get("ok"):
            try:
                return float(self.siliconflow_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                return None
        if p == "openrouter" and getattr(self, "openrouter_data", None) and self.openrouter_data.get("ok"):
            try:
                return float(self.openrouter_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                return None
        res = self.results.get(m["id"])
        if res and res.get("ok"):
            try:
                return float(res.get("value"))
            except (TypeError, ValueError):
                return None
        return None

    def _filtered_daily(self):
        """每日用量按主账号过滤：DeepSeek 按账号名称匹配到具体 API Key；
        Kimi 为组织级每日账单；其他服务商暂无数据，不误显示别的模型数据。"""
        m = self._get_master()
        all_recs = self.daily_data or []
        if not m:
            return all_recs
        p = m.get("provider")
        if p == "deepseek":
            nm = (m.get("name") or "").strip()
            ds = [r for r in all_recs if (r.get("provider") or "deepseek") == "deepseek"]
            if nm:
                f = [r for r in ds if r.get("name") == nm]
                if f:
                    return f
            return ds
        if p == "moonshot":
            return [r for r in all_recs if r.get("provider") == "moonshot"]
        if p == "zhipu":
            return [r for r in all_recs if r.get("provider") == "zhipu"]
        if p == "siliconflow":
            return [r for r in all_recs if r.get("provider") == "siliconflow"]
        if p == "openrouter":
            return [r for r in all_recs if r.get("provider") == "openrouter"]
        return []

    def _update_master_ui(self):
        """切换主账号后刷新按钮文字与界面。"""
        if getattr(self, "master_btn", None):
            self.master_btn.set_text(self._master_label())
        self._rebuild_list()
        if getattr(self, "_cal_win", None):
            try:
                self._render_calendar()
            except Exception:  # noqa: BLE001
                pass
        self._check_alert()

    def open_master_dialog(self):
        if not self.accounts:
            messagebox.showinfo("提示", "请先点击「＋ 添加账号」添加账号", parent=self.root)
            return
        MasterDialog(self.root, self)

    # ------------------------------------------------------------------ 每日用量
    # ------------------------------------------------------------------ 每日用量(日历)
    def show_daily(self):
        """每日用量统一为日历形式：不管主账号是哪家，界面都与 DeepSeek 主账号一致。
        数据按主账号过滤。Kimi 主账号若无每日账单，后台同步一次（不阻塞显示）。"""
        if not self.daily_data:
            if not self._load_daily_cache():
                self._ensure_daily_sync()
        master = self._get_master()
        if master and master.get("provider") == "moonshot":
            has_kd = any(r.get("provider") == "moonshot" for r in (self.daily_data or []))
            if not has_kd and not getattr(self, "_kimi_syncing", False):
                threading.Thread(target=self._worker_kimi_sync, daemon=True).start()
        elif master and master.get("provider") == "zhipu":
            has_kd = any(r.get("provider") == "zhipu" for r in (self.daily_data or []))
            if not has_kd and not getattr(self, "_zhipu_syncing", False):
                threading.Thread(target=self._worker_zhipu_sync, daemon=True).start()
        elif master and master.get("provider") == "siliconflow":
            has_kd = any(r.get("provider") == "siliconflow" for r in (self.daily_data or []))
            if not has_kd and not getattr(self, "_siliconflow_syncing", False):
                threading.Thread(target=self._worker_siliconflow_sync, daemon=True).start()
        elif master and master.get("provider") == "openrouter":
            has_kd = any(r.get("provider") == "openrouter" for r in (self.daily_data or []))
            if not has_kd and not getattr(self, "_openrouter_syncing", False):
                threading.Thread(target=self._worker_openrouter_sync, daemon=True).start()
        win = tk.Toplevel(self.root)
        win.title("每日用量")
        win.geometry("580x520")
        win.configure(bg=COLOR_BG)
        self._cal_win = win
        self._cal_year = datetime.date.today().year
        self._cal_month = datetime.date.today().month
        self._render_calendar()

    def _ensure_daily_sync(self):
        if getattr(self, "_daily_syncing", False):
            return
        self._daily_syncing = True

        def worker():
            try:
                d = browser_sync.fetch_deepseek_daily(headless=True, timeout=60)
                data = d.get("data") if d.get("ok") else None
            except Exception:
                data = None
            self._daily_syncing = False
            self.ui_queue.put(lambda dd=data: self._daily_synced(dd))

        threading.Thread(target=worker, daemon=True).start()

    def _merge_daily(self, records):
        """把一批逐日记录合并进 daily_data（按 provider+name+date 去重），并落盘。"""
        if not records:
            return

        def _key(r):
            return (r.get("provider") or "deepseek", r.get("name") or "", r["date"])

        merged = {_key(r): r for r in (self.daily_data or [])}
        for r in records:
            merged[_key(r)] = r
        self.daily_data = list(merged.values())
        self._save_daily_cache()

    def _daily_synced(self, data):
        if data:
            self._merge_daily(data)
            if getattr(self, "_cal_win", None):
                self._render_calendar()

    def _render_calendar(self):
        win = self._cal_win
        for w in win.winfo_children():
            w.destroy()
        filtered = self._filtered_daily()
        daily_map = {r["date"]: r for r in filtered}
        today = datetime.date.today()

        # 顶部：当前主账号信息（名称 + 余额），统一各服务商入口视觉
        master = self._get_master()
        if master:
            mname = master.get("name") or _provider_id_to_name(master.get("provider"))
            bal = self._master_balance()
            extra = f" · 余额 ¥{bal:.2f}" if bal is not None else ""
            tk.Label(win, text=f"主账号：{mname}{extra}", bg=COLOR_BG,
                     fg=COLOR_TEXT, font=FONT_SMALL).pack(pady=(8, 0))

        head = tk.Frame(win, bg=COLOR_BG)
        head.pack(fill="x", pady=(10, 4))
        ios_ui.iOSButton(head, "◀ 上月", lambda: self._cal_shift(-1), color=ios_ui.BTN_GRAY, fg=ios_ui.BTN_GRAY_FG,
                         width=78, height=30, font_size=9).pack(side="left", padx=12)
        tk.Label(head, text=f"{self._cal_year} 年 {self._cal_month} 月", bg=COLOR_BG,
                 fg=COLOR_TEXT, font=FONT_CARD_NAME).pack(side="left", expand=True)
        ios_ui.iOSButton(head, "下月 ▶", lambda: self._cal_shift(1), color=ios_ui.BTN_GRAY, fg=ios_ui.BTN_GRAY_FG,
                         width=78, height=30, font_size=9).pack(side="right", padx=12)

        # 日期跳转（立体滚轮）
        tj = tk.Frame(win, bg=COLOR_BG)
        tj.pack(pady=(0, 6))
        ios_ui.iOSButton(tj, "日期跳转", self.open_date_wheel, color=ios_ui.SYNC_BG, fg=ios_ui.SYNC_FG,
                         width=92, height=32, font_size=10).pack()
        win.bind("<MouseWheel>", lambda e: self._cal_shift(1 if e.delta > 0 else -1))

        cal_frame = tk.Frame(win, bg=COLOR_BG)
        cal_frame.pack()
        for i, w in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            tk.Label(cal_frame, text=w, bg=COLOR_BG, fg=COLOR_SUB,
                     font=FONT_SMALL).grid(row=0, column=i, padx=6, pady=4)

        cal = calendar.Calendar(firstweekday=0)
        row = 1
        for dt in cal.itermonthdates(self._cal_year, self._cal_month):
            if dt.month != self._cal_month:
                continue
            col = dt.weekday()
            date_str = dt.isoformat()
            rec = daily_map.get(date_str)
            has_usage = bool(rec and (rec["tokens"] > 0 or rec["cost"] > 0))
            is_today = dt == today
            if is_today:
                bg, fg = "#f97316", "#ffffff"
            elif has_usage:
                bg, fg = "#ffffff", COLOR_TEXT
            else:
                bg, fg = "#e5e7eb", COLOR_SUB  # 无数据/未来:灰
            cell = tk.Frame(cal_frame, width=58, height=52, bg=bg,
                            highlightbackground=COLOR_BORDER, highlightthickness=1)
            cell.grid(row=row, column=col, padx=2, pady=2)
            cell.grid_propagate(False)
            tk.Label(cell, text=str(dt.day), bg=bg, fg=fg,
                     font=FONT_NORMAL).pack(pady=(2, 0))
            if has_usage:
                cost_color = "#16a34a" if rec["cost"] < 1 else "#dc2626"
                tk.Label(cell, text=f"¥{rec['cost']:.2f}", bg=bg, fg=cost_color,
                         font=("Microsoft YaHei UI", 7)).pack()
                if not is_today:
                    cmd = lambda e, ds=date_str: self.show_day_detail(ds)
                    cell.bind("<Button-1>", cmd)
                    for _ch in cell.winfo_children():
                        _ch.bind("<Button-1>", cmd)
                    cell.configure(cursor="hand2")
            if col == 6:
                row += 1

        total_cost = sum(r["cost"] for r in filtered)
        total_tok = sum(r["tokens"] for r in filtered)
        if filtered:
            tk.Label(win, text=f"合计：¥{total_cost:.2f} · Token {total_tok:,}",
                     bg=COLOR_BG, fg=COLOR_TEXT, font=FONT_SMALL).pack(pady=(8, 6))
        else:
            if master and master.get("provider") == "moonshot":
                tip = "该主账号暂无消费记录（Kimi 日账单于次日上午更新）"
            elif master and master.get("provider") == "zhipu":
                tip = "该主账号暂无消费记录（智谱无消费时按日账单为空）"
            elif master and master.get("provider") == "openrouter":
                tip = "该主账号暂无消费记录（OpenRouter 无用量时 analytics 为空）"
            elif master and master.get("provider") == "siliconflow":
                tip = "该主账号暂无消费记录（硅基流动无消费时按日账单为空）"
            else:
                tip = "该主账号暂无逐日用量数据"
            tk.Label(win, text=tip, bg=COLOR_BG, fg=COLOR_SUB,
                     font=FONT_SMALL).pack(pady=(8, 6))

    def _cal_shift(self, delta):
        m = self._cal_month + delta
        y = self._cal_year
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self._cal_month = m
        self._cal_year = y
        need = f"{y:04d}-{m:02d}"
        has_month = any(r["date"].startswith(need) for r in self._filtered_daily())
        if not has_month:
            self._ensure_month_data(y, m)
        self._render_calendar()

    def _draw_badge(self):
        """绘制立体圆形日期徽章（渐变球体，中心显示年月）。"""
        c = self._badge
        c.delete("all")
        w, h = 130, 88
        cx, cy, r = w // 2, h // 2 + 4, 34
        # 底部阴影
        c.create_oval(cx - r - 3, cy - r + 4, cx + r + 3, cy + r + 4,
                      fill="#d1d5db", outline="")
        # 渐变球体（多层椭圆近似立体）
        for i in range(12, -1, -1):
            rr = r * (i / 12)
            g = 90 + int(120 * (i / 12))
            b = 150 + int(105 * (i / 12))
            color = "#%02x%02x%02x" % (37, g, b)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=color, outline="")
        # 高光
        c.create_oval(cx - r * 0.45, cy - r * 0.85, cx + r * 0.45, cy + r * 0.05,
                      fill="#ffffff", outline="", stipple="gray50")
        c.create_text(cx, cy - 8, text=f"{self._cal_year}年", fill="#ffffff",
                      font=("Microsoft YaHei UI", 10, "bold"))
        c.create_text(cx, cy + 12, text=f"{self._cal_month}月", fill="#ffffff",
                      font=("Microsoft YaHei UI", 13, "bold"))

    def _jump_to(self):
        try:
            y = int(self._j_y.get())
            m = int(self._j_m.get())
            d = int(self._j_d.get())
        except ValueError:
            messagebox.showinfo("提示", "请输入有效年月日", parent=self.root)
            return
        if not (1 <= m <= 12 and 1 <= d <= 31):
            messagebox.showinfo("提示", "月份 1-12，日期 1-31", parent=self.root)
            return
        self._cal_year = y
        self._cal_month = m
        need = f"{y:04d}-{m:02d}"
        if not any(r["date"].startswith(need) for r in self._filtered_daily()):
            self._ensure_month_data(y, m)
        self._render_calendar()
        date_str = f"{y:04d}-{m:02d}-{d:02d}"
        if any(r["date"] == date_str for r in self._filtered_daily()):
            self.show_day_detail(date_str)

    def open_date_wheel(self):
        """惯性顺滑滚轮日期选择器：滚动带物理动画、滑动过渡、边界回弹。"""
        # ===== 调试参数（可自行调整） =====
        ANIM_MS = 8           # 动画帧间隔(毫秒)，约120fps
        FRICTION = 0.86       # 惯性衰减系数(0~1)，越小减速越快
        VELOCITY_STEP = 0.35  # 每次滚轮注入的速度量，越小滚动越缓
        SNAP_FACTOR = 0.35    # 缓出吸附到最近整项的速率
        ITEM_SPACING = 56     # 相邻项垂直间距(像素)，模仿 iOS 计时器
        LINE_GAP = 12         # 两条横线距中心距离(只框住选中的一个数字)
        CENTER_Y = 200        # 滚轮中心 y
        ARC_RADIUS = 70       # 圆弧半径(弧度立体感)，越小弧度越大
        ARC_ANGLE = 0.20      # 每项对应角度(弧度)
        # =================================

        win = tk.Toplevel(self.root)
        win.title("日期跳转")
        win.geometry("380x560")   # 高度留足，避免底部「确定/取消」按钮文字被裁剪
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        today = datetime.date.today()

        y_min, y_max = 2020, 2100
        wheels = [
            {"label": "年", "values": list(range(y_min, y_max + 1)), "x": 80,
             "offset": 0.0, "target": 0.0, "circular": False},
            {"label": "月", "values": list(range(1, 13)), "x": 190,
             "offset": 0.0, "target": 0.0, "circular": False},
            {"label": "日", "values": list(range(1, 29)), "x": 300,
             "offset": 0.0, "target": 0.0, "circular": False},
        ]
        # 每次打开默认定位到当天（而非当月第一天）
        for w in wheels:
            cur = (today.year if w["label"] == "年"
                   else today.month if w["label"] == "月" else today.day)
            try:
                w["sel"] = w["values"].index(cur)
            except ValueError:
                w["sel"] = 0

        c = tk.Canvas(win, width=360, height=440, bg="#ffffff", highlightthickness=0)
        c.pack(pady=(12, 2))

        preview = tk.StringVar()
        tk.Label(win, textvariable=preview, bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Microsoft YaHei UI", 12, "bold")).pack(pady=(0, 4))

        _last_ym = [None, None]

        def _update_preview():
            y = wheels[0]["values"][wheels[0]["sel"]]
            m = wheels[1]["values"][wheels[1]["sel"]]
            # 年月变化时，日滚轮按公历动态调整(含闰年2月29、小月30等)
            if _last_ym != [y, m]:
                n = calendar.monthrange(y, m)[1]
                wheels[2]["values"] = list(range(1, n + 1))
                if wheels[2]["sel"] >= n:
                    wheels[2]["sel"] = n - 1
                _last_ym[:] = [y, m]
            d = wheels[2]["values"][wheels[2]["sel"]]
            preview.set(f"{y}年 {m}月 {d}日")

        # 每帧按 offset 插值绘制 → 实现滑动过渡(不瞬间跳变)
        # PIL 渲染数字(支持横向压缩 scaleX + 字号 + 亮度 三联动)
        _font_path = "C:/Windows/Fonts/arialbd.ttf"
        _photo_cache = {}

        def _text_img(val, size, scaleX, gray):
            key = (val, int(size), int(scaleX * 20), int(gray / 15))
            if key in _photo_cache:
                return _photo_cache[key]
            try:
                font = ImageFont.truetype(_font_path, max(5, size))
            except Exception:
                font = ImageFont.load_default()
            tmp = PILImage.new("RGBA", (10, 10), (0, 0, 0, 0))
            dd = ImageDraw.Draw(tmp)
            bbox = dd.textbbox((0, 0), val, font=font)
            w = max(1, bbox[2] - bbox[0])
            h = max(1, bbox[3] - bbox[1])
            nw = max(2, int(w * scaleX))
            img = PILImage.new("RGBA", (nw + 2, h + 2), (0, 0, 0, 0))
            dd = ImageDraw.Draw(img)
            dd.text((-bbox[0], -bbox[1]), val, font=font, fill=(gray, gray, gray, 255))
            if scaleX < 0.97:
                img = img.resize((nw + 2, h + 2), PILImage.LANCZOS)  # 横向压扁
            tk_img = ImageTk.PhotoImage(img)
            _photo_cache[key] = tk_img
            if len(_photo_cache) > 400:
                _photo_cache.clear()
            return tk_img

        def _draw():
            c.delete("all")
            for w in wheels:
                n = len(w["values"])
                for i in range(-4, 5):
                    raw = w["sel"] + i
                    if not w["circular"] and (raw < 0 or raw >= n):
                        continue
                    idx = raw % n
                    val = w["values"][idx]
                    dist = i + w["offset"]
                    # 垂直间距固定不变，仅横向 scaleX 压缩（iOS 圆柱透视）
                    yy = CENTER_Y + dist * ITEM_SPACING
                    xx = w["x"]
                    d = abs(dist)
                    scaleX = max(0.75, 1 - 0.05 * d)          # 最远 scaleX 下限 0.75
                    size = max(9, int(24 * max(0.42, 1 - 0.10 * d)))
                    gray = min(215, int(0 + 40 * d))           # 选中黑，远端浅灰(更强立体对比)
                    img = _text_img(str(val), size, scaleX, gray)
                    c.create_image(xx, yy, image=img)
                c.create_text(w["x"], 14, text=w["label"],
                              font=("Microsoft YaHei UI", 10, "bold"), fill="#555555")
            # 选中框(浅灰细线)：整数像素宽，避免 GDI 小数线宽渲染模糊/毛边
            c.create_line(30, CENTER_Y - LINE_GAP, 330, CENTER_Y - LINE_GAP, fill="#c8c8cc", width=2)
            c.create_line(30, CENTER_Y + LINE_GAP, 330, CENTER_Y + LINE_GAP, fill="#c8c8cc", width=2)
            # 上下白色渐变遮罩层(白底，盖在数字上层)
            mask = PILImage.new("RGBA", (360, 440), (0, 0, 0, 0))
            md = ImageDraw.Draw(mask)
            for y in range(70):
                a = int(220 * (1 - y / 70) ** 1.5)
                md.line([(0, y), (360, y)], fill=(255, 255, 255, a))
                md.line([(0, 439 - y), (360, 439 - y)], fill=(255, 255, 255, a))
            self._mask_img = ImageTk.PhotoImage(mask)
            c.create_image(180, 220, image=self._mask_img)

        # 动画主循环：惯性减速 + 缓出吸附 + 跨项 + 边界回弹
        def _tick():
            for w in wheels:
                n = len(w["values"])
                # 缓动逼近目标：offset 平滑经过小数中间值(滑动过程)
                diff = w["target"] - w["offset"]
                if abs(diff) > 0.01:
                    w["offset"] += diff * SNAP_FACTOR
                else:
                    w["offset"] = float(w["target"])
                # 跨项切换(滑动越过一格时换值)
                while w["offset"] >= 1:
                    if not w["circular"] and w["sel"] <= 0:
                        w["target"] = 0                    # 顶部边界回弹
                        w["offset"] += (0 - w["offset"]) * 0.5
                        break
                    w["sel"] = (w["sel"] - 1) % n
                    w["offset"] -= 1
                    w["target"] -= 1
                while w["offset"] <= -1:
                    if not w["circular"] and w["sel"] >= n - 1:
                        w["target"] = 0                    # 底部边界回弹
                        w["offset"] += (0 - w["offset"]) * 0.5
                        break
                    w["sel"] = (w["sel"] + 1) % n
                    w["offset"] += 1
                    w["target"] += 1
            _draw()
            _update_preview()
            c.after(ANIM_MS, _tick)   # 持续动画循环，滚动时立即响应

        # 滚轮事件：累积速度(节流缓冲)，不瞬时改值
        def _on_wheel(e):
            for w in wheels:
                if abs(e.x - w["x"]) < 42:
                    # 一次滚轮目标移动一个数字，动画平滑滑动过渡
                    w["target"] += (1 if e.delta > 0 else -1)
                    break

        c.bind("<MouseWheel>", _on_wheel)
        _draw()
        _update_preview()
        c.after(ANIM_MS, _tick)

        btns = tk.Frame(win, bg=COLOR_BG)
        btns.pack(pady=(0, 12))

        def _ok():
            y = wheels[0]["values"][wheels[0]["sel"]]
            m = wheels[1]["values"][wheels[1]["sel"]]
            d = wheels[2]["values"][wheels[2]["sel"]]
            self._cal_year = y
            self._cal_month = m
            need = f"{y:04d}-{m:02d}"
            if not any(r["date"].startswith(need) for r in self._filtered_daily()):
                self._ensure_month_data(y, m)
            self._render_calendar()
            date_str = f"{y:04d}-{m:02d}-{d:02d}"
            if any(r["date"] == date_str for r in self._filtered_daily()):
                self.show_day_detail(date_str)
            win.destroy()

        ios_ui.iOSButton(btns, "确定", _ok, color=COLOR_PRIMARY,
                         width=88, height=34, font_size=11).pack(side="left", padx=12)
        ios_ui.iOSButton(btns, "取消", win.destroy, color=ios_ui.BTN_GRAY, fg=ios_ui.BTN_GRAY_FG,
                         width=88, height=34, font_size=11).pack(side="left", padx=12)

    def _ensure_month_data(self, year, month):
        """日历切月：按主账号服务商抓该月逐日数据（DeepSeek 走接口，智谱走日账单）。"""
        master = self._get_master()
        if master and master.get("provider") == "zhipu":
            def worker():
                data = zhipu_sync.fetch_zhipu_month(headless=True, timeout=60,
                                                    year=year, month=month)
                self.ui_queue.put(lambda dd=data: self._month_synced(dd))
            threading.Thread(target=worker, daemon=True).start()
        else:
            self._ensure_month_sync(year, month)

    def _ensure_month_sync(self, year, month):
        def worker():
            try:
                start = int(datetime.datetime(year, month, 1).timestamp())
                ey, em = (year + 1, 1) if month == 12 else (year, month + 1)
                end = int(datetime.datetime(ey, em, 1).timestamp())
                d = browser_sync.fetch_deepseek_daily(headless=True, timeout=60,
                                                      start=start, end=end)
                data = d.get("data") if d.get("ok") else None
            except Exception:
                data = None
            self.ui_queue.put(lambda dd=data: self._month_synced(dd))

        threading.Thread(target=worker, daemon=True).start()

    def _month_synced(self, data):
        if data:
            self._merge_daily(data)
            if getattr(self, "_cal_win", None):
                self._render_calendar()

    # ------------------------------------------------------------------ 当天详情
    def show_day_detail(self, date_str):
        recs = [r for r in self._filtered_daily() if r["date"] == date_str]
        if not recs:
            messagebox.showinfo("提示", "该日暂无用量数据", parent=self.root)
            return
        rec = recs[0]
        win = tk.Toplevel(self.root)
        win.title(f"{date_str} 用量")
        win.geometry("380x260")
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        prov = rec.get("provider", "deepseek")
        # 能提供 Token/请求维度的服务商才显示对应数据，否则明确「暂不支持」
        has_token_dim = prov in ("deepseek", "openrouter")
        info = [f"日期：{date_str}", "",
                f"金额：¥{rec['cost']:.4f}"]
        if has_token_dim:
            info += [f"Token：{rec['tokens']:,}", f"请求次数：{rec['requests']}"]
        else:
            info += ["Token：暂不支持", "请求次数：暂不支持"]
        tk.Label(win, text="\n".join(info), bg=COLOR_BG, fg=COLOR_TEXT, font=FONT_NORMAL,
                 justify="left").pack(padx=24, pady=(18, 10))
        if prov in ("deepseek", "openrouter"):
            # 每小时分布：DeepSeek / OpenRouter 有官方接口
            ios_ui.iOSButton(win, "每小时 Token 分布",
                             lambda: self._draw_hourly(date_str, "token", prov), color=ios_ui.SYNC_BG, fg=ios_ui.SYNC_FG,
                             width=168, height=36, font_size=10).pack(pady=(4, 0))
            tk.Label(win, text="查看该天每小时 Token 用量",
                     bg=COLOR_BG, fg=COLOR_SUB2, font=FONT_SMALL).pack(pady=(8, 0))
        else:
            tk.Label(win, text="该服务商暂不支持每小时 Token 分布",
                     bg=COLOR_BG, fg=COLOR_SUB2, font=FONT_SMALL).pack(pady=(8, 0))

    # ------------------------------------------------------------------ 用量图
    def show_hourly_chart(self, date_str):
        win = tk.Toplevel(self.root)
        win.title("选择图表")
        win.geometry("300x180")
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        tk.Label(win, text=f"{date_str} 选择图表类型：", bg=COLOR_BG,
                 fg=COLOR_TEXT, font=FONT_NORMAL).pack(pady=(20, 10))

        def pick(mode):
            win.destroy()
            self._draw_hourly(date_str, mode)

        ios_ui.iOSButton(win, "Token 用量图", lambda: pick("token"), color=COLOR_PRIMARY,
                         width=132, height=34, font_size=10).pack(pady=4)
        ios_ui.iOSButton(win, "金额用量图", lambda: pick("cost"), color=ios_ui.SYNC_BG, fg=ios_ui.SYNC_FG,
                         width=132, height=34, font_size=10).pack(pady=4)

    def _draw_hourly(self, date_str, mode, provider="deepseek"):
        # 立即弹出加载窗口，避免等待时无反馈（官方数据，令牌失效时需开浏览器，可能较慢）
        win = tk.Toplevel(self.root)
        win.title("加载中")
        win.geometry("340x150")
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        tk.Label(win, text="正在获取小时数据…", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).pack(pady=(34, 6))
        pname = _provider_id_to_name(provider)
        tk.Label(win, text=f"{date_str} · {pname} 官方数据", bg=COLOR_BG,
                 fg=COLOR_SUB2, font=FONT_SMALL).pack()
        self._hourly_loading_win = win
        self._hourly_loading_meta = (date_str, mode)
        self._update_status(f"正在获取 {date_str} 的小时数据…")
        threading.Thread(target=self._worker_hourly, args=(date_str, mode, provider), daemon=True).start()

    def _worker_hourly(self, date_str, mode, provider="deepseek"):
        try:
            if provider == "openrouter":
                r = openrouter_sync.fetch_openrouter_hourly(date_str, headless=True, timeout=60)
            else:
                r = browser_sync.fetch_hourly(date_str, headless=True, timeout=60)
        except Exception as e:
            r = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        self.ui_queue.put(lambda rr=r, m=mode, ds=date_str: self._hourly_done(ds, m, rr))

    def _hourly_done(self, date_str, mode, result):
        # 关闭对应的加载窗口
        try:
            if (getattr(self, "_hourly_loading_win", None) is not None
                    and getattr(self, "_hourly_loading_meta", None) == (date_str, mode)):
                self._hourly_loading_win.destroy()
                self._hourly_loading_win = None
        except Exception:  # noqa: BLE001
            pass
        if not result.get("ok"):
            messagebox.showwarning("提示", result.get("error", "获取失败"), parent=self.root)
            return
        records = result["data"]
        win = tk.Toplevel(self.root)
        win.title(f"{date_str} - {'Token' if mode=='token' else '金额'}分布")
        win.geometry("760x480")
        win.configure(bg=COLOR_BG)
        cv = tk.Canvas(win, bg="#ffffff", highlightthickness=1,
                       highlightbackground=COLOR_BORDER)
        cv.pack(fill="both", expand=True, padx=12, pady=12)
        W, H = 720, 420
        left, bottom, top = 46, 40, 30
        plot_w = W - left - 20
        plot_h = H - top - bottom
        vals = [r["tokens"] if mode == "token" else r["cost"] for r in records]
        label = "Token" if mode == "token" else "金额"
        mx = max(vals) or 1
        bw = max(6, plot_w / 24 * 0.6)
        cv.create_line(left, H - bottom, W - 10, H - bottom, fill="#333")
        # 网格线 + m(百万)单位标注
        if mode == "token":
            steps = 5
            for i in range(steps + 1):
                yy = H - bottom - (i / steps) * plot_h
                val_m = mx * i / steps / 1e6
                cv.create_line(left, yy, W - 10, yy, fill="#e5e7eb")
                cv.create_text(left - 4, yy, text=f"{val_m:.0f}m", anchor="e",
                               font=("Microsoft YaHei UI", 7), fill=COLOR_SUB)
        for i, rec in enumerate(records):
            v = vals[i]
            h = v / mx * plot_h
            x = left + i * (plot_w / 24) + plot_w / 24 / 2 - bw / 2
            cv.create_rectangle(x, H - bottom - h, x + bw, H - bottom,
                                fill=_heat(v / mx), outline="")
            if i % 3 == 0:
                cv.create_text(x + bw / 2, H - bottom + 14, text=f"{i}时",
                               font=("Microsoft YaHei UI", 7))
        cv.create_text(left, top, text=f"{date_str} {label}分布(m=百万)",
                       anchor="w", font=FONT_SMALL)

    # ------------------------------------------------------------------ 预警设置
    def set_alert(self):
        master = self._get_master()
        if not master:
            messagebox.showinfo("提示", "请先点击「主账号」选择一个主账号", parent=self.root)
            return
        mname = master.get("name") or _provider_id_to_name(master.get("provider"))
        win = tk.Toplevel(self.root)
        win.title("费用预警设置")
        win.geometry("360x250")
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        tk.Label(win, text=f"主账号：{mname}\n余额低于多少元时提醒？\n(填 0 或留空 = 关闭预警)",
                 bg=COLOR_BG, fg=COLOR_TEXT, font=FONT_NORMAL,
                 justify="center").pack(padx=20, pady=(14, 6))
        var = tk.StringVar(value=str(self._alert_threshold_for() or ""))
        tk.Entry(win, textvariable=var, font=FONT_NORMAL, width=20).pack(pady=6)

        def save():
            try:
                th = float(var.get().strip() or 0)
            except ValueError:
                th = 0
            self._alerts[master["id"]] = th
            s = storage.load_settings()
            s["alerts"] = self._alerts
            storage.save_settings(s)
            logger.log(f"主账号「{mname}」预警阈值已设置：{th} 元")
            win.destroy()
            if th > 0:
                self._update_status(f"预警已设置：主账号「{mname}」余额低于 ¥{th:.2f} 时提醒")
            else:
                self._update_status("预警已关闭")

        ios_ui.iOSButton(win, "保存", save, color=COLOR_PRIMARY,
                         width=88, height=34, font_size=11).pack(pady=(8, 12))

    def _update_status(self, text):
        """状态小字已按用户要求移除，此方法保留为空（兼容旧调用点）。"""
        pass

    # ------------------------------------------------------------------ 自动刷新
    def _toggle_auto(self):
        self._cancel_auto_job()
        if self.auto_minutes.get() == 1:
            self._schedule_auto_refresh()
        self._persist_auto()

    def _on_minutes_change(self):
        # 调整分钟数：保存设置，并按新间隔重新调度
        self._persist_auto()
        if self.auto_minutes.get() == 1:
            self._schedule_auto_refresh()

    def _cancel_auto_job(self):
        if self.auto_job is not None:
            try:
                self.root.after_cancel(self.auto_job)
            except Exception:  # noqa: BLE001
                pass
            self.auto_job = None

    def _schedule_auto_refresh(self):
        self._cancel_auto_job()
        minutes = self._clamp_minutes(self.auto_var.get(), 10)
        if self.auto_minutes.get() != 1:
            return
        self.auto_job = self.root.after(minutes * 60 * 1000, self._auto_tick)

    def _auto_tick(self):
        self.refresh_all()
        self._schedule_auto_refresh()

    def _clamp_minutes(self, raw, default):
        """解析并限制分钟数为 1~120 的整数；输入非法/超上限时回退到合理值。"""
        try:
            m = int(str(raw).strip())
        except (TypeError, ValueError):
            return default
        if m < 1:
            return default
        return min(m, 120)

    def _persist_auto(self):
        minutes = self._clamp_minutes(self.auto_var.get(), 10)
        self.auto_var.set(str(minutes))  # 回显修正值（如输入 500 → 120）
        enabled = self.auto_minutes.get() == 1
        # 先读已有设置再覆盖，避免把主账号 / 预警等其他设置冲掉
        s = storage.load_settings()
        s["auto_refresh"] = enabled
        s["auto_minutes"] = minutes
        storage.save_settings(s)
        logger.log(f"自动刷新设置已保存：开启={enabled}，间隔={minutes}分钟")

    # ------------------------------------------------------------------ 自动同步官方
    def _toggle_sync(self):
        self._cancel_sync_job()
        if self.sync_enabled.get() == 1:
            self._schedule_auto_sync()
        self._persist_sync()

    def _on_sync_minutes_change(self):
        self._persist_sync()
        if self.sync_enabled.get() == 1:
            self._schedule_auto_sync()

    def _cancel_sync_job(self):
        if self.sync_job is not None:
            try:
                self.root.after_cancel(self.sync_job)
            except Exception:
                pass
            self.sync_job = None

    def _schedule_auto_sync(self):
        self._cancel_sync_job()
        minutes = self._clamp_minutes(self.sync_minutes_var.get(), 30)
        if self.sync_enabled.get() != 1:
            return
        self.sync_job = self.root.after(minutes * 60 * 1000, self._sync_tick)

    def _sync_tick(self):
        self.sync_official()
        self._schedule_auto_sync()

    def _persist_sync(self):
        minutes = self._clamp_minutes(self.sync_minutes_var.get(), 30)
        self.sync_minutes_var.set(str(minutes))  # 回显修正值
        enabled = self.sync_enabled.get() == 1
        s = storage.load_settings()
        s["auto_sync"] = enabled
        s["auto_sync_minutes"] = minutes
        storage.save_settings(s)
        logger.log(f"自动同步官方设置已保存：开启={enabled}，间隔={minutes}分钟")

    # ------------------------------------------------------------------ 增删改
    def open_add_dialog(self):
        AccountDialog(self.root, on_save=self._add_account, app=self)

    def _add_account(self, account, name, provider, api_key, base_url):
        # account 参数在「编辑」时传入；「添加」时为 None，这里忽略即可
        acc = {
            "id": storage.new_id(),
            "name": name,
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "created_at": time.time(),
        }
        self.accounts.append(acc)
        storage.save_accounts(self.accounts)
        self._rebuild_list()
        self._update_status(f"已添加「{acc.get('name') or _provider_id_to_name(provider)}」，正在查询余额…")
        self.refresh_one(acc)

    def open_edit_dialog(self, acc):
        AccountDialog(self.root, account=acc, on_save=self._save_edit, app=self)

    def _save_edit(self, acc, name, provider, api_key, base_url):
        acc["name"] = name
        acc["provider"] = provider
        acc["api_key"] = api_key
        acc["base_url"] = base_url
        storage.save_accounts(self.accounts)
        self._rebuild_list()
        self._update_status(f"已更新「{acc.get('name') or _provider_id_to_name(provider)}」…")
        self.refresh_one(acc)

    def delete_account(self, acc):
        if not messagebox.askyesno(
                "删除账号",
                f"确定要删除「{acc.get('name') or _provider_id_to_name(acc.get('provider'))}」吗？\n本机保存的 API Key 也会一并删除。"):
            return
        self.accounts = [a for a in self.accounts if a["id"] != acc["id"]]
        self.results.pop(acc["id"], None)
        storage.save_accounts(self.accounts)
        self._rebuild_list()
        self._update_status(f"已删除，剩余 {len(self.accounts)} 个账号")

    # ------------------------------------------------------------------ 排序
    def open_sort_menu(self):
        """排序菜单：点击「排序」按钮在按钮下方弹出选项。当前已选方式前打 ✔。"""
        menu = tk.Menu(self.root, tearoff=0, font=FONT_NORMAL)
        for text, cmd in self._sort_menu_items():
            menu.add_command(label=text, command=cmd)
        try:
            x = self.sort_btn.cv.winfo_rootx()
            y = self.sort_btn.cv.winfo_rooty() + self.sort_btn.cv.winfo_height()
        except Exception:  # noqa: BLE001
            x, y = 0, 0
        menu.tk_popup(x, y)

    def _sort_menu_items(self):
        """排序菜单项：当前已选中的排序方式前加「✔ 」。"""
        cur = getattr(self, "_sort_mode", "")
        items = [
            ("按添加时间（从早→晚）", self.sort_by_time, "time"),
            ("按模型余额（高 → 低）", self.sort_by_balance, "balance"),
            ("按名称（首字母）", self.sort_by_name, "name"),
        ]
        return [(("✔ " + t) if cur == m else t, cmd) for t, cmd, m in items]

    def _account_balance(self, acc):
        """统一取某账号当前余额（DeepSeek/Kimi/智谱走同步数据，其他走余额接口）。"""
        p = acc.get("provider")
        if p == "deepseek" and self.official_data and self.official_data.get("ok"):
            try:
                return float(self.official_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                pass
        if p == "moonshot" and self.kimi_data and self.kimi_data.get("ok"):
            try:
                return float(self.kimi_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                pass
        if p == "zhipu" and self.zhipu_data and self.zhipu_data.get("ok"):
            try:
                return float(self.zhipu_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                pass
        if p == "siliconflow" and self.siliconflow_data and self.siliconflow_data.get("ok"):
            try:
                return float(self.siliconflow_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                pass
        if p == "openrouter" and self.openrouter_data and self.openrouter_data.get("ok"):
            try:
                return float(self.openrouter_data["data"].get("balance", 0))
            except (TypeError, ValueError):
                pass
        res = self.results.get(acc["id"])
        if res and res.get("ok"):
            try:
                return float(res.get("value"))
            except (TypeError, ValueError):
                pass
        return None

    def _sort_key_name(self, acc):
        """按名称排序键：去掉括号内容后，取首个字符的首字母（中文转拼音首字母）。"""
        nm = (acc.get("name") or "").strip() or _provider_id_to_name(acc.get("provider"))
        nm = re.sub(r"[（(].*?[)）]", "", nm).strip()
        first = nm[:1]
        return (_py_first(first), nm.lower())

    def _apply_sort_order(self):
        """按当前排序模式重排 self.accounts（不重建 UI）。未设置排序时不动。"""
        m = getattr(self, "_sort_mode", "")
        if m == "time":
            self.accounts.sort(key=lambda a: (a.get("created_at") or 0) or 0)
        elif m == "balance":
            # 余额缺失的排最后，其余按余额从高到低
            def key(a):
                b = self._account_balance(a)
                return (1, 0.0) if b is None else (0, -b)
            self.accounts.sort(key=key)
        elif m == "name":
            self.accounts.sort(key=self._sort_key_name)

    def _persist_sort_mode(self):
        try:
            s = storage.load_settings()
            s["sort_mode"] = getattr(self, "_sort_mode", "")
            storage.save_settings(s)
        except Exception:  # noqa: BLE001
            pass

    def _set_sort(self, mode):
        self._sort_mode = mode
        self._persist_sort_mode()
        self._apply_sort_order()   # 仅在用户选择排序时排一次，此后顺序固定
        self._rebuild_list()

    def sort_by_time(self):
        self._set_sort("time")

    def sort_by_balance(self):
        self._set_sort("balance")

    def sort_by_name(self):
        self._set_sort("name")

    def run(self):
        self.root.mainloop()

    # 任何 Tk 回调里的异常都弹窗显示，避免“没反应”
    def report_callback_exception(self, exc, val, tb):
        detail = "".join(traceback.format_exception(exc, val, tb))
        logger.log_exc("Tk 回调异常")
        try:
            messagebox.showerror("程序出错了", f"发生了一个错误：\n\n{val}\n\n详细信息：\n{detail}")
        except Exception:  # noqa: BLE001
            pass


class MasterDialog:
    """主账号设置：选择一个账号作为主账号。能查到 API Key 维度用量信息的模型
    （如 DeepSeek）自动按账号名称匹配统计，无需手动绑定 API Key。"""

    def __init__(self, parent, app):
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("主账号设置")
        self.win.configure(bg=COLOR_BG)
        self.win.resizable(False, False)
        # 不使用 grab_set：允许窗口最小化、且不阻断主窗口操作

        body = tk.Frame(self.win, bg=COLOR_BG, padx=20, pady=18)
        body.pack()

        tk.Label(body, text="主账号（每日用量 / 预警设置跟随它）", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).grid(row=0, column=0, sticky="w", pady=(0, 8))

        accounts = app.accounts
        # 下拉选项只显示账号名；没起名字时用服务商短名（不追加服务商全名/模型名）
        self.display = [f"{a.get('name') or _provider_short_name(a['provider'])}"
                        for a in accounts]
        self.acc_var = tk.StringVar()
        self.acc_box = ttk.Combobox(body, textvariable=self.acc_var, state="readonly",
                                    font=FONT_NORMAL, width=38, values=self.display)
        self.acc_box.grid(row=1, column=0, pady=(0, 12), sticky="ew")
        idx = next((i for i, a in enumerate(accounts) if a.get("id") == app._master_id), 0)
        self.acc_box.current(idx)

        btns = tk.Frame(body, bg=COLOR_BG)
        btns.grid(row=2, column=0, sticky="e", pady=(4, 0))
        ios_ui.iOSButton(btns, "取消", self.win.destroy, color=ios_ui.BTN_GRAY, fg=ios_ui.BTN_GRAY_FG,
                         width=84, height=34, font_size=11).pack(side="right", padx=(8, 0))
        ios_ui.iOSButton(btns, "保存", self._save, color=COLOR_PRIMARY,
                         width=84, height=34, font_size=11).pack(side="right")

        self.win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.win.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + 80
        self.win.geometry(f"+{max(x, 0)}+{y}")

    def _current_acc(self):
        idx = self.acc_box.current()
        if 0 <= idx < len(self.app.accounts):
            return self.app.accounts[idx]
        return None

    def _save(self):
        acc = self._current_acc()
        if not acc:
            messagebox.showwarning("提示", "请选择一个主账号", parent=self.win)
            return
        self.app._master_id = acc["id"]
        self.app._master_api = ""   # 不再手动绑定；由 _filtered_daily 按账号名称自动匹配
        s = storage.load_settings()
        s["master_account_id"] = self.app._master_id
        s["master_api_name"] = ""
        storage.save_settings(s)
        logger.log(f"主账号已切换为：{acc.get('name') or _provider_id_to_name(acc['provider'])}")
        self.app._update_master_ui()
        self.win.destroy()


class AccountDialog:
    """添加 / 编辑账号的对话框。"""

    def __init__(self, parent, on_save, account=None, app=None):
        self.on_save = on_save
        self.account = account
        self.app = app
        editing = account is not None

        self.win = tk.Toplevel(parent)
        self.win.title("编辑账号" if editing else "添加账号")
        self.win.configure(bg=COLOR_BG)
        self.win.resizable(False, False)
        # 不使用 grab_set：允许窗口最小化、不阻断主窗口操作

        body = tk.Frame(self.win, bg=COLOR_BG, padx=20, pady=18)
        body.pack()

        # 名称
        tk.Label(body, text="名称（可选）", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.name_var = tk.StringVar(value=account.get("name", "") if account else "")
        tk.Entry(body, textvariable=self.name_var, font=FONT_NORMAL,
                 width=40).grid(row=1, column=0, pady=(0, 12), sticky="ew")

        # 服务商（下拉选择：已添加的模型字体变灰、不可选）
        tk.Label(body, text="服务商", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._provider_id = account.get("provider") if account else providers.PROVIDERS[0]["id"]
        self.provider_var = tk.StringVar(value=_provider_id_to_name(self._provider_id))
        prow = tk.Frame(body, bg=COLOR_CARD)
        prow.grid(row=3, column=0, pady=(0, 4), sticky="ew")
        self.provider_entry = tk.Entry(prow, textvariable=self.provider_var, state="readonly",
                                       font=FONT_NORMAL, bg=COLOR_CARD, fg=COLOR_TEXT,
                                       relief="flat", bd=1, highlightbackground=COLOR_BORDER)
        self.provider_entry.pack(side="left", fill="x", expand=True, ipady=4)
        # 编辑模式：服务商锁定，不能更换
        tk.Button(prow, text="▾", command=self._open_provider_list, bg=COLOR_CARD,
                  fg=COLOR_TEXT, relief="flat", bd=0, font=FONT_NORMAL,
                  cursor="hand2", padx=6,
                  state="disabled" if editing else "normal").pack(side="right")

        self.hint_label = tk.Label(body, text="", bg=COLOR_BG, fg=COLOR_SUB2, font=FONT_SMALL)
        self.hint_label.grid(row=4, column=0, sticky="w", pady=(0, 12))

        # API Key
        tk.Label(body, text="API Key", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).grid(row=5, column=0, sticky="w", pady=(0, 4))
        key_row = tk.Frame(body, bg=COLOR_BG)
        key_row.grid(row=6, column=0, pady=(0, 4), sticky="ew")
        self.key_var = tk.StringVar(value=account["api_key"] if account else "")
        self.key_entry = tk.Entry(key_row, textvariable=self.key_var, show="*",
                                  font=FONT_NORMAL, width=33,
                                  state="readonly" if editing else "normal")
        self.key_entry.pack(side="left")
        self.show_btn = tk.Button(key_row, text="👁 显示", command=self._toggle_show,
                                  bg=COLOR_BG, fg=COLOR_PRIMARY, relief="flat", bd=0,
                                  font=FONT_SMALL, cursor="hand2")
        self.show_btn.pack(side="left", padx=(8, 0))
        tk.Label(body, text="从服务商官网的「API Key」页面获取",
                 bg=COLOR_BG, fg=COLOR_SUB2, font=FONT_SMALL).grid(
            row=7, column=0, sticky="w", pady=(0, 12))

        # 自定义地址
        tk.Label(body, text="接口地址（可选，留空用默认）", bg=COLOR_BG, fg=COLOR_TEXT,
                 font=FONT_NORMAL).grid(row=8, column=0, sticky="w", pady=(0, 4))
        self.url_var = tk.StringVar(value=account.get("base_url", "") if account else "")
        tk.Entry(body, textvariable=self.url_var, font=FONT_NORMAL,
                 width=40, state="readonly" if editing else "normal").grid(
            row=9, column=0, pady=(0, 16), sticky="ew")

        # 按钮
        btns = tk.Frame(body, bg=COLOR_BG)
        btns.grid(row=10, column=0, sticky="e")
        ios_ui.iOSButton(btns, "取消", self.win.destroy, color=ios_ui.BTN_GRAY, fg=ios_ui.BTN_GRAY_FG,
                         width=84, height=34, font_size=11).pack(side="right", padx=(8, 0))
        ios_ui.iOSButton(btns, "保存", self._save, color=COLOR_PRIMARY,
                         width=84, height=34, font_size=11).pack(side="right")

        self._last_provider = self._provider_id
        self._on_provider_change()
        self.win.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.win.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + 60
        self.win.geometry(f"+{max(x, 0)}+{y}")

    def _open_provider_list(self):
        """弹出服务商下拉列表：已添加的模型字体变灰、点击不可选（删除账号后恢复）。"""
        # 已添加过的服务商一律置灰（含当前选中项，避免重复添加同一模型）
        used = set()
        if self.app is not None:
            used = {a.get("provider") for a in self.app.accounts}
        win = tk.Toplevel(self.win)
        win.overrideredirect(True)
        try:
            x = self.provider_entry.winfo_rootx()
            y = self.provider_entry.winfo_rooty() + self.provider_entry.winfo_height()
        except Exception:  # noqa: BLE001
            x, y = 0, 0
        win.geometry(f"+{x}+{y}")
        lb = tk.Listbox(win, font=FONT_NORMAL, height=len(providers.PROVIDERS),
                        exportselection=False, bd=1, relief="solid",
                        activestyle="none", selectbackground="#dbeafe")
        lb.pack()
        for p in providers.PROVIDERS:
            lb.insert(tk.END, p["name"])
            if p["id"] in used:
                lb.itemconfig(tk.END, fg="#a0a0a0")  # 已添加：字体变灰

        def _pick(_e):
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            if idx >= len(providers.PROVIDERS):
                return
            if providers.PROVIDERS[idx]["id"] in used:
                return  # 已添加：不可选
            self._provider_id = providers.PROVIDERS[idx]["id"]
            self.provider_var.set(providers.PROVIDERS[idx]["name"])
            self._on_provider_change()
            win.destroy()

        lb.bind("<ButtonRelease-1>", _pick)
        lb.bind("<FocusOut>", lambda e: win.destroy())
        lb.focus_set()

    def _current_provider(self):
        return self._provider_id

    def _on_provider_change(self):
        cur = self._provider_id
        p = providers.get_provider(cur)
        self.hint_label.configure(text=p["hint"] if p else "")
        # 只有地址为空、或仍是上一个服务商的默认地址时，才切换成新服务商的默认地址；
        # 用户手动填过的地址保持不变。
        last_p = providers.get_provider(self._last_provider)
        cur_url = self.url_var.get()
        if (not cur_url) or (last_p and cur_url == last_p["default_base"]):
            self.url_var.set(p["default_base"] if p else "")
        self._last_provider = cur

    def _toggle_show(self):
        if self.key_entry.cget("show") == "*":
            self.key_entry.configure(show="")
            self.show_btn.configure(text="🙈 隐藏")
        else:
            self.key_entry.configure(show="*")
            self.show_btn.configure(text="👁 显示")

    def _save(self):
        try:
            name = self.name_var.get().strip()
            provider = self._current_provider()
            api_key = self.key_var.get().strip()
            base_url = self.url_var.get().strip()
            logger.log(f"点击保存：名称={name!r} 服务商={provider!r} Key长度={len(api_key)} 地址={base_url!r}")
            if not api_key:
                messagebox.showwarning("提示", "请填写 API Key", parent=self.win)
                return
            # 每个模型只能添加一个 API Key：同一服务商已有账号时禁止重复添加
            if self.account is None and self.app is not None:
                exists = [a for a in self.app.accounts if a.get("provider") == provider]
                if exists:
                    messagebox.showwarning(
                        "提示",
                        f"「{_provider_id_to_name(provider)}」已有一个 API Key，每个模型只能添加一个。\n"
                        "如需更换 Key，请先删除原账号再重新添加。",
                        parent=self.win)
                    return
            self.on_save(self.account, name, provider, api_key, base_url)
            logger.log("保存成功，对话框关闭")
        except Exception as e:  # noqa: BLE001
            logger.log_exc("保存时出错")
            messagebox.showerror("保存失败", f"发生了一个错误：\n{e}", parent=self.win)
            return
        self.win.destroy()


def main():
    # 启用 DPI 感知：避免 Windows 缩放导致界面模糊/低像素/圆角锯齿
    scale = 1.0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        scale = ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    app = BalanceApp(root, scale)
    app.run()


if __name__ == "__main__":
    main()
