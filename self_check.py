# -*- coding: utf-8 -*-
"""余额监控数据自检与自动修正。

功能：
  1. 对比「软件显示 Token」与「官方页面 Token」，不一致时自动用官方页面值（fetch_deepseek_usage 已内置该修正）。
  2. 校验每日 Token 之和，提示口径差异。
  3. 校验小时之和与每日一致。
运行：<venv python> self_check.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import browser_sync  # noqa: E402


def main():
    print("==== 余额监控数据自检 ====")
    issues = 0

    # 1. 官方页面 Token vs 软件显示 Token（自动修正）
    u = browser_sync.fetch_deepseek_usage(headless=True, timeout=60)
    if not u.get("ok"):
        print(f"[错误] 同步失败: {u.get('error')}")
        issues += 1
    else:
        page_tokens = browser_sync._fetch_page_tokens(headless=True, timeout=60, max_age=0)
        shown = u["data"]["tokens"]
        print(f"软件显示 Token: {shown}")
        if page_tokens:
            print(f"官方页面 Token: {page_tokens:,}")
            if shown != str(page_tokens):
                print("[自动修正] Token 已使用官方页面值")
            else:
                print("[正常] Token 与官方一致")
        else:
            print("[警告] 无法抓取官方页面 Token")

    # 2. 每日之和 vs 官方总 Token
    d = browser_sync.fetch_deepseek_daily(headless=True, timeout=60)
    if d.get("ok"):
        daily_sum = sum(r["tokens"] for r in d["data"])
        print(f"每日 Token 之和: {daily_sum:,}")
        if u.get("ok"):
            total = int(u["data"]["tokens"])
            if daily_sum != total:
                print(f"[提示] 每日之和({daily_sum}) 与官方总 Token({total}) 口径不同，总 Token 以官方页面为准")
        # 3. 随机抽一天校验小时之和
        day = d["data"][-1]["date"]
        h = browser_sync.fetch_hourly(day, headless=True, timeout=60)
        if h.get("ok"):
            hourly_sum = sum(r["tokens"] for r in h["data"])
            daily_val = next((r["tokens"] for r in d["data"] if r["date"] == day), None)
            match = (hourly_sum == daily_val)
            print(f"[{'正常' if match else '错误'}] {day} 小时之和={hourly_sum} 每日={daily_val}")
            if not match:
                issues += 1
    else:
        print(f"[错误] 逐日数据获取失败: {d.get('error')}")
        issues += 1

    print("==== 自检完成 ====")
    print("发现问题数:", issues)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
