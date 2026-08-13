# -*- coding: utf-8 -*-
"""Kimi 累计消费计算测试：累计消费 = 充值+赠送-当前余额（use 只统计现金不准），
且「累计消费 + 当前余额 = 代金券/充值总额」应恒成立。mock 浏览器。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kimi_sync  # noqa: E402

# 金额单位：接口返回 1e-5 元


def _mk_page(acc, voucher_acc, cur, voucher_cur, today):
    class FakePage:
        def __init__(self):
            self._h = {}

        def on(self, ev, cb):
            self._h[ev] = cb

        def goto(self, url, **k):
            class Req:
                url = "/api?oid=org123&endpoint=x"
                headers = {"authorization": "Bearer tok"}

            self._h["request"](Req())

            class R:
                url = "/api?endpoint=organizationAccountInfo"

                def json(self):
                    return {"code": 0, "data": {"use": 0, "today_consume": today,
                                                "cur": cur, "voucher_cur": voucher_cur,
                                                "acc": acc, "voucher_acc": voucher_acc}}

            self._h["response"](R())

        def wait_for_timeout(self, ms):
            pass

    return FakePage()


class FakeCtx:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page

    def close(self):
        pass


class FakeP:
    def __init__(self, page):
        self.chromium = type("C", (), {
            "launch_persistent_context": lambda self, **k: FakeCtx(page)})()


class FakePlaywright:
    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return FakeP(self._page)

    def __exit__(self, *a):
        return False


def _fetch(acc, voucher_acc, cur, voucher_cur, today, daily):
    """构造 Kimi 同步场景并返回结果。"""
    page = _mk_page(acc, voucher_acc, cur, voucher_cur, today)
    orig_pw = kimi_sync.sync_playwright
    orig_daily = kimi_sync._fetch_kimi_daily_via
    kimi_sync.sync_playwright = lambda: FakePlaywright(page)
    kimi_sync._fetch_kimi_daily_via = lambda *a, **k: daily
    try:
        return kimi_sync.fetch_kimi_usage_daily(headless=True, timeout=5)
    finally:
        kimi_sync.sync_playwright = orig_pw
        kimi_sync._fetch_kimi_daily_via = orig_daily


def test_balance_plus_cost_equals_granted():
    """无每日账单：累计消费=充值+赠送-余额，且 消费+余额=总额。"""
    # 余额 7.35 元(735000)，赠送 15 元(1500000)，今日 4.95 元(495000)
    r = _fetch(0, 1500000, 0, 735000, 495000, [])
    assert r.get("ok"), r
    assert r["data"]["balance"] == "7.35", r["data"]
    assert r["data"]["today_consume"] == "4.95", r["data"]
    total = float(r["data"]["total_cost"])
    bal = float(r["data"]["balance"])
    assert r["data"]["total_cost"] == "7.65", r["data"]
    # 消费 + 余额 = 总额 15（恒等式）
    assert abs(total + bal - 15.0) < 0.01, (total, bal)
    assert total >= float(r["data"]["today_consume"])


def test_daily_less_than_total_keeps_total():
    """有每日账单但累计小于 充值+赠送-余额 时，累计保持 充值+赠送-余额。"""
    import datetime
    daily = [{"date": datetime.date.today().isoformat(), "cost": 1.84,
              "tokens": 0, "requests": 0, "cache_hit": 0, "cache_miss": 0,
              "hit_rate": 0.0, "api_key": "", "name": "", "provider": "moonshot"}]
    # 余额 10.80(1080232)，赠送 15(1500000)
    r = _fetch(0, 1500000, 0, 1080232, 184000, daily)
    assert r.get("ok"), r
    # daily 累计 1.84 < 4.20（15-10.80）→ 累计保持 4.20
    assert r["data"]["total_cost"] == "4.20", r["data"]
    total = float(r["data"]["total_cost"])
    bal = float(r["data"]["balance"])
    assert abs(total + bal - 15.0) < 0.01, (total, bal)


def test_daily_greater_than_total_uses_daily():
    """每日账单累计比估算更大时（含历史），用账单累计（更完整）。"""
    import datetime
    today = datetime.date.today().isoformat()
    daily = [{"date": today, "cost": 5.00, "tokens": 0, "requests": 0,
              "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
              "api_key": "", "name": "", "provider": "moonshot"},
             {"date": "2026-08-10", "cost": 3.00, "tokens": 0, "requests": 0,
              "cache_hit": 0, "cache_miss": 0, "hit_rate": 0.0,
              "api_key": "", "name": "", "provider": "moonshot"}]
    # 余额 7.35，赠送 15 → 估算 7.65，但 daily 累计 8.00 > 7.65 → 用 8.00
    r = _fetch(0, 1500000, 0, 735000, 500000, daily)
    assert r.get("ok"), r
    assert r["data"]["total_cost"] == "8.00", r["data"]
    assert r["data"]["today_consume"] == "5.00", r["data"]


if __name__ == "__main__":
    test_balance_plus_cost_equals_granted()
    test_daily_less_than_total_keeps_total()
    test_daily_greater_than_total_uses_daily()
    print("PASS: Kimi 累计消费测试通过（消费+余额=总额）")
