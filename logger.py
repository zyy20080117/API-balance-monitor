# -*- coding: utf-8 -*-
"""简易日志：把操作和异常写到 ~/.model_balance/app.log，便于排查。"""

import datetime
import os
import traceback

LOG_PATH = os.path.join(os.path.expanduser("~"), ".model_balance", "app.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def log_exc(context):
    log(f"{context}\n{traceback.format_exc()}")
