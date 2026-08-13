# -*- coding: utf-8 -*-
"""OpenRouter 同步逻辑测试：analytics 解析 + 余额 HTTP + 组装。不启动浏览器。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openrouter_sync  # noqa: E402


def test_parse_analytics():
    data = {"data": {"data": [
        {"date": "2026-08-11", "total_usage": 0.5, "request_count": 10,
         "tokens_prompt": 100, "tokens_completion": 200},
        {"date": "2026-08-12", "total_usage": 1.25, "request_count": 20,
         "tokens_prompt": 300, "tokens_completion": 400},
    ]}}
    records = openrouter_sync._parse_analytics(data)
    assert len(records) == 2, records
    assert records[0]["date"] == "2026-08-11"
    assert records[0]["cost"] == 0.5
    assert records[0]["requests"] == 10
    assert records[0]["tokens"] == 300
    assert records[0]["provider"] == "openrouter"
    assert records[1]["cost"] == 1.25
    # 空数据
    assert openrouter_sync._parse_analytics({"data": {"data": []}}) == []
    assert openrouter_sync._parse_analytics(None) == []
    assert openrouter_sync._parse_analytics({"data": {}}) == []


def test_parse_analytics_missing_fields():
    """字段缺失时容错为 0，不报错。"""
    data = {"data": {"data": [{"date": "2026-08-11"}]}}
    records = openrouter_sync._parse_analytics(data)
    assert records[0]["cost"] == 0.0
    assert records[0]["requests"] == 0
    assert records[0]["tokens"] == 0


def test_fetch_usage_daily():
    """余额来自 HTTP credits，daily 来自 analytics，total_cost 用 daily 累计。"""
    orig_credits = openrouter_sync._fetch_credits
    orig_analytics = openrouter_sync._fetch_analytics_daily
    openrouter_sync._fetch_credits = lambda key: {"total_credits": "10.00", "total_usage": "2.00"}
    openrouter_sync._fetch_analytics_daily = lambda *a, **k: [
        {"date": "2026-08-12", "cost": 2.0, "tokens": 100, "requests": 5}]
    try:
        r = openrouter_sync.fetch_openrouter_usage_daily("sk-test")
        assert r.get("ok"), r
        assert r["data"]["balance"] == "8.00", r["data"]
        assert r["data"]["total_cost"] == "2.00", r["data"]
        assert len(r["daily"]) == 1
    finally:
        openrouter_sync._fetch_credits = orig_credits
        openrouter_sync._fetch_analytics_daily = orig_analytics


def test_fetch_usage_no_credits():
    """无 API Key 或余额接口失败时，ok=False 且 error 明确。"""
    orig_credits = openrouter_sync._fetch_credits
    orig_analytics = openrouter_sync._fetch_analytics_daily
    openrouter_sync._fetch_credits = lambda key: None
    openrouter_sync._fetch_analytics_daily = lambda *a, **k: None
    try:
        r = openrouter_sync.fetch_openrouter_usage_daily("")
        assert not r.get("ok"), r
        assert r.get("error")
    finally:
        openrouter_sync._fetch_credits = orig_credits
        openrouter_sync._fetch_analytics_daily = orig_analytics


def test_parse_hourly():
    """analytics granularity=hour 解析为 0-23 小时记录。"""
    data = {"data": {"data": [
        {"date": "2026-08-12T09:00:00.000Z", "total_usage": 0.1, "request_count": 3,
         "tokens_prompt": 100, "tokens_completion": 200},
        {"date": "2026-08-12T14:00:00.000Z", "total_usage": 0.2, "request_count": 5,
         "tokens_prompt": 300, "tokens_completion": 400},
    ]}}
    records = openrouter_sync._parse_hourly(data)
    assert len(records) == 24, len(records)
    assert records[9]["tokens"] == 300
    assert records[9]["cost"] == 0.1
    assert records[9]["requests"] == 3
    assert records[14]["tokens"] == 700
    assert records[14]["requests"] == 5
    assert records[0]["tokens"] == 0
    # 空数据 → 24 条全 0
    empty = openrouter_sync._parse_hourly({"data": {"data": []}})
    assert len(empty) == 24 and empty[0]["tokens"] == 0


def test_openrouter_short_timeout():
    """OpenRouter（国外站点）使用 5s 短超时，连接失败时快速返回，不长时间「查询中」。"""
    import providers
    import requests
    calls = []
    orig_get = requests.get

    def fake_get(url, headers=None, timeout=None):
        calls.append(timeout)
        raise requests.ConnectionError("模拟连接超时")

    requests.get = fake_get
    try:
        r = providers.check_openrouter("sk-test", "https://openrouter.ai/api/v1")
        assert not r.get("ok"), r
        assert calls and calls[0] == (5, 5), calls
    finally:
        requests.get = orig_get


if __name__ == "__main__":
    test_parse_analytics()
    test_parse_analytics_missing_fields()
    test_fetch_usage_daily()
    test_fetch_usage_no_credits()
    test_parse_hourly()
    test_openrouter_short_timeout()
    print("PASS: OpenRouter 同步逻辑测试通过")
