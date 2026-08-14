# -*- coding: utf-8 -*-
"""主账号功能（需求4）逻辑测试：不启动 GUI、不发网络请求。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui


def make_app():
    app = gui.BalanceApp.__new__(gui.BalanceApp)
    app.accounts = [
        {"id": "a1", "name": "DeepSeek-A", "provider": "deepseek", "api_key": "k1", "base_url": ""},
        {"id": "a2", "name": "DeepSeek-B", "provider": "deepseek", "api_key": "k2", "base_url": ""},
        {"id": "k1id", "name": "Kimi", "provider": "moonshot", "api_key": "k3", "base_url": ""},
    ]
    # 模拟平台逐日数据：两个 API Key 在同一天不同用量（应分开统计）
    app.daily_data = [
        {"date": "2026-08-09", "name": "API-A", "cost": 1.0, "tokens": 12200000, "requests": 10,
         "cache_hit": 0, "cache_miss": 0, "hit_rate": 0},
        {"date": "2026-08-09", "name": "API-B", "cost": 2.0, "tokens": 6600000, "requests": 8,
         "cache_hit": 0, "cache_miss": 0, "hit_rate": 0},
        {"date": "2026-08-10", "name": "API-A", "cost": 3.0, "tokens": 9900000, "requests": 12,
         "cache_hit": 0, "cache_miss": 0, "hit_rate": 0},
        {"date": "2026-08-10", "name": "API-B", "cost": 4.0, "tokens": 8900000, "requests": 9,
         "cache_hit": 0, "cache_miss": 0, "hit_rate": 0},
    ]
    app._master_id = ""
    app._master_api = ""
    app._alerts = {}
    app.official_data = None
    app.kimi_data = None
    app.results = {}
    return app


def test_filtered_daily():
    app = make_app()
    # 账号名称与平台 API Key 名称一致 → 自动只统计该 Key（无需手动绑定）
    app.accounts[0]["name"] = "API-A"
    app._master_id = "a1"
    f = app._filtered_daily()
    assert len(f) == 2, f"期望2条，实际{len(f)}"
    assert all(r["name"] == "API-A" for r in f), f
    assert sum(r["tokens"] for r in f) == 12200000 + 9900000, sum(r["tokens"] for r in f)

    # 换一个名称 = API-B 的账号 → 分开统计 API-B
    app.accounts[1]["name"] = "API-B"
    app._master_id = "a2"
    f = app._filtered_daily()
    assert sum(r["tokens"] for r in f) == 6600000 + 8900000, sum(r["tokens"] for r in f)

    # 名称与平台 API Key 不一致 → 返回全量（模型级合计）
    app.accounts[0]["name"] = "DeepSeek-A"
    app._master_id = "a1"
    assert len(app._filtered_daily()) == 4

    # 非 DeepSeek 主账号：daily 数据是 DeepSeek 平台的，不误显示 → 空列表
    app._master_id = "k1id"
    assert app._filtered_daily() == []


def test_alert_per_account():
    app = make_app()
    app._alerts = {"a1": 10.0, "k1id": 5.0}
    app._master_id = "a1"
    assert app._alert_threshold_for() == 10.0
    app._master_id = "k1id"
    assert app._alert_threshold_for() == 5.0
    app._master_id = "不存在"
    assert app._alert_threshold_for() == 0.0


def test_master_balance():
    app = make_app()
    # Kimi 主账号：余额来自 kimi_data
    app._master_id = "k1id"
    app.kimi_data = {"ok": True, "data": {"balance": "15.00"}}
    assert app._master_balance() == 15.0
    # DeepSeek 主账号：余额来自官方页面
    app._master_id = "a1"
    app.official_data = {"ok": True, "data": {"balance": "8.03"}}
    assert app._master_balance() == 8.03
    # 无数据：None
    app2 = make_app()
    app2._master_id = "a1"
    assert app2._master_balance() is None


def test_master_label():
    app = make_app()
    assert app._master_label() == "主账号 ▾"
    app._master_id = "a1"
    label = app._master_label()
    assert "DeepSeek-A" in label, label


def test_short_name():
    assert gui._provider_short_name("siliconflow") == "硅基流动"
    assert gui._provider_short_name("deepseek") == "DeepSeek"
    assert gui._provider_short_name("zhipu") == "智谱"
    assert gui._provider_short_name("") == ""


def test_master_label_short():
    # 无账号名：主账号按钮只显示服务商短名，不显示全名「硅基流动 SiliconFlow」
    app = make_app()
    app.accounts.append({"id": "sf", "name": "",
                         "provider": "siliconflow", "api_key": "k", "base_url": ""})
    app._master_id = "sf"
    label = app._master_label()
    assert label == "主账号 ▾ 硅基流动", label
    assert "SiliconFlow" not in label, label
    # 有账号名：优先用账号名
    app.accounts[-1]["name"] = "我的硅基"
    assert app._master_label() == "主账号 ▾ 我的硅基", app._master_label()


if __name__ == "__main__":
    test_filtered_daily()
    test_alert_per_account()
    test_master_balance()
    test_master_label()
    test_short_name()
    test_master_label_short()
    print("PASS: 主账号逻辑测试通过")
