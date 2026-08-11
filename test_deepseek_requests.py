# -*- coding: utf-8 -*-
"""DeepSeek 请求次数修复测试：请求次数/Token 以官方页面统计卡为准（amount 接口偏少）。"""
import browser_sync  # noqa: E402


def fake_api_json(headless, timeout, path, params=None):
    """模拟 amount 接口：REQUEST 合计 4080，比官方页面 5417 偏少。"""
    if path == "/users/get_user_summary":
        return {"data": {"biz_data": {
            "normal_wallets": [{"balance": 10}],
            "total_costs": [{"amount": 5}],
        }}}
    if path == "/usage/by_api_key/amount":
        return {"data": {"biz_data": {"series": [
            {"model": "deepseek-v4-flash",
             "buckets": [{"time": 1786406400, "usage": {
                 "REQUEST": 4077, "RESPONSE_TOKEN": 100,
                 "PROMPT_CACHE_HIT_TOKEN": 200, "PROMPT_CACHE_MISS_TOKEN": 300}}]},
            {"model": "deepseek-v4-pro",
             "buckets": [{"time": 1786406400, "usage": {
                 "REQUEST": 3, "RESPONSE_TOKEN": 100,
                 "PROMPT_CACHE_HIT_TOKEN": 200, "PROMPT_CACHE_MISS_TOKEN": 300}}]},
        ]}}}
    return None


def test_usage_uses_page_requests():
    orig_api = browser_sync._api_json
    orig_tok = browser_sync._page_tokens_cached
    orig_req = browser_sync._page_requests_cached
    browser_sync._api_json = fake_api_json
    browser_sync._page_tokens_cached = lambda *a, **k: 1460537082
    browser_sync._page_requests_cached = lambda *a, **k: 5417
    try:
        r = browser_sync.fetch_deepseek_usage(headless=True, timeout=30)
        assert r.get("ok"), r
        # 请求次数用官方页面 5417，而不是 amount 的 4080
        assert r["data"]["requests"] == "5417", r["data"]
        # Token 用官方页面值
        assert r["data"]["tokens"] == "1460537082", r["data"]
    finally:
        browser_sync._api_json = orig_api
        browser_sync._page_tokens_cached = orig_tok
        browser_sync._page_requests_cached = orig_req


def test_usage_fallback_to_amount():
    """无页面缓存时，请求次数回退 amount 接口汇总（不报错）。"""
    orig_api = browser_sync._api_json
    orig_tok = browser_sync._page_tokens_cached
    orig_req = browser_sync._page_requests_cached
    browser_sync._api_json = fake_api_json
    browser_sync._page_tokens_cached = lambda *a, **k: None
    browser_sync._page_requests_cached = lambda *a, **k: None
    try:
        r = browser_sync.fetch_deepseek_usage(headless=True, timeout=30)
        assert r.get("ok"), r
        assert r["data"]["requests"] == "4080", r["data"]  # amount 近30天汇总
    finally:
        browser_sync._api_json = orig_api
        browser_sync._page_tokens_cached = orig_tok
        browser_sync._page_requests_cached = orig_req


if __name__ == "__main__":
    test_usage_uses_page_requests()
    test_usage_fallback_to_amount()
    print("PASS: DeepSeek 请求次数测试通过")
