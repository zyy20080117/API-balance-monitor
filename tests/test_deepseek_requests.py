# -*- coding: utf-8 -*-
"""DeepSeek 请求次数修复测试：请求次数/Token 以官方页面统计卡为准（amount 接口偏少）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    orig_mod = browser_sync._page_models_cached
    browser_sync._api_json = fake_api_json
    browser_sync._page_tokens_cached = lambda *a, **k: None
    browser_sync._page_requests_cached = lambda *a, **k: None
    browser_sync._page_models_cached = lambda *a, **k: None
    try:
        r = browser_sync.fetch_deepseek_usage(headless=True, timeout=30)
        assert r.get("ok"), r
        assert r["data"]["requests"] == "4080", r["data"]  # amount 近30天汇总
    finally:
        browser_sync._api_json = orig_api
        browser_sync._page_tokens_cached = orig_tok
        browser_sync._page_requests_cached = orig_req
        browser_sync._page_models_cached = orig_mod


def test_parse_page_models():
    """官方页面各模型明细解析：总数 = 明细合计。"""
    text = ("消费金额\n¥51.46\nAPI 请求次数\n5,656\nTokens\n1,515,581,188\n"
            "deepseek-v4-flash\nAPI 请求次数\n5,653\nTokens\n1,515,509,670\n"
            "deepseek-v4-pro\nAPI 请求次数\n3\nTokens\n71,518")
    models = browser_sync._parse_page_models(text)
    assert len(models) == 2, models
    m = {x["model"]: x for x in models}
    assert m["deepseek-v4-flash"]["requests"] == 5653, m
    assert m["deepseek-v4-flash"]["tokens"] == 1515509670, m
    assert m["deepseek-v4-pro"]["requests"] == 3, m
    # 总数与明细一致
    assert m["deepseek-v4-flash"]["requests"] + m["deepseek-v4-pro"]["requests"] == 5656


def test_usage_uses_page_models():
    """模型明细以官方页面为准，与总数同源（总数=明细），不再与 amount 混用。"""
    orig_api = browser_sync._api_json
    orig_tok = browser_sync._page_tokens_cached
    orig_req = browser_sync._page_requests_cached
    orig_mod = browser_sync._page_models_cached
    browser_sync._api_json = fake_api_json   # amount 明细 flash=4077（偏少）
    browser_sync._page_tokens_cached = lambda *a, **k: 1515581188
    browser_sync._page_requests_cached = lambda *a, **k: 5656
    browser_sync._page_models_cached = lambda *a, **k: [
        {"model": "deepseek-v4-flash", "requests": 5653, "tokens": 1515509670},
        {"model": "deepseek-v4-pro", "requests": 3, "tokens": 71518},
    ]
    try:
        r = browser_sync.fetch_deepseek_usage(headless=True, timeout=30)
        assert r.get("ok"), r
        models = {m["model"]: m for m in r["data"]["models"]}
        # 明细用页面值 5653（不是 amount 的 4077）
        assert models["deepseek-v4-flash"]["requests"] == 5653, r["data"]["models"]
        # 总数 = 明细合计（与官网一致）
        total = sum(m["requests"] for m in r["data"]["models"])
        assert total == int(r["data"]["requests"]) == 5656, r["data"]
    finally:
        browser_sync._api_json = orig_api
        browser_sync._page_tokens_cached = orig_tok
        browser_sync._page_requests_cached = orig_req
        browser_sync._page_models_cached = orig_mod


if __name__ == "__main__":
    test_usage_uses_page_requests()
    test_usage_fallback_to_amount()
    test_parse_page_models()
    test_usage_uses_page_models()
    print("PASS: DeepSeek 请求次数测试通过")
