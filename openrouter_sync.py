# -*- coding: utf-8 -*-
"""OpenRouter（openrouter.ai）同步：余额（HTTP）+ 每日用量（浏览器 analytics）。

- 余额/累计消费：官方 HTTP 接口 /api/v1/credits，用账号的 API Key（Bearer）。
- 每日用量：浏览器打开 activity 控制台，POST analytics-query（按日粒度，近90天）。
  无用量数据时返回空列表（账号无消费时 analytics 为空，符合"有就保留，没有才舍去"）。
"""

import datetime
import json

import requests
import browser_sync
from playwright.sync_api import sync_playwright

ACTIVITY_URL = "https://openrouter.ai/activity"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
HTTP_TIMEOUT = 15


def _parse_analytics(data):
    """解析 analytics-query 响应为逐日记录列表；无数据返回 []。

    响应结构：{"data": {"data": [ {date, total_usage, request_count,
    tokens_prompt, tokens_completion, ...}, ... ]}}。
    total_usage 单位为美元（USD）。
    """
    records = []
    if not isinstance(data, dict):
        return records
    d = data.get("data") or {}
    items = d.get("data") or []
    if not isinstance(items, list):
        return records
    for it in items:
        if not isinstance(it, dict):
            continue
        date = it.get("date") or it.get("day") or ""
        if not date:
            continue
        date_str = str(date)[:10]
        cost = it.get("total_usage")
        if cost is None:
            cost = it.get("cost") or 0
        try:
            cost_f = float(cost)
        except (TypeError, ValueError):
            cost_f = 0.0
        req = it.get("request_count") or 0
        try:
            req_f = int(req)
        except (TypeError, ValueError):
            req_f = 0
        tok = (it.get("tokens_prompt") or 0) + (it.get("tokens_completion") or 0)
        try:
            tok_f = int(tok)
        except (TypeError, ValueError):
            tok_f = 0
        records.append({
            "date": date_str, "cost": round(cost_f, 6), "tokens": tok_f, "requests": req_f,
            "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
            "api_key": "", "name": "", "provider": "openrouter",
        })
    records.sort(key=lambda r: r["date"])
    return records


def _fetch_credits(api_key):
    """HTTP 查 OpenRouter 余额：total_credits / total_usage。失败返回 None。"""
    if not api_key:
        return None
    try:
        r = requests.get(CREDITS_URL, headers={"Authorization": f"Bearer {api_key}"},
                         timeout=HTTP_TIMEOUT)
        if not r.ok:
            return None
        return (r.json() or {}).get("data") or {}
    except Exception:  # noqa: BLE001
        return None


def fetch_openrouter_usage_daily(api_key="", headless=True, timeout=90):
    """同步 OpenRouter：余额（HTTP）+ 每日用量（浏览器 analytics，近90天）。

    返回 {"ok", "data": {balance, total_cost, today_consume, total_credits},
          "daily": [records], "error"}。
    """
    result = {"ok": False, "data": None, "daily": [], "error": "未获取到数据"}

    # 1) 余额/累计消费（HTTP，用账号 API Key）
    credits = _fetch_credits(api_key)
    if credits is not None:
        total = credits.get("total_credits")
        used = credits.get("total_usage")
        try:
            total_f = float(total) if total is not None else None
        except (TypeError, ValueError):
            total_f = None
        try:
            used_f = float(used) if used is not None else None
        except (TypeError, ValueError):
            used_f = None
        if total_f is not None:
            remaining = total_f - used_f if used_f is not None else total_f
            result["ok"] = True
            result["data"] = {
                "balance": "%.2f" % max(remaining, 0),
                "total_cost": "%.2f" % (used_f or 0),
                "today_consume": None,
                "total_credits": "%.2f" % total_f,
            }
        else:
            result["error"] = "余额接口未返回有效数据"
    else:
        result["error"] = "余额查询失败（请检查 API Key）"

    # 2) 每日用量（浏览器 analytics-query）
    daily = _fetch_analytics_daily(headless, timeout)
    if daily is not None:
        result["daily"] = daily
        if result.get("data"):
            if daily:
                result["data"]["total_cost"] = "%.2f" % sum(r["cost"] for r in daily)
                tdy = datetime.date.today().isoformat()
                tc = next((r["cost"] for r in daily if r["date"] == tdy), None)
                if tc is not None:
                    result["data"]["today_consume"] = "%.2f" % tc
    return result


def _fetch_analytics_daily(headless=True, timeout=90):
    """浏览器打开 activity 页，POST analytics-query 抓近90天按日用量。失败返回 None。"""
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                page.goto(ACTIVITY_URL, timeout=timeout * 1000)
                page.wait_for_timeout(4000)
                now = datetime.datetime.utcnow()
                start = (now - datetime.timedelta(days=90)).strftime("%Y-%m-%dT00:00:00.000Z")
                end = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
                body = json.dumps({
                    "metrics": ["total_usage", "request_count",
                                "tokens_prompt", "tokens_completion"],
                    "granularity": "day",
                    "time_range": {"start": start, "end": end},
                    "order_by": {"field": "date", "direction": "asc"},
                    "limit": 400,
                })
                js = ("async (b) => { const r = await fetch('/api/frontend/v1/private/analytics-query', "
                      "{method:'POST', headers:{'Content-Type':'application/json'}, "
                      "credentials:'include', body:b}); return await r.json(); }")
                res = page.evaluate(js, body)
                return _parse_analytics(res)
            finally:
                ctx.close()
    except Exception:  # noqa: BLE001
        return None


def fetch_openrouter_hourly(date_str, headless=True, timeout=60):
    """OpenRouter 指定日的小时分布（analytics granularity=hour）。返回 {"ok","data"}。"""
    result = {"ok": False, "data": None, "error": "未获取到小时数据"}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                page.goto(ACTIVITY_URL, timeout=timeout * 1000)
                page.wait_for_timeout(4000)
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                start = dt.strftime("%Y-%m-%dT00:00:00.000Z")
                end = (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
                body = json.dumps({
                    "metrics": ["total_usage", "request_count",
                                "tokens_prompt", "tokens_completion"],
                    "granularity": "hour",
                    "time_range": {"start": start, "end": end},
                    "order_by": {"field": "date", "direction": "asc"},
                    "limit": 400,
                })
                js = ("async (b) => { const r = await fetch('/api/frontend/v1/private/analytics-query', "
                      "{method:'POST', headers:{'Content-Type':'application/json'}, "
                      "credentials:'include', body:b}); return await r.json(); }")
                res = page.evaluate(js, body)
                records = _parse_hourly(res)
                if records:
                    result = {"ok": True, "data": records}
                else:
                    result = {"ok": False, "error": "该日暂无小时用量数据"}
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return result


def _parse_hourly(data):
    """解析 analytics granularity=hour 响应为 0-23 小时记录列表。

    date 形如 '2026-08-12T14:00:00.000Z'，取其小时。
    """
    hours = {}
    if isinstance(data, dict):
        d = data.get("data") or {}
        items = d.get("data") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            ds = str(it.get("date") or "")
            try:
                hour = int(ds[11:13])
            except (ValueError, IndexError):
                continue
            cost = it.get("total_usage")
            try:
                cost_f = float(cost) if cost is not None else 0.0
            except (TypeError, ValueError):
                cost_f = 0.0
            tok = (it.get("tokens_prompt") or 0) + (it.get("tokens_completion") or 0)
            try:
                tok_f = int(tok)
            except (TypeError, ValueError):
                tok_f = 0
            req = it.get("request_count") or 0
            try:
                req_f = int(req)
            except (TypeError, ValueError):
                req_f = 0
            hours[hour] = {"tokens": tok_f, "cost": cost_f, "requests": req_f}
    records = []
    for hour in range(24):
        h = hours.get(hour, {})
        records.append({
            "hour": hour,
            "tokens": int(h.get("tokens", 0)),
            "cost": round(float(h.get("cost", 0)), 6),
            "requests": int(h.get("requests", 0)),
            "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
        })
    return records
