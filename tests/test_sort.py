# -*- coding: utf-8 -*-
"""排序功能逻辑测试：模式记忆 + 数据更新后重排 + 余额缺失排最后。不启动 GUI。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui  # noqa: E402


def make_app():
    app = gui.BalanceApp.__new__(gui.BalanceApp)
    app.accounts = [
        {"id": "a", "provider": "relay", "name": "中转A", "created_at": 3.0},
        {"id": "b", "provider": "relay", "name": "模型B", "created_at": 1.0},
        {"id": "c", "provider": "relay", "name": "中转C", "created_at": 2.0},
    ]
    app._sort_mode = ""
    app.results = {}
    app.official_data = None
    app.kimi_data = None
    app.zhipu_data = None
    app.siliconflow_data = None
    return app


def test_time():
    app = make_app()
    app._sort_mode = "time"
    app._apply_sort_order()
    assert [a["id"] for a in app.accounts] == ["b", "c", "a"]


def test_balance():
    app = make_app()
    # a=5, b 无数据, c=3 → 有数据降序在前，无数据最后
    app.results = {"a": {"ok": True, "value": "5"},
                   "b": {"ok": False},
                   "c": {"ok": True, "value": "3"}}
    app._sort_mode = "balance"
    app._apply_sort_order()
    ids = [a["id"] for a in app.accounts]
    assert ids == ["a", "c", "b"], ids


def test_rebuild_does_not_resort():
    """同步官方/刷新过程中 rebuild 不重排，顺序稳定（避免中间态乱序）。"""
    app = make_app()
    app.results = {"a": {"ok": True, "value": "1"},
                   "b": {"ok": False},
                   "c": {"ok": True, "value": "9"}}
    app._sort_mode = "balance"
    app._apply_sort_order()
    order1 = [a["id"] for a in app.accounts]   # c, a, b
    # 数据更新（同步过程中部分数据到位），重建不重排 → 顺序不变
    app.results["b"] = {"ok": True, "value": "99"}
    app._rebuild_list = lambda: None
    app._rebuild_list()
    assert [a["id"] for a in app.accounts] == order1, [a["id"] for a in app.accounts]


def test_after_sync_resorts():
    """同步官方全部完成后按最新数据重排一次。"""
    app = make_app()
    app.results = {"a": {"ok": False}, "b": {"ok": False}, "c": {"ok": False}}
    app._sort_mode = "balance"
    app._apply_sort_order()
    assert [a["id"] for a in app.accounts] == ["a", "b", "c"]
    app.results["b"] = {"ok": True, "value": "99"}
    app._rebuild_list = lambda: None
    app._apply_sort_after_sync()
    assert [a["id"] for a in app.accounts] == ["b", "a", "c"], [a["id"] for a in app.accounts]


def test_name():
    app = make_app()
    app._sort_mode = "name"
    app._apply_sort_order()
    ids = [a["id"] for a in app.accounts]
    assert ids == ["b", "a", "c"], ids  # 模(m) 在 中(z) 前


def test_no_mode():
    app = make_app()
    app._apply_sort_order()
    assert [a["id"] for a in app.accounts] == ["a", "b", "c"]


def test_startup_applies_sort_mode():
    """启动时即使文件顺序是乱序，也应按上次排序方式恢复显示顺序。"""
    app = make_app()
    # 文件顺序被其它操作打乱：created_at 乱序
    app.accounts = [
        {"id": "x", "provider": "relay", "name": "中转X", "created_at": 3.0},
        {"id": "y", "provider": "relay", "name": "模型Y", "created_at": 1.0},
        {"id": "z", "provider": "relay", "name": "中转Z", "created_at": 2.0},
    ]
    app._sort_mode = "time"
    app._apply_sort_order()   # __init__ 启动时调用
    assert [a["id"] for a in app.accounts] == ["y", "z", "x"], [a["id"] for a in app.accounts]


def test_set_sort_persists():
    app = make_app()
    app._rebuild_list = lambda: None  # 不重建 UI，只验证模式设置
    app._set_sort("time")
    assert app._sort_mode == "time"


def test_sort_persisted_across_restart():
    """选择排序后写入 settings，模拟重启后从 settings 恢复同一排序。"""
    import os
    import tempfile
    import storage
    orig = storage.SETTINGS_PATH
    storage.SETTINGS_PATH = os.path.join(tempfile.gettempdir(), "_sf_test_settings.json")
    try:
        app = make_app()
        app._rebuild_list = lambda: None
        app._set_sort("balance")
        # 选择后 settings 里已写入 sort_mode
        assert storage.load_settings().get("sort_mode") == "balance"
        # 模拟重启：从 settings 读到上一次的选择
        app2 = make_app()
        app2._sort_mode = str(storage.load_settings().get("sort_mode", "") or "")
        assert app2._sort_mode == "balance"
    finally:
        if os.path.exists(storage.SETTINGS_PATH):
            os.remove(storage.SETTINGS_PATH)
        storage.SETTINGS_PATH = orig


def test_menu_checkmark():
    app = make_app()
    app._sort_mode = "balance"
    labels = [t for t, _ in app._sort_menu_items()]
    assert labels == ["按添加时间（从早→晚）", "✔ 按模型余额（高 → 低）", "按名称（首字母）"], labels
    app._sort_mode = "name"
    labels = [t for t, _ in app._sort_menu_items()]
    assert labels[2] == "✔ 按名称（首字母）", labels
    app._sort_mode = "time"
    labels = [t for t, _ in app._sort_menu_items()]
    assert labels[0] == "✔ 按添加时间（从早→晚）", labels
    app._sort_mode = ""
    labels = [t for t, _ in app._sort_menu_items()]
    assert all(not t.startswith("✔") for t in labels), labels


if __name__ == "__main__":
    test_time()
    test_balance()
    test_rebuild_does_not_resort()
    test_after_sync_resorts()
    test_name()
    test_no_mode()
    test_startup_applies_sort_mode()
    test_set_sort_persists()
    test_menu_checkmark()
    test_sort_persisted_across_restart()
    print("PASS: 排序逻辑测试通过")
