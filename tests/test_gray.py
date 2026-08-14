# -*- coding: utf-8 -*-
"""验证服务商下拉框：已添加的服务商（含当前选中项）全部置灰。

修复回归测试：当前默认选中的 DeepSeek 已添加时，也必须变灰不可选。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk  # noqa: E402

import gui  # noqa: E402

LAST_TOPLEVEL = {}


class FakeListbox:
    def __init__(self, *a, **k):
        self.items = []
        self.fg = []
        LAST_TOPLEVEL["lb"] = self

    def pack(self, *a, **k):
        pass

    def insert(self, index, text):
        self.items.append(text)
        self.fg.append("black")

    def itemconfig(self, index, **kw):
        if index == "end":
            index = len(self.fg) - 1
        self.fg[index] = kw.get("fg", self.fg[index])

    def curselection(self):
        return ()

    def bind(self, *a, **k):
        pass

    def focus_set(self):
        pass


class FakeApp:
    def __init__(self):
        # deepseek 先添加，moonshot 后添加
        self.accounts = [
            {"provider": "deepseek", "name": "ds1"},
            {"provider": "moonshot", "name": ""},
        ]


def main():
    root = tk.Tk()
    root.withdraw()
    orig_listbox = tk.Listbox
    tk.Listbox = FakeListbox
    try:
        app = FakeApp()
        dlg = gui.AccountDialog(root, on_save=None, app=app)
        # 添加模式默认当前选中 PROVIDERS[0] = deepseek
        assert dlg._provider_id == "deepseek", dlg._provider_id
        dlg._open_provider_list()
        lb = LAST_TOPLEVEL["lb"]
        items, fg = lb.items, lb.fg
        name_to_id = {p["name"]: p["id"] for p in gui.providers.PROVIDERS}
        gray = {name_to_id[n] for n, c in zip(items, fg) if c == "#a0a0a0"}
        black = {name_to_id[n] for n, c in zip(items, fg) if c == "black"}
        # 已添加的两个都必须灰（含当前默认选中的 DeepSeek）
        assert "deepseek" in gray, f"DeepSeek 已添加却未置灰: gray={gray}"
        assert "moonshot" in gray, f"Kimi 已添加却未置灰: gray={gray}"
        # 未添加的仍为黑色可选项
        assert "siliconflow" in black, f"硅基流动未添加却被置灰: black={black}"
        print("GRAY_OK  deepseek+moonshot 均置灰，siliconflow 正常可选项")
    finally:
        tk.Listbox = orig_listbox
        root.destroy()
    print("TEST PASS")


if __name__ == "__main__":
    main()
