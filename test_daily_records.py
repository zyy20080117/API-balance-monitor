# -*- coding: utf-8 -*-
"""各账号每日用量记录与 Token 计算验证。

验证：DeepSeek/OpenRouter 有 Token 维度，Kimi/智谱/硅基流动无 Token（接口无该维度），
按「有就保留，没有才舍去」记录。合并、过滤、Token 计算正确。
"""
import sys

sys.path.insert(0, r"c:/Users/13404/model_balance_app")
import gui  # noqa: E402


def make_app():
    app = gui.BalanceApp.__new__(gui.BalanceApp)
    app.accounts = [
        {"id": "ds", "provider": "deepseek", "name": "ds1"},
        {"id": "km", "provider": "moonshot", "name": ""},
        {"id": "zp", "provider": "zhipu", "name": ""},
        {"id": "sf", "provider": "siliconflow", "name": ""},
        {"id": "or", "provider": "openrouter", "name": ""},
    ]
    app.daily_data = []
    app._save_daily_cache = lambda: None
    app._master_id = ""
    app._master_api = ""
    return app


def test_merge_all_providers():
    """各服务商每日用量合并后完整保留，Token 计算正确。"""
    app = make_app()
    ds = [{"provider": "deepseek", "name": "ds1", "date": "2026-08-12",
           "cost": 0.5, "tokens": 1000, "requests": 10}]
    kimi = [{"provider": "moonshot", "name": "", "date": "2026-08-12",
             "cost": 0.1, "tokens": 0, "requests": 0}]
    zhipu = [{"provider": "zhipu", "name": "", "date": "2026-08-12",
              "cost": 0.2, "tokens": 0, "requests": 0}]
    sf = [{"provider": "siliconflow", "name": "", "date": "2026-08-12",
           "cost": 0.3, "tokens": 0, "requests": 0}]
    or_ = [{"provider": "openrouter", "name": "", "date": "2026-08-12",
            "cost": 0.4, "tokens": 500, "requests": 5}]
    for r in (ds, kimi, zhipu, sf, or_):
        app._merge_daily(r)
    assert len(app.daily_data) == 5, [r["provider"] for r in app.daily_data]
    by_prov = {r["provider"]: r for r in app.daily_data}
    # Token：DeepSeek/OpenRouter 有值，其余为 0（接口无 Token 维度）
    assert by_prov["deepseek"]["tokens"] == 1000
    assert by_prov["openrouter"]["tokens"] == 500
    assert by_prov["moonshot"]["tokens"] == 0
    assert by_prov["zhipu"]["tokens"] == 0
    assert by_prov["siliconflow"]["tokens"] == 0


def test_filtered_by_master():
    """每日用量按主账号过滤：OpenRouter 主账号只返回 openrouter 记录。"""
    app = make_app()
    app._merge_daily([{"provider": "deepseek", "name": "ds1", "date": "2026-08-12",
                       "cost": 0.5, "tokens": 1000, "requests": 10}])
    app._merge_daily([{"provider": "openrouter", "name": "", "date": "2026-08-12",
                       "cost": 0.4, "tokens": 500, "requests": 5}])
    app._master_id = "or"
    filt = app._filtered_daily()
    assert len(filt) == 1 and filt[0]["provider"] == "openrouter", filt


if __name__ == "__main__":
    test_merge_all_providers()
    test_filtered_by_master()
    print("PASS: 每日用量记录与 Token 计算验证通过")
