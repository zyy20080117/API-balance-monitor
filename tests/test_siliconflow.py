# -*- coding: utf-8 -*-
"""硅基流动接入逻辑测试：不启动 GUI、不发网络请求。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui  # noqa: E402
import siliconflow_sync  # noqa: E402


def make_app():
    app = gui.BalanceApp.__new__(gui.BalanceApp)
    app.accounts = [
        {"id": "sf1", "name": "硅基流动", "provider": "siliconflow", "api_key": "k", "base_url": ""},
        {"id": "ds1", "name": "DeepSeek", "provider": "deepseek", "api_key": "k2", "base_url": ""},
    ]
    app.daily_data = [
        {"date": "2026-08-10", "name": "", "provider": "siliconflow",
         "cost": 0.5, "tokens": 0, "requests": 0},
        {"date": "2026-08-11", "name": "", "provider": "siliconflow",
         "cost": 1.2, "tokens": 0, "requests": 0},
        {"date": "2026-08-10", "name": "API-A", "provider": "deepseek",
         "cost": 3.0, "tokens": 100, "requests": 1},
    ]
    app._master_id = ""
    app._master_api = ""
    app._alerts = {}
    app.official_data = None
    app.kimi_data = None
    app.zhipu_data = None
    app.siliconflow_data = None
    app.results = {}
    return app


def test_filtered_daily():
    app = make_app()
    app._master_id = "sf1"
    f = app._filtered_daily()
    assert len(f) == 2, f"期望2条硅基流动记录，实际{len(f)}"
    assert all(r["provider"] == "siliconflow" for r in f), f
    # DeepSeek 主账号：不应混入硅基流动数据
    app._master_id = "ds1"
    f2 = app._filtered_daily()
    assert all(r["provider"] == "deepseek" for r in f2), f2


def test_master_balance():
    app = make_app()
    app._master_id = "sf1"
    assert app._master_balance() is None
    app.siliconflow_data = {"ok": True, "data": {"balance": "0.00"}}
    assert app._master_balance() == 0.0


def test_account_balance():
    app = make_app()
    app.siliconflow_data = {"ok": True, "data": {"balance": "0.00"}}
    assert app._account_balance(app.accounts[0]) == 0.0


def test_parse_daily():
    # 同一天多条（不同 apiKey/model 分摊）累计；timeDimension 支持时间戳/字符串
    data = {"data": {"list": [
        {"timeDimension": 1786406400000, "netAmount": "0.30", "apiKey": "a", "modelName": "m1"},
        {"timeDimension": "2026-08-11 00:00:00", "netAmount": "0.20", "apiKey": "b", "modelName": "m2"},
        {"timeDimension": "2026-08-10", "grossAmount": "0.10"},
        {"timeDimension": 1786320000, "netAmount": "5.00"},
    ]}}
    recs = siliconflow_sync._parse_daily(data)
    by = {r["date"]: r["cost"] for r in recs}
    assert abs(by.get("2026-08-11", 0) - 0.50) < 1e-6, by  # 0.30 + 0.20 同天累计
    assert abs(by.get("2026-08-10", 0) - 5.10) < 1e-6, by  # 0.10(gross) + 5.00(秒级时间戳)
    assert recs[0]["provider"] == "siliconflow"


def test_fmt_date():
    assert siliconflow_sync._fmt_date(1786377600000) == "2026-08-11"
    assert siliconflow_sync._fmt_date("2026-08-11 00:00:00") == "2026-08-11"
    assert siliconflow_sync._fmt_date("2026-08-10") == "2026-08-10"
    assert siliconflow_sync._fmt_date("not-a-date") is None


if __name__ == "__main__":
    test_filtered_daily()
    test_master_balance()
    test_account_balance()
    test_parse_daily()
    test_fmt_date()
    print("PASS: 硅基流动接入逻辑测试通过")
