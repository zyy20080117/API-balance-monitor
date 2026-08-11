# -*- coding: utf-8 -*-
"""GUI 冒烟测试：启动界面，3 秒后自动关闭。若 3 秒内无异常即通过。"""

import sys
import threading
import tkinter as tk

import gui
import providers
import storage


def main():
    # 用一个临时账号测试刷新链路（API Key 无效，预期显示异常但界面不崩）
    root = tk.Tk()
    app = gui.BalanceApp(root)

    # 若没有账号，注入一个无效 Key 的账号，测试异常分支
    if not app.accounts:
        app.accounts.append({
            "id": storage.new_id(),
            "name": "冒烟测试",
            "provider": "deepseek",
            "api_key": "sk-invalid-smoke-test",
            "base_url": "",
        })
        app._rebuild_list()
        app.refresh_one(app.accounts[-1])

    # 3 秒后自动关闭
    root.after(3000, root.destroy)
    root.mainloop()
    print("GUI 冒烟测试通过")


if __name__ == "__main__":
    main()
