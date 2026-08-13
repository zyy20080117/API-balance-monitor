# -*- coding: utf-8 -*-
"""Kimi 平台浏览器同步：抓取登录后的消费数据（总消费/今日消费/余额）。

需要先在软件浏览器（browser_profile）里登录 platform.kimi.com。
数据单位：接口返回 1e-5 元，转换为元。
"""

import datetime
import json
import os
import re

import browser_sync
from playwright.sync_api import sync_playwright

KIMI_URL = "https://platform.kimi.com/console/account"
KIMI_FEE_URL = "https://platform.kimi.com/console/fee-detail?tab=daily"


def fetch_kimi_usage(headless=True, timeout=60):
    """抓取 Kimi 账户消费数据。返回 {"ok", "data": {total_cost, today_consume, balance}} 或错误。"""
    result = {"ok": False, "error": "未获取到数据"}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                info = {"use": None}

                def _on_resp(r):
                    if "/api?endpoint=organizationAccountInfo" in r.url:
                        try:
                            j = r.json()
                            if j.get("code") == 0 and j.get("data"):
                                d = j["data"]
                                info["use"] = d.get("use")
                                info["today"] = d.get("today_consume")
                                info["cur"] = d.get("cur")
                                info["voucher_cur"] = d.get("voucher_cur")
                                info["acc"] = d.get("acc")
                                info["voucher_acc"] = d.get("voucher_acc")
                        except Exception:  # noqa: BLE001
                            pass

                page.on("response", _on_resp)
                page.goto(KIMI_URL, timeout=timeout * 1000)
                page.wait_for_timeout(6000)
                if info["use"] is not None:
                    result = {"ok": True, "data": {
                        "total_cost": "%.2f" % (info["use"] / 100000.0),
                        "today_consume": "%.2f" % ((info["today"] or 0) / 100000.0),
                        "balance": "%.2f" % (((info["cur"] or 0) + (info["voucher_cur"] or 0)) / 100000.0),
                        "recharge": "%.2f" % ((info["acc"] or 0) / 100000.0),
                        "granted": "%.2f" % ((info["voucher_acc"] or 0) / 100000.0),
                    }}
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return result


def _fmt_date(v):
    """把 Kimi 返回的日期（时间戳/字符串）统一成 YYYY-MM-DD。"""
    if isinstance(v, (int, float)):
        ts = v / 1000.0 if v > 1e12 else v
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None
    s = str(v).replace("/", "-")[:10]
    try:
        datetime.datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:  # noqa: BLE001
        return None


def _parse_kimi_daily(data):
    """解析 organizationDailyBills 响应为逐日记录列表；无数据返回 []。

    Kimi 无 Token 维度明细，故 tokens/requests 记为 0，只统计每日金额。
    金额单位为 1e-5 元（与 accountInfo 一致），除以 100000 转为元。
    """
    records = []
    if not isinstance(data, dict):
        return records
    d = data.get("data")
    if not d:
        return records
    items = d
    if isinstance(d, dict):
        for k in ("list", "items", "records", "bills", "rows", "data"):
            if isinstance(d.get(k), list):
                items = d[k]
                break
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return records
    for it in items:
        if not isinstance(it, dict):
            continue
        date = (it.get("date") or it.get("day") or it.get("bill_date") or it.get("time")
                or it.get("dateStr") or it.get("consumption_date"))
        # Kimi 日账单字段：voucher_fee(代金券) + recharge_fee(充值) 为当日消费
        voucher = it.get("voucher_fee")
        recharge = it.get("recharge_fee")
        if voucher is not None or recharge is not None:
            cost = (voucher or 0) + (recharge or 0)
        else:
            cost = (it.get("cost")
                    if it.get("cost") is not None else
                    it.get("amount")
                    if it.get("amount") is not None else
                    it.get("consume")
                    if it.get("consume") is not None else
                    it.get("total_amount")
                    if it.get("total_amount") is not None else
                    it.get("money"))
        try:
            cost_f = float(cost) / 100000.0 if cost is not None else 0.0
        except (TypeError, ValueError):
            cost_f = 0.0
        date_str = _fmt_date(date)
        if not date_str:
            continue
        records.append({
            "date": date_str, "cost": round(cost_f, 4), "tokens": 0, "requests": 0,
            "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
            "api_key": "", "name": "", "provider": "moonshot",
        })
    records.sort(key=lambda r: r["date"])
    return records


def fetch_kimi_usage_daily(headless=True, timeout=60):
    """一次浏览器会话同步 Kimi 账户信息 + 每日账单。

    返回 {"ok", "data": {total_cost, today_consume, balance, ...}, "daily": [records], "error"}。
    daily 为空列表表示当前无消费记录（Kimi 日账单次日上午 7 点更新）。
    """
    result = {"ok": False, "data": None, "daily": [], "error": "未获取到数据"}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                info = {"use": None, "tok": "", "oid": ""}

                def _on_resp(r):
                    if "/api?endpoint=organizationAccountInfo" in r.url:
                        try:
                            j = r.json()
                            if j.get("code") == 0 and j.get("data"):
                                d = j["data"]
                                info["use"] = d.get("use")
                                info["today"] = d.get("today_consume")
                                info["cur"] = d.get("cur")
                                info["voucher_cur"] = d.get("voucher_cur")
                                info["acc"] = d.get("acc")
                                info["voucher_acc"] = d.get("voucher_acc")
                        except Exception:  # noqa: BLE001
                            pass

                def _on_req(r):
                    u = r.url
                    if "/api?" in u:
                        if not info["tok"]:
                            info["tok"] = r.headers.get("authorization", "")
                        if not info["oid"]:
                            m = re.search(r"[?&]oid=([^&]+)", u)
                            if m:
                                info["oid"] = m.group(1)

                page.on("response", _on_resp)
                page.on("request", _on_req)
                page.goto(KIMI_URL, timeout=timeout * 1000)
                # 条件等待：账户接口响应到了立即继续，避免固定等 6 秒拖慢加载
                for _ in range(int(timeout) * 2):
                    page.wait_for_timeout(250)
                    if info["use"] is not None and info["oid"] and info["tok"]:
                        break

                if info["oid"] and info["tok"]:
                    result["daily"] = _fetch_kimi_daily_via(page, info["oid"], info["tok"], timeout)
                if info["use"] is not None:
                    # 累计消费 = 充值 + 赠送 - 当前余额（Kimi 的 use 只统计现金，不准）
                    total = ((info.get("acc") or 0) + (info.get("voucher_acc") or 0)
                             - (info.get("cur") or 0) - (info.get("voucher_cur") or 0)) / 100000.0
                    if total < 0:
                        total = 0.0
                    today = (info.get("today") or 0) / 100000.0
                    # 官网"消费金额"口径在每日账单里（含赠送账户扣减），更完整则优先
                    if result["daily"]:
                        daily_total = sum(r["cost"] for r in result["daily"])
                        if daily_total > total:
                            total = daily_total
                        tdy = datetime.date.today().isoformat()
                        tc = next((r["cost"] for r in result["daily"] if r["date"] == tdy), None)
                        if tc is not None:
                            today = tc
                    # 兜底：累计消费不能小于今日消费（口径不一致时）
                    if total < today:
                        total = today
                    data = {
                        "total_cost": "%.2f" % total,
                        "today_consume": "%.2f" % today,
                        "balance": "%.2f" % (((info["cur"] or 0) + (info["voucher_cur"] or 0)) / 100000.0),
                        "recharge": "%.2f" % ((info["acc"] or 0) / 100000.0),
                        "granted": "%.2f" % ((info["voucher_acc"] or 0) / 100000.0),
                    }
                    result.update({"ok": True, "data": data})
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return result


def _fetch_kimi_daily_via(page, oid, tok, timeout=60):
    """在已打开的页面上调用 organizationDailyBills 并解析每日账单。"""
    try:
        now = datetime.datetime.now()
        end_dt = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=1)
        start_ms = int((end_dt - datetime.timedelta(days=90)).timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        url = (f"/api?start={start_ms}&end={end_ms}&pid=&oid={oid}&endpoint=organizationDailyBills")
        js = ("async () => { const r = await fetch(%s, { headers: { 'authorization': %s } }); "
              "return await r.json(); }" % (json.dumps(url), json.dumps(tok)))
        data = page.evaluate(js)
        return _parse_kimi_daily(data)
    except Exception:  # noqa: BLE001
        return []
