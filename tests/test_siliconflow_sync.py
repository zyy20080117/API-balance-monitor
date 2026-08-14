# -*- coding: utf-8 -*-
"""真实调用 siliconflow_sync 同步一次，打印结果。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import siliconflow_sync  # noqa: E402
import browser_sync  # noqa: E402


def main():
    with browser_sync._BROWSER_LOCK:
        r = siliconflow_sync.fetch_siliconflow_usage_daily(headless=True, timeout=90)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])


if __name__ == "__main__":
    main()
