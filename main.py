# -*- coding: utf-8 -*-
"""大模型余额监控 —— 程序入口

捕获未处理异常：崩溃时弹窗显示错误信息与堆栈，并写入日志文件，避免直接闪退。
"""

import sys
import tkinter as tk
import traceback
from tkinter import messagebox

import logger


def _show_fatal(tb_text):
    """崩溃时弹窗显示错误与堆栈，并写入日志文件。"""
    try:
        logger.log("程序发生未捕获异常\n" + tb_text)
    except Exception:
        pass
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("程序出错了", f"发生了一个错误：\n\n{tb_text}")
        root.destroy()
    except Exception:
        pass


def main():
    try:
        from gui import main as gui_main
        gui_main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        _show_fatal(tb)
        sys.exit(1)


if __name__ == "__main__":
    main()
