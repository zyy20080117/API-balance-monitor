# -*- coding: utf-8 -*-
"""卡片顺序保持测试：_update_card 重建单卡后 _reorder_cards 恢复 accounts 顺序，
修复「同步官方时卡片莫名乱跳」的根因（_make_card 会把新卡 pack 到末尾）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk  # noqa: E402

import gui  # noqa: E402


def test_reorder_keeps_account_order():
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.BalanceApp.__new__(gui.BalanceApp)
        app.accounts = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        app.list_frame = tk.Frame(root)
        app.list_frame.pack()
        # 按 accounts 顺序创建卡片
        for acc in app.accounts:
            f = tk.Frame(app.list_frame)
            f._acc_id = acc["id"]
            f.pack(fill="x", pady=(0, 10))
        # 模拟乱序：b 被销毁后加到末尾 → 顺序 a, c, b
        for child in list(app.list_frame.winfo_children()):
            if getattr(child, "_acc_id", None) == "b":
                child.destroy()
        nb = tk.Frame(app.list_frame)
        nb._acc_id = "b"
        nb.pack(fill="x", pady=(0, 10))
        order = [getattr(c, "_acc_id", None) for c in app.list_frame.pack_slaves()]
        assert order == ["a", "c", "b"], order   # 确认产生了乱序（复现 bug）
        # _reorder_cards 恢复 accounts 顺序
        app._reorder_cards()
        order2 = [getattr(c, "_acc_id", None) for c in app.list_frame.pack_slaves()]
        assert order2 == ["a", "b", "c"], order2
        print("PASS: _reorder_cards 保持账号顺序")
    finally:
        root.destroy()


def test_update_card_keeps_order():
    """_update_card 重建单卡用 before 插回原位，顺序不乱跳。"""
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.BalanceApp.__new__(gui.BalanceApp)
        app.accounts = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        app.root = root
        app.canvas = tk.Canvas(root)
        app.canvas.pack()
        app.list_frame = tk.Frame(root)
        app.list_frame.pack()

        def fake_make_card(acc, before=None):
            f = tk.Frame(app.list_frame)
            f._acc_id = acc["id"]
            if before is not None:
                f.pack(fill="x", pady=(0, 10), before=before)
            else:
                f.pack(fill="x", pady=(0, 10))
            return f

        app._make_card = fake_make_card
        app._bind_card_scroll = lambda card: None
        for acc in app.accounts:
            app._make_card(acc)
        order = [getattr(c, "_acc_id", None) for c in app.list_frame.pack_slaves()]
        assert order == ["a", "b", "c"], order
        # 更新中间的 b：重建后插回原位，顺序保持 a, b, c
        app._update_card("b")
        app._flush_card_updates()   # 去抖：立即执行重建
        order2 = [getattr(c, "_acc_id", None) for c in app.list_frame.pack_slaves()]
        assert order2 == ["a", "b", "c"], order2
        # 更新末尾的 c：仍保持
        app._update_card("c")
        app._flush_card_updates()
        order3 = [getattr(c, "_acc_id", None) for c in app.list_frame.pack_slaves()]
        assert order3 == ["a", "b", "c"], order3
        print("PASS: _update_card before 插回保持顺序")
    finally:
        root.destroy()


def test_bind_card_scroll():
    """重建后的新卡应补绑滚轮，避免鼠标停在该卡上无法滚动。"""
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.BalanceApp.__new__(gui.BalanceApp)
        app._on_wheel = lambda e: None
        card = tk.Frame(root)
        label = tk.Label(card, text="x")
        label.pack()
        card.pack()
        app._bind_card_scroll(card)
        assert card.bind("<MouseWheel>") is not None, "card 未绑定滚轮"
        assert label.bind("<MouseWheel>") is not None, "子控件未绑定滚轮"
        print("PASS: 重建卡片补绑滚轮")
    finally:
        root.destroy()


if __name__ == "__main__":
    test_reorder_keeps_account_order()
    test_update_card_keeps_order()
    test_bind_card_scroll()
    print("TEST PASS")
