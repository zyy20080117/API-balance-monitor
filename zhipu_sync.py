# -*- coding: utf-8 -*-
"""智谱开放平台（open.bigmodel.cn）浏览器同步：账户余额/消费 + 按日费用明细。

需要先在软件浏览器（browser_profile）里登录 open.bigmodel.cn。
内部接口均带 authorization: Bearer <JWT>，令牌从页面请求头捕获。
"""

import datetime
import json
import re

import browser_sync
from playwright.sync_api import sync_playwright

ZHIPU_URL = "https://open.bigmodel.cn/console/overview"
API_ACCOUNT = "/api/biz/account/query-customer-account-report"
API_DAILY = "/api/finance/expenseBill/expenseBillListByDay"


def _parse_zhipu_daily(data):
    """解析 expenseBillListByDay 响应为逐日记录列表；无数据返回 []。

    每条记录只统计每日消费金额（智谱无公开的 token 逐日明细字段，金额单位为元）。
    """
    records = []
    if not isinstance(data, dict):
        return records
    rows = data.get("rows") or []
    for it in rows:
        if not isinstance(it, dict):
            continue
        date = (it.get("billingDate") or it.get("consumeDate") or it.get("billDate")
                or it.get("date") or it.get("day") or it.get("billingMonth"))
        cost = (it.get("consumeAmount")
                if it.get("consumeAmount") is not None else
                it.get("totalAmount")
                if it.get("totalAmount") is not None else
                it.get("consumeMoney")
                if it.get("consumeMoney") is not None else
                it.get("amount"))
        try:
            cost_f = float(cost) if cost is not None else 0.0
        except (TypeError, ValueError):
            cost_f = 0.0
        date_str = _fmt_date(date)
        if not date_str:
            continue
        records.append({
            "date": date_str, "cost": round(cost_f, 4), "tokens": 0, "requests": 0,
            "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
            "api_key": "", "name": "", "provider": "zhipu",
        })
    records.sort(key=lambda r: r["date"])
    return records


def _fmt_date(v):
    """把日期（时间戳/YYYY-MM/YYYY-MM-DD）转成 YYYY-MM-DD。"""
    if isinstance(v, (int, float)):
        ts = v / 1000.0 if v > 1e12 else v
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None
    s = str(v).strip().replace("/", "-")
    if re.match(r"^\d{4}-\d{2}$", s):
        return s + "-01"  # 仅月份：取当月 1 日（明细缺失时的兜底）
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return None


def fetch_zhipu_usage_daily(headless=True, timeout=60):
    """一次浏览器会话同步智谱账户信息 + 近3个月按日费用明细。

    返回 {"ok", "data": {balance, total_cost, today_consume, recharge, granted, token_total},
          "daily": [records], "error"}。
    """
    result = {"ok": False, "data": None, "daily": [], "error": "未获取到数据"}
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                info = {"tok": ""}

                def _on_req(r):
                    if "/api/biz/" in r.url and not info["tok"]:
                        h = r.headers
                        info["tok"] = h.get("authorization", "") or h.get("token", "") or ""

                page.on("request", _on_req)
                page.goto(ZHIPU_URL, timeout=timeout * 1000)
                page.wait_for_timeout(6000)
                if not info["tok"]:
                    result = {"ok": False, "error": "未获取到访问令牌"}
                    return result
                tok = json.dumps(info["tok"])

                def call(url):
                    js = ("async () => { const r = await fetch(%s, { headers: { 'authorization': %s } }); "
                          "return await r.json(); }" % (json.dumps(url), tok))
                    return page.evaluate(js)

                # 1) 账户报告（余额 / 消费）
                try:
                    acc = call(API_ACCOUNT)
                    d = acc.get("data") or {}
                    result["ok"] = True
                    result["data"] = {
                        "balance": "%.2f" % (float(d.get("availableBalance", 0) or 0)),
                        "recharge": "%.2f" % (float(d.get("rechargeAmount", 0) or 0)),
                        "granted": "%.2f" % (float(d.get("giveAmount", 0) or 0)),
                        "total_cost": "%.2f" % (float(d.get("totalSpendAmount", 0) or 0)),
                        "today_consume": ("%.2f" % float(d["todaySpendAmount"])
                                          if d.get("todaySpendAmount") is not None else None),
                    }
                except Exception as e:  # noqa: BLE001
                    result = {"ok": False, "error": f"账户报告失败: {e}"}
                    return result

                # 2) 近3个月按日费用明细
                daily = []
                now = datetime.datetime.now()
                for delta in range(3):
                    d0 = datetime.date(now.year, now.month, 1) - datetime.timedelta(days=delta * 31)
                    month = d0.strftime("%Y-%m")
                    url = (API_DAILY + "?billingMonth=" + month
                           + "&billStatus=&modelProductName=&paymentType=&pageNum=1&pageSize=50")
                    try:
                        res = call(url)
                        daily.extend(_parse_zhipu_daily(res))
                    except Exception:  # noqa: BLE001
                        pass
                # 去重（同一天保留一条）
                by_date = {}
                for r in daily:
                    by_date[r["date"]] = r
                result["daily"] = sorted(by_date.values(), key=lambda r: r["date"])
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return result


def fetch_zhipu_month(headless=True, timeout=60, year=None, month=None):
    """抓指定月份的按日费用明细（日历切月用）。返回逐日记录列表。"""
    now = datetime.datetime.now()
    y = year or now.year
    m = month or now.month
    month_str = f"{y:04d}-{m:02d}"
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=browser_sync.PROFILE_DIR, executable_path=browser_sync.EDGE_PATH,
                headless=headless, args=browser_sync._START_ARGS)
            try:
                page = ctx.new_page()
                info = {"tok": ""}

                def _on_req(r):
                    if "/api/biz/" in r.url and not info["tok"]:
                        h = r.headers
                        info["tok"] = h.get("authorization", "") or h.get("token", "") or ""

                page.on("request", _on_req)
                page.goto(ZHIPU_URL, timeout=timeout * 1000)
                page.wait_for_timeout(5000)
                if not info["tok"]:
                    return []
                url = (API_DAILY + "?billingMonth=" + month_str
                       + "&billStatus=&modelProductName=&paymentType=&pageNum=1&pageSize=50")
                js = ("async () => { const r = await fetch(%s, { headers: { 'authorization': %s } }); "
                      "return await r.json(); }" % (json.dumps(url), json.dumps(info["tok"])))
                res = page.evaluate(js)
                return _parse_zhipu_daily(res)
            finally:
                ctx.close()
    except Exception:  # noqa: BLE001
        return []
