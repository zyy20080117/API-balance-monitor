# -*- coding: utf-8 -*-
"""Kimi 累计消费兜底测试：use 只统计现金(=0)、today 含代金券(=1.84)时，
累计消费应提升到不小于今日消费，避免「今日>累计」矛盾。mock 浏览器。"""
import sys

sys.path.insert(0, r"c:/Users/13404/model_balance_app")
import kimi_sync  # noqa: E402


class FakePage:
    def __init__(self):
        self._h = {}

    def on(self, ev, cb):
        self._h[ev] = cb

    def goto(self, url, **k):
        # 触发请求（设置 tok/oid）与响应（organizationAccountInfo: use=0, today=1.84）
        class Req:
            url = "/api?oid=org123&endpoint=x"
            headers = {"authorization": "Bearer tok"}

        self._h["request"](Req())

        class R:
            url = "/api?endpoint=organizationAccountInfo"

            def json(self):
                return {"code": 0, "data": {"use": 0, "today_consume": 184000,
                                            "cur": 0, "voucher_cur": 1080232,
                                            "acc": 0, "voucher_acc": 1500000}}

        self._h["response"](R())

    def wait_for_timeout(self, ms):
        pass


class FakeCtx:
    def new_page(self):
        return FakePage()

    def close(self):
        pass


class FakeP:
    chromium = type("C", (), {"launch_persistent_context": lambda self, **k: FakeCtx()})()


class FakePlaywright:
    def __enter__(self):
        return FakeP()

    def __exit__(self, *a):
        return False


def test_kimi_total_cost_not_less_than_today():
    orig_pw = kimi_sync.sync_playwright
    orig_daily = kimi_sync._fetch_kimi_daily_via
    kimi_sync.sync_playwright = lambda: FakePlaywright()
    kimi_sync._fetch_kimi_daily_via = lambda *a, **k: []   # 无每日账单
    try:
        r = kimi_sync.fetch_kimi_usage_daily(headless=True, timeout=5)
        assert r.get("ok"), r
        assert r["data"]["today_consume"] == "1.84", r["data"]
        # 累计消费 = 充值+赠送-余额 = (0+15-0-10.80) = 4.20
        assert r["data"]["total_cost"] == "4.20", r["data"]
        assert float(r["data"]["total_cost"]) >= float(r["data"]["today_consume"])
    finally:
        kimi_sync.sync_playwright = orig_pw
        kimi_sync._fetch_kimi_daily_via = orig_daily


def test_kimi_total_cost_with_daily():
    """有每日账单时，累计用账单累计（含今日），仍不小于今日。"""
    orig_pw = kimi_sync.sync_playwright
    orig_daily = kimi_sync._fetch_kimi_daily_via
    kimi_sync.sync_playwright = lambda: FakePlaywright()

    def fake_daily(page, oid, tok, timeout):
        import datetime
        return [{"date": datetime.date.today().isoformat(), "cost": 1.84,
                 "tokens": 0, "requests": 0, "cache_hit": 0, "cache_miss": 0,
                 "hit_rate": 0.0, "api_key": "", "name": "", "provider": "moonshot"}]

    kimi_sync._fetch_kimi_daily_via = fake_daily
    try:
        r = kimi_sync.fetch_kimi_usage_daily(headless=True, timeout=5)
        assert r.get("ok"), r
        # daily 累计(1.84) < 充值+赠送-余额(4.20)，累计保持 4.20
        assert r["data"]["total_cost"] == "4.20", r["data"]
        assert r["data"]["today_consume"] == "1.84", r["data"]
    finally:
        kimi_sync.sync_playwright = orig_pw
        kimi_sync._fetch_kimi_daily_via = orig_daily


if __name__ == "__main__":
    test_kimi_total_cost_not_less_than_today()
    test_kimi_total_cost_with_daily()
    print("PASS: Kimi 累计消费兜底测试通过")
