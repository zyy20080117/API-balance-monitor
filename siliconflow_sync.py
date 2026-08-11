# -*- coding: utf-8 -*-
"""硅基流动（cloud.siliconflow.cn）浏览器同步：账户余额/消费 + 按日费用明细。

需要先在软件浏览器（browser_profile）里登录 cloud.siliconflow.cn。
认证：cookie（同源 fetch 自动带）+ x-subject-id 请求头（从页面请求或
iam-server subject/info/peek 响应获取）。金额单位为元。日期范围上限 60 天。
"""

import datetime
import json
import re

import browser_sync
from playwright.sync_api import sync_playwright

CONSOLE_URL = "https://cloud.siliconflow.cn/me/bills"
API_WALLET = "/walletd-server/api/v1/subject/profile/peek"
API_SUBJECT = "/iam-server/api/v1/subject/info/peek"
API_AGG = "/panel-server/api/v1/bill/aggregate_amount"
API_ALLOC = "/panel-server/api/v1/bill/items/allocation_aggregate"

TZ8 = datetime.timezone(datetime.timedelta(hours=8))


def _fmt_date(v):
    """把时间戳(ms/s)/'yyyy-MM-dd...' 统一成 yyyy-MM-dd（按 UTC+8）。"""
    if isinstance(v, (int, float)):
        ts = v / 1000.0 if v > 1e12 else v
        try:
            return datetime.datetime.fromtimestamp(ts, TZ8).strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _parse_daily(data):
    """解析 allocation_aggregate 响应为逐日记录列表；无数据返回 []。

    列表项按 timeAggregationDimension=day 聚合并按 API Key/模型分摊，
    同一天多条时累计净金额 netAmount（实际扣费）。
    """
    records = []
    if not isinstance(data, dict):
        return records
    d = data.get("data") or {}
    items = d.get("list")
    if not isinstance(items, list):
        return records
    by_date = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        date = _fmt_date(it.get("timeDimension"))
        if not date:
            continue
        net = it.get("netAmount")
        if net is None:
            net = it.get("grossAmount")
        try:
            cost = float(net) if net is not None else 0.0
        except (TypeError, ValueError):
            cost = 0.0
        day = by_date.setdefault(date, {"cost": 0.0})
        day["cost"] += cost
    for date, day in by_date.items():
        records.append({
            "date": date, "cost": round(day["cost"], 4), "tokens": 0, "requests": 0,
            "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
            "api_key": "", "name": "", "provider": "siliconflow",
        })
    records.sort(key=lambda r: r["date"])
    return records


def fetch_siliconflow_usage_daily(headless=True, timeout=90):
    """一次浏览器会话同步硅基流动账户信息 + 近60天按日费用明细。

    返回 {"ok", "data": {balance, total_cost, today_consume, recharge},
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
                sid = {"v": ""}

                def _on_req(r):
                    if "cloud.siliconflow.cn" in r.url and not sid["v"]:
                        sid["v"] = r.headers.get("x-subject-id", "")

                page.on("request", _on_req)
                page.goto(CONSOLE_URL, timeout=timeout * 1000)
                page.wait_for_timeout(6000)
                if not sid["v"]:
                    # 回退：从 subject/info/peek 响应取 subjectId
                    try:
                        js = ("async (u) => { const r = await fetch(u); return await r.json(); }")
                        r = page.evaluate(js, "https://cloud.siliconflow.cn" + API_SUBJECT
                                          + "?attrs=s%3Ainfo%3AinvitationCode&attrs=s%3Atier%3Acomputed")
                        sid["v"] = ((r or {}).get("data") or {}).get("subjectId", "")
                    except Exception:  # noqa: BLE001
                        pass
                if not sid["v"]:
                    result = {"ok": False, "error": "未获取到账户标识（请确认已在浏览器登录硅基流动）"}
                    return result
                sh = json.dumps(sid["v"])

                def call(url):
                    js = ("async (u) => { const r = await fetch(u, "
                          "{ headers: { 'x-subject-id': %s } }); return await r.json(); }" % sh)
                    return page.evaluate(js, url)

                # 1) 账户余额/累计消费/充值
                try:
                    w = call("https://cloud.siliconflow.cn" + API_WALLET)
                    fi = ((w or {}).get("data") or {}).get("financialInfo") or {}
                    result["ok"] = True
                    result["data"] = {
                        "balance": "%.2f" % float(fi.get("balance") or 0),
                        "total_cost": "%.2f" % float(fi.get("used") or 0),
                        "today_consume": None,
                        "recharge": "%.2f" % float(fi.get("recharged") or 0),
                    }
                except Exception as e:  # noqa: BLE001
                    result = {"ok": False, "error": f"账户余额失败: {e}"}
                    return result

                # 2) 每日用量（按天聚合，近60天，自动翻页）
                now = datetime.datetime.now(TZ8)
                today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = now.replace(hour=23, minute=59, second=59, microsecond=999000)
                start = today0 - datetime.timedelta(days=59)
                base = (f"type=3&aggregateByUnit=true&aggregateByApiKey=true"
                        f"&aggregateByModelName=true&timeAggregationDimension=day"
                        f"&pageSize=50"
                        f"&startTime={int(start.timestamp() * 1000)}"
                        f"&endTime={int(today_end.timestamp() * 1000)}")
                daily = []
                for current in range(1, 11):  # 最多翻 10 页
                    url = ("https://cloud.siliconflow.cn" + API_ALLOC + "?" + base
                           + f"&current={current}")
                    try:
                        res = call(url)
                        d = (res or {}).get("data") or {}
                        items = d.get("list") or []
                        if isinstance(items, list):
                            daily.extend(items)
                        total = (d.get("pagination") or {}).get("total") or 0
                        if len(daily) >= total or len(items) < 50:
                            break
                    except Exception:  # noqa: BLE001
                        break
                result["daily"] = _parse_daily({"data": {"list": daily}})

                # 3) 今日消费：优先官网「今日」汇总口径
                try:
                    agg = call("https://cloud.siliconflow.cn" + API_AGG
                               + f"?startTime={int(today0.timestamp() * 1000)}"
                               + f"&endTime={int(today_end.timestamp() * 1000)}")
                    ad = (agg or {}).get("data") or {}
                    tdy = ad.get("netAmount")
                    if tdy is not None:
                        result["data"]["today_consume"] = "%.2f" % float(tdy)
                except Exception:  # noqa: BLE001
                    pass

                # 累计消费优先用 daily 累计（口径与逐日明细一致）
                if result["daily"]:
                    result["data"]["total_cost"] = "%.2f" % sum(r["cost"] for r in result["daily"])
                    tdy = today0.date().isoformat()
                    tc = next((r["cost"] for r in result["daily"] if r["date"] == tdy), None)
                    if tc is not None:
                        result["data"]["today_consume"] = "%.2f" % tc
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return result
