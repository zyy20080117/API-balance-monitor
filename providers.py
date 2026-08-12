# -*- coding: utf-8 -*-
"""各模型服务商的余额查询逻辑"""

import requests

TIMEOUT = 15
# OpenRouter 是国外站点，连接慢/不稳：用短超时快速失败，避免长时间「查询中」
OR_TIMEOUT = 5


class ProviderError(Exception):
    pass


# ---------------------------------------------------------------------------
# 通用 HTTP 辅助
# ---------------------------------------------------------------------------

def _http_get(url, api_key, timeout=TIMEOUT):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    # 连接与读取均限时，避免连接挂起导致长时间等待
    return requests.get(url, headers=headers, timeout=(timeout, timeout))


def _http_err(r):
    """把非 2xx 的响应转成可读错误信息。"""
    code = r.status_code
    text = (r.text or "").strip()
    if text:
        text = " " + text[:160]
    if code in (401, 403):
        return {"ok": False, "error": "API Key 无效或没有权限 (401/403)"}
    if code == 402:
        return {"ok": False, "error": "余额不足 (402)"}
    if code == 429:
        return {"ok": False, "error": "请求过于频繁 (429)"}
    return {"ok": False, "error": f"HTTP {code}{text}"}


def _req_err(e):
    """把网络异常转成可读错误信息。"""
    return {"ok": False, "error": f"无法连接服务器：{e.__class__.__name__}"}


def _json(r):
    """解析 JSON，失败时返回带响应的错误结果。"""
    try:
        return {"ok": True, "data": r.json()}
    except Exception:
        return {"ok": False, "error": "服务器返回的不是有效 JSON"}


def _num(v):
    """把数字字符串转 float，失败返回 None。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 各服务商查询函数。统一返回 dict：
#   {"ok": True, "value": str, "unit": str, "lines": [str,...], "badge": str}
#   {"ok": False, "error": str}
# ---------------------------------------------------------------------------

def check_deepseek(api_key, base_url):
    url = f"{base_url.rstrip('/')}/user/balance"
    try:
        r = _http_get(url, api_key)
    except requests.RequestException as e:
        return _req_err(e)
    if not r.ok:
        return _http_err(r)
    jr = _json(r)
    if not jr["ok"]:
        return jr
    j = jr["data"]
    infos = j.get("balance_infos") or []
    if not infos:
        return {"ok": False, "error": "未获取到余额信息"}
    inf = infos[0]
    cur = inf.get("currency", "CNY")
    total = inf.get("total_balance")
    lines = []
    if inf.get("topped_up_balance") is not None:
        lines.append(f"充值余额：{inf.get('topped_up_balance')}")
    if inf.get("granted_balance") is not None:
        lines.append(f"赠送余额：{inf.get('granted_balance')}")
    return {"ok": True, "value": total, "unit": cur, "lines": lines, "badge": "DeepSeek"}


def check_moonshot(api_key, base_url):
    url = f"{base_url.rstrip('/')}/v1/users/me/balance"
    try:
        r = _http_get(url, api_key)
    except requests.RequestException as e:
        return _req_err(e)
    if not r.ok:
        return _http_err(r)
    jr = _json(r)
    if not jr["ok"]:
        return jr
    j = jr["data"]
    data = j.get("data") or {}
    avail = data.get("available_balance")
    if avail is None:
        return {"ok": False, "error": f"未解析到余额：{str(j)[:120]}"}
    lines = []
    for k, label in (("cash_balance", "现金余额"), ("voucher_balance", "代金券")):
        if data.get(k) is not None:
            try:
                v = f"{float(data.get(k)):.2f}"
            except (TypeError, ValueError):
                v = data.get(k)
            lines.append(f"{label}：{v}")
    return {"ok": True, "value": avail, "unit": "CNY", "lines": lines, "badge": "Kimi"}


def check_siliconflow(api_key, base_url):
    url = f"{base_url.rstrip('/')}/v1/user/info"
    try:
        r = _http_get(url, api_key)
    except requests.RequestException as e:
        return _req_err(e)
    if not r.ok:
        return _http_err(r)
    jr = _json(r)
    if not jr["ok"]:
        return jr
    j = jr["data"]
    code = j.get("code")
    if code is not None and code != 20000 and code != 0 and code != 200:
        return {"ok": False, "error": j.get("message") or f"查询失败 (code={code})"}
    data = j.get("data") or {}
    balance = data.get("balance")
    if balance is None:
        return {"ok": False, "error": f"未解析到余额：{str(j)[:120]}"}
    lines = []
    if data.get("totalBalance") is not None:
        lines.append(f"总余额：{data.get('totalBalance')}")
    if data.get("chargeBalance") is not None:
        lines.append(f"充值余额：{data.get('chargeBalance')}")
    return {"ok": True, "value": balance, "unit": "CNY", "lines": lines, "badge": "硅基流动"}


def check_openrouter(api_key, base_url):
    url = f"{base_url.rstrip('/')}/credits"
    try:
        r = _http_get(url, api_key, timeout=OR_TIMEOUT)
    except requests.RequestException as e:
        return _req_err(e)
    if not r.ok:
        return _http_err(r)
    jr = _json(r)
    if not jr["ok"]:
        return jr
    j = jr["data"]
    data = j.get("data") or {}
    total = _num(data.get("total_credits"))
    used = _num(data.get("total_usage"))
    if total is None:
        return {"ok": False, "error": f"未解析到额度：{str(j)[:120]}"}
    remaining = total - used if used is not None else total
    lines = [f"总额度：{total:.2f} USD", f"已使用：{used:.2f} USD"] if used is not None else []
    return {"ok": True, "value": f"{remaining:.2f}", "unit": "USD", "lines": lines, "badge": "OpenRouter"}


def check_zhipu(api_key, base_url):
    url = f"{base_url.rstrip('/')}/balance"
    try:
        r = _http_get(url, api_key)
    except requests.RequestException as e:
        return _req_err(e)
    if r.status_code == 404:
        # 智谱开放平台不再提供公开的 HTTP 余额接口，余额/消费走浏览器同步
        return {"ok": False, "error": "余额与消费需点击「同步官方」查询（智谱无公开余额接口）"}
    if not r.ok:
        return _http_err(r)
    jr = _json(r)
    if not jr["ok"]:
        return jr
    j = jr["data"]
    if isinstance(j, dict) and j.get("error"):
        return {"ok": False, "error": str(j.get("error"))}
    balance = j.get("balance")
    if balance is None:
        return {"ok": False, "error": f"未解析到余额：{str(j)[:120]}"}
    lines = []
    if j.get("topped_up_balance") is not None:
        lines.append(f"充值余额：{j.get('topped_up_balance')}")
    if j.get("granted_balance") is not None:
        lines.append(f"赠送余额：{j.get('granted_balance')}")
    return {"ok": True, "value": balance, "unit": "CNY", "lines": lines, "badge": "智谱 GLM"}


def check_relay(api_key, base_url):
    """通用 OpenAI 兼容中转站（new-api / one-api 等）。

    依次尝试常见的余额接口路径，取第一个成功的。
    """
    base = base_url.rstrip("/") or "https://api.openai.com"
    candidates = [
        f"{base}/v1/dashboard/billing/credit_grants",
        f"{base}/dashboard/billing/credit_grants",
        f"{base}/v1/user/balance",
    ]
    last_err = None
    for url in candidates:
        try:
            r = _http_get(url, api_key)
        except requests.RequestException as e:
            last_err = _req_err(e)
            continue
        if r.status_code in (401, 403):
            # Key 无效，不用再试其它路径
            return _http_err(r)
        if not r.ok:
            last_err = _http_err(r)
            continue
        jr = _json(r)
        if not jr["ok"]:
            last_err = jr
            continue
        j = jr["data"]
        # OpenAI 计费端点格式
        avail = j.get("total_available")
        granted = j.get("total_granted")
        used = j.get("total_used")
        if avail is None and granted is not None and used is not None:
            avail = _num(granted) - _num(used) if _num(granted) is not None and _num(used) is not None else None
        if avail is not None:
            lines = []
            if granted is not None:
                lines.append(f"总额度：{granted}")
            if used is not None:
                lines.append(f"已使用：{used}")
            return {"ok": True, "value": avail, "unit": "", "lines": lines, "badge": "中转站"}
        # 某些站点用 {"balance": ..., "currency": ...}
        if j.get("balance") is not None:
            return {
                "ok": True,
                "value": j.get("balance"),
                "unit": j.get("currency") or "",
                "lines": [],
                "badge": "中转站",
            }
        last_err = {"ok": False, "error": f"未解析到余额：{str(j)[:120]}"}
    return last_err or {"ok": False, "error": "所有接口路径都失败了"}


# ---------------------------------------------------------------------------
# 服务商注册表
# ---------------------------------------------------------------------------

PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_base": "https://api.deepseek.com",
        "hint": "余额单位：元 (CNY)",
        "check": check_deepseek,
    },
    {
        "id": "moonshot",
        "name": "Kimi",
        "default_base": "https://api.moonshot.cn",
        "hint": "余额单位：元 (CNY)",
        "check": check_moonshot,
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "default_base": "https://api.siliconflow.cn",
        "hint": "余额单位：元 (CNY)",
        "check": check_siliconflow,
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM（BigModel）",
        "default_base": "https://open.bigmodel.cn/api/paas/v4",
        "hint": "余额单位：元 (CNY)",
        "check": check_zhipu,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "default_base": "https://openrouter.ai/api/v1",
        "hint": "余额单位：美元 (USD)",
        "check": check_openrouter,
    },
    {
        "id": "relay",
        "name": "通用中转站（OpenAI 兼容）",
        "default_base": "",
        "hint": "填写中转站地址，如 https://api.xxx.com",
        "check": check_relay,
    },
]

PROVIDER_MAP = {p["id"]: p for p in PROVIDERS}


def get_provider(pid):
    return PROVIDER_MAP.get(pid)


def check_account(provider_id, api_key, base_url):
    """对单个账号执行查询，返回统一结果 dict。"""
    p = get_provider(provider_id)
    if p is None:
        return {"ok": False, "error": f"未知服务商：{provider_id}"}
    if not api_key:
        return {"ok": False, "error": "未填写 API Key"}
    try:
        return p["check"](api_key, base_url or p["default_base"])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"查询出错：{e.__class__.__name__}: {e}"}
