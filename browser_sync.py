# -*- coding: utf-8 -*-
"""浏览器同步：通过 DeepSeek 页面内部接口获取官方真实数据。

优化：首次从浏览器获取访问令牌并缓存到本地，之后直接用 HTTP 请求
调用内部接口（余额 / 逐日 / 小时数据），不再每次都启动浏览器，同步秒级完成。
全程本地运行，数据不离开本机。
"""

import datetime
import json
import os
import re
import threading

import requests
from playwright.sync_api import sync_playwright

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".model_balance", "browser_profile")
TOKEN_CACHE = os.path.join(os.path.expanduser("~"), ".model_balance", "api_token.json")
USAGE_URL = "https://platform.deepseek.com/usage"
API_BASE = "https://platform.deepseek.com/api/v0"

_START_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--disable-background-networking",
]

# 全局浏览器串行锁：Kimi/智谱/DeepSeek 等都用同一个 browser_profile，
# 同一时刻只允许一个 playwright 浏览器会话，避免 profile 冲突导致进程被强杀。
_BROWSER_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 令牌缓存
# ---------------------------------------------------------------------------

def _load_cred():
    try:
        with open(TOKEN_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("token", ""), (d.get("cookies") or {})
    except Exception:
        return "", {}


def _save_cred(token, cookies):
    try:
        os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
        with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
            json.dump({"token": token, "cookies": cookies}, f)
    except Exception:
        pass


def _fetch_token(headless=True, timeout=60):
    """开浏览器获取访问令牌和登录 cookie（并缓存）。"""
    token = ""
    cookies = {}
    with _BROWSER_LOCK:
        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR, executable_path=EDGE_PATH,
                    headless=headless, args=_START_ARGS,
                )
                try:
                    page = ctx.new_page()
                    tok = {"t": ""}

                    def _on_req(req):
                        if "usage/by_api_key/amount" in req.url and not tok["t"]:
                            tok["t"] = req.headers.get("authorization", "")

                    page.on("request", _on_req)
                    page.goto(USAGE_URL, timeout=timeout * 1000)
                    page.wait_for_timeout(5000)
                    token = tok["t"]
                    try:
                        for c in ctx.cookies("https://platform.deepseek.com"):
                            cookies[c["name"]] = c["value"]
                    except Exception:
                        pass
                finally:
                    ctx.close()
        except Exception:
            pass
    if token:
        _save_cred(token, cookies)
    return token


def _ensure_token(headless=True, timeout=60):
    token, _ = _load_cred()
    if token:
        return token
    return _fetch_token(headless, timeout)


def _headers():
    """构造带令牌 + cookie 的请求头（绕过反爬）。"""
    token, cookies = _load_cred()
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Authorization": token,
        "Cookie": cookie_str,
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"),
        "Referer": USAGE_URL,
        "Origin": "https://platform.deepseek.com",
        "Accept": "application/json",
    }


def _api_json(headless, timeout, path, params=None):
    """带令牌请求内部接口；令牌失效时重取一次。返回 dict 或 None。"""
    headers = _headers()
    if not headers["Authorization"]:
        if not _fetch_token(headless, timeout):
            return None
        headers = _headers()
    for attempt in range(2):
        try:
            r = requests.get(API_BASE + path, headers=headers, params=params, timeout=timeout)
            if r.status_code in (401, 403, 429):
                # 令牌/cookie 失效，重取一次
                _fetch_token(headless, timeout)
                headers = _headers()
                continue
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        break
    return None


def _day_bounds(start=None, end=None):
    """返回 (start, end) 整点对齐的时间戳；缺省近30天。"""
    if start is None or end is None:
        now = datetime.datetime.now()
        end = int(datetime.datetime(now.year, now.month, now.day).timestamp())
        start = end - 30 * 86400
    return start, end


# ---------------------------------------------------------------------------
# 官方页面 Token（权威口径，带本地缓存）
# ---------------------------------------------------------------------------

TOKEN_PAGE_CACHE = os.path.join(os.path.expanduser("~"), ".model_balance", "tokens_cache.json")


def _page_tokens_cached(max_age=None):
    """读取官方页面 Token 缓存（权威口径），**不启动浏览器**。
    默认(max_age=None)时任意缓存均返回；指定 max_age 时仅新鲜度内返回。"""
    try:
        with open(TOKEN_PAGE_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        val = d.get("tokens")
        ts = d.get("ts", 0)
        if val is not None:
            if max_age is None or (datetime.datetime.now().timestamp() - ts) < max_age:
                return val
    except Exception:
        pass
    return None


def _page_requests_cached(max_age=None):
    """读取官方页面「API 请求次数」缓存（权威口径），**不启动浏览器**。"""
    try:
        with open(TOKEN_PAGE_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        val = d.get("requests")
        ts = d.get("ts", 0)
        if val is not None:
            if max_age is None or (datetime.datetime.now().timestamp() - ts) < max_age:
                return val
    except Exception:
        pass
    return None


def _fetch_page_tokens(headless=True, timeout=60, max_age=300):
    """抓官方用量页的 Tokens + API 请求次数（权威口径），带本地缓存。

    官方页面统计卡（顶部：消费金额 / API 请求次数 / Tokens）与 amount 接口
    口径不一致（amount 的请求数偏少），一律以页面为准。
    """
    try:
        with open(TOKEN_PAGE_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        val = d.get("tokens")
        ts = d.get("ts", 0)
        if val is not None and (datetime.datetime.now().timestamp() - ts) < max_age:
            return val
    except Exception:
        pass

    tokens = None
    requests = None
    models = None
    with _BROWSER_LOCK:
        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=PROFILE_DIR, executable_path=EDGE_PATH,
                    headless=headless, args=_START_ARGS,
                )
                try:
                    page = ctx.new_page()
                    page.goto(USAGE_URL, timeout=timeout * 1000)
                    page.wait_for_timeout(8000)
                    text = page.inner_text("body")
                    m = re.search(r"Tokens\s*\n?\s*([\d,]+)", text)
                    if m:
                        tokens = int(m.group(1).replace(",", ""))
                    mr = re.search(r"API 请求次数\s*\n?\s*([\d,]+)", text)
                    if mr:
                        requests = int(mr.group(1).replace(",", ""))
                    # 各模型明细也从页面抓（总数与明细一致，避免与 amount 接口混用）
                    models = _parse_page_models(text)
                finally:
                    ctx.close()
        except Exception:
            pass

    if tokens is not None or requests is not None or models:
        try:
            os.makedirs(os.path.dirname(TOKEN_PAGE_CACHE), exist_ok=True)
            with open(TOKEN_PAGE_CACHE, "w", encoding="utf-8") as f:
                json.dump({"tokens": tokens, "requests": requests, "models": models,
                           "ts": datetime.datetime.now().timestamp()}, f)
        except Exception:
            pass
    return tokens


def _parse_page_models(text):
    """从官方页面文本解析各模型的请求数与 Token。

    页面结构（每模型一块）：
        deepseek-v4-flash
        API 请求次数
        5,653
        Tokens
        1,515,509,670
    返回 [{"model", "requests", "tokens"}, ...]；解析失败返回 []。
    """
    lines = [l.strip() for l in text.split("\n")]
    out = []
    for i, l in enumerate(lines):
        if "deepseek" not in l.lower():
            continue
        if i + 1 >= len(lines) or lines[i + 1] != "API 请求次数":
            continue
        try:
            req = int(lines[i + 2].replace(",", ""))
        except (ValueError, IndexError):
            continue
        tok = 0
        for j in range(i + 3, min(i + 8, len(lines))):
            if lines[j] == "Tokens" and j + 1 < len(lines):
                try:
                    tok = int(lines[j + 1].replace(",", ""))
                except (ValueError, IndexError):
                    tok = 0
                break
        out.append({"model": l, "requests": req, "tokens": tok})
    return out


def _page_models_cached(max_age=None):
    """读取官方页面模型明细缓存（权威口径），**不启动浏览器**。"""
    try:
        with open(TOKEN_PAGE_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        val = d.get("models")
        ts = d.get("ts", 0)
        if val:
            if max_age is None or (datetime.datetime.now().timestamp() - ts) < max_age:
                return val
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 概览（余额 / 累计消费 / 请求 / token / 模型）
# ---------------------------------------------------------------------------

def fetch_deepseek_usage(headless=True, timeout=60):
    try:
        s = _api_json(headless, timeout, "/users/get_user_summary")
        biz = ((s or {}).get("data") or {}).get("biz_data") or {}
        balance = None
        wallets = biz.get("normal_wallets") or []
        if wallets:
            try:
                balance = float(wallets[0].get("balance", 0))
            except (TypeError, ValueError):
                pass
        total_cost = None
        costs = biz.get("total_costs") or []
        if costs:
            try:
                total_cost = float(costs[0].get("amount", 0))
            except (TypeError, ValueError):
                pass

        start, end = _day_bounds()
        q = {"start": start, "end": end, "tz": 28800}
        amt = _api_json(headless, timeout, "/usage/by_api_key/amount", params=q)
        amt_biz = ((amt or {}).get("data") or {}).get("biz_data") or {}
        requests_total = 0
        tokens_total = 0
        models = {}
        for s in amt_biz.get("series", []):
            model = s.get("model", "")
            mreq = 0
            mtok = 0
            for b in s.get("buckets", []):
                u = b.get("usage", {}) or {}
                mreq += u.get("REQUEST", 0) or 0
                mtok += ((u.get("RESPONSE_TOKEN", 0) or 0)
                         + (u.get("PROMPT_CACHE_HIT_TOKEN", 0) or 0)
                         + (u.get("PROMPT_CACHE_MISS_TOKEN", 0) or 0))
            requests_total += mreq
            tokens_total += mtok
            models[model] = {"requests": mreq, "tokens": mtok}

        # 官方页面统计卡是权威口径（amount 接口的请求数/Token 均偏少），
        # 用它覆盖 amount 汇总；失败则用 amount。
        # 优先用本地缓存（不启动浏览器，避免同步卡住）；后台另行刷新
        page_tokens = _page_tokens_cached()
        if page_tokens is not None:
            tokens_total = page_tokens
        page_requests = _page_requests_cached()
        if page_requests is not None:
            requests_total = page_requests
        # 模型明细同样以官方页面为准，保证总数 = 明细合计（与官网一致）
        page_models = _page_models_cached()
        if page_models:
            models = {m["model"]: {"requests": m["requests"], "tokens": m["tokens"]}
                      for m in page_models}

        data = {
            "balance": f"{balance:.2f}" if balance is not None else "?",
            "total_cost": f"{total_cost:.2f}" if total_cost is not None else "?",
            "requests": str(requests_total),
            "tokens": str(tokens_total),
            "models": [{"model": k, "requests": v["requests"], "tokens": v["tokens"]}
                       for k, v in models.items()],
        }
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": f"同步失败: {e.__class__.__name__}: {str(e)[:100]}"}


# ---------------------------------------------------------------------------
# 逐日数据
# ---------------------------------------------------------------------------

def fetch_deepseek_daily(headless=True, timeout=60, start=None, end=None):
    start, end = _day_bounds(start, end)
    params = {"start": start, "end": end, "tz": 28800}
    amt = _api_json(headless, timeout, "/usage/by_api_key/amount", params=params)
    cost = _api_json(headless, timeout, "/usage/by_api_key/cost", params=params)
    records = _parse_daily({"amount": amt, "cost": cost})
    if not records:
        return {"ok": False, "error": "未解析到逐日数据"}
    return {"ok": True, "data": records}


def _parse_daily(data):
    amt = data.get("amount") or {}
    cost = data.get("cost") or {}
    amt_data = (amt.get("data") or {}) if isinstance(amt, dict) else {}
    cost_data = (cost.get("data") or {}) if isinstance(cost, dict) else {}
    amt_biz = (amt_data.get("biz_data") or {}) if isinstance(amt_data, dict) else {}
    cost_biz = (cost_data.get("biz_data") or {}) if isinstance(cost_data, dict) else {}

    keys = {}
    for s in amt_biz.get("series", []):
        kid = (s.get("api_key") or {}).get("tracking_id") or "?"
        name = (s.get("api_key") or {}).get("name") or kid
        info = keys.setdefault(kid, {"name": name, "days": {}})
        for b in s.get("buckets", []):
            try:
                date = datetime.datetime.fromtimestamp(b.get("time")).strftime("%Y-%m-%d")
            except Exception:
                continue
            u = b.get("usage", {}) or {}
            day = info["days"].setdefault(date, {
                "cost": 0.0, "tokens": 0, "requests": 0,
                "cache_hit": 0, "cache_miss": 0,
            })
            day["tokens"] += ((u.get("RESPONSE_TOKEN", 0) or 0)
                              + (u.get("PROMPT_CACHE_HIT_TOKEN", 0) or 0)
                              + (u.get("PROMPT_CACHE_MISS_TOKEN", 0) or 0))
            day["requests"] += u.get("REQUEST", 0) or 0
            day["cache_hit"] += u.get("PROMPT_CACHE_HIT_TOKEN", 0) or 0
            day["cache_miss"] += u.get("PROMPT_CACHE_MISS_TOKEN", 0) or 0

    for d in cost_biz.get("data", []):
        for s in d.get("series", []):
            kid = (s.get("api_key") or {}).get("tracking_id") or "?"
            if kid not in keys:
                continue
            info = keys[kid]
            for b in s.get("buckets", []):
                try:
                    date = datetime.datetime.fromtimestamp(b.get("time")).strftime("%Y-%m-%d")
                except Exception:
                    continue
                day = info["days"].setdefault(date, {
                    "cost": 0.0, "tokens": 0, "requests": 0,
                    "cache_hit": 0, "cache_miss": 0,
                })
                try:
                    day["cost"] += float(b.get("cost", 0) or 0)
                except (TypeError, ValueError):
                    pass

    records = []
    for kid, info in keys.items():
        for date, day in info["days"].items():
            total_in = day["cache_hit"] + day["cache_miss"]
            records.append({
                "api_key": kid,
                "name": info["name"],
                "date": date,
                "cost": round(day["cost"], 4),
                "tokens": int(day["tokens"]),
                "requests": int(day["requests"]),
                "cache_hit": int(day["cache_hit"]),
                "cache_miss": int(day["cache_miss"]),
                "hit_rate": round(day["cache_hit"] / total_in, 4) if total_in > 0 else 0.0,
            })
    records.sort(key=lambda r: (r["name"], r["date"]))
    return records


# ---------------------------------------------------------------------------
# 小时数据
# ---------------------------------------------------------------------------

def fetch_hourly(date_str, headless=True, timeout=60):
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return {"ok": False, "error": "日期格式应为 YYYY-MM-DD"}
    start = int(dt.timestamp())
    end = start + 86400
    params = {"start": start, "end": end, "tz": 28800}
    amt = _api_json(headless, timeout, "/usage/by_api_key/amount", params=params)
    cost = _api_json(headless, timeout, "/usage/by_api_key/cost", params=params)
    records = _parse_hourly({"amount": amt, "cost": cost})
    if not records:
        return {"ok": False, "error": "未解析到小时数据"}
    return {"ok": True, "data": records}


def _parse_hourly(data):
    amt = data.get("amount") or {}
    cost = data.get("cost") or {}
    amt_data = (amt.get("data") or {}) if isinstance(amt, dict) else {}
    cost_data = (cost.get("data") or {}) if isinstance(cost, dict) else {}
    amt_biz = (amt_data.get("biz_data") or {}) if isinstance(amt_data, dict) else {}
    cost_biz = (cost_data.get("biz_data") or {}) if isinstance(cost_data, dict) else {}

    hours = {}
    for s in amt_biz.get("series", []):
        for b in s.get("buckets", []):
            try:
                hour = datetime.datetime.fromtimestamp(b.get("time")).hour
            except Exception:
                continue
            u = b.get("usage", {}) or {}
            h = hours.setdefault(hour, {"tokens": 0, "cost": 0.0, "requests": 0,
                                        "cache_hit": 0, "cache_miss": 0})
            h["tokens"] += ((u.get("RESPONSE_TOKEN", 0) or 0)
                            + (u.get("PROMPT_CACHE_HIT_TOKEN", 0) or 0)
                            + (u.get("PROMPT_CACHE_MISS_TOKEN", 0) or 0))
            h["requests"] += u.get("REQUEST", 0) or 0
            h["cache_hit"] += u.get("PROMPT_CACHE_HIT_TOKEN", 0) or 0
            h["cache_miss"] += u.get("PROMPT_CACHE_MISS_TOKEN", 0) or 0

    for d in cost_biz.get("data", []):
        for s in d.get("series", []):
            for b in s.get("buckets", []):
                try:
                    hour = datetime.datetime.fromtimestamp(b.get("time")).hour
                except Exception:
                    continue
                h = hours.setdefault(hour, {"tokens": 0, "cost": 0.0, "requests": 0,
                                            "cache_hit": 0, "cache_miss": 0})
                try:
                    h["cost"] += float(b.get("cost", 0) or 0)
                except (TypeError, ValueError):
                    pass

    records = []
    for hour in range(24):
        h = hours.get(hour, {"tokens": 0, "cost": 0.0, "requests": 0,
                             "cache_hit": 0, "cache_miss": 0})
        total_in = h["cache_hit"] + h["cache_miss"]
        records.append({
            "hour": hour,
            "tokens": int(h["tokens"]),
            "cost": round(h["cost"], 4),
            "requests": int(h["requests"]),
            "cache_hit": int(h["cache_hit"]),
            "cache_miss": int(h["cache_miss"]),
            "hit_rate": round(h["cache_hit"] / total_in, 4) if total_in > 0 else 0.0,
        })
    return records
