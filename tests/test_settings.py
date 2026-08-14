# -*- coding: utf-8 -*-
"""自动刷新/自动同步时间设置逻辑测试：手动输入解析 + 1~120 上限。不启动 GUI。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui  # noqa: E402


def make_app():
    return gui.BalanceApp.__new__(gui.BalanceApp)


def test_clamp():
    app = make_app()
    # 合法范围原样保留
    assert app._clamp_minutes("30", 10) == 30
    assert app._clamp_minutes("1", 10) == 1
    assert app._clamp_minutes("120", 10) == 120
    # 超过 120 → 上限 120
    assert app._clamp_minutes("150", 10) == 120
    assert app._clamp_minutes("999", 10) == 120
    # 0 / 负数 / 非法字符 / 空 → 用默认值
    assert app._clamp_minutes("0", 10) == 10
    assert app._clamp_minutes("-5", 30) == 30
    assert app._clamp_minutes("abc", 10) == 10
    assert app._clamp_minutes("", 30) == 30
    assert app._clamp_minutes("30.5", 10) == 10
    # 首尾空格容错
    assert app._clamp_minutes(" 25 ", 10) == 25


def test_worker_all_parallel():
    """启动刷新并行查询所有账号，避免模型多时「查询中」持续很久。"""
    import threading
    import time

    class FakeQueue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

    import providers
    app = make_app()
    app.accounts = [
        {"id": "a", "provider": "relay", "api_key": "k", "base_url": "https://x"},
        {"id": "b", "provider": "relay", "api_key": "k", "base_url": "https://x"},
    ]
    app.refresh_lock = threading.Lock()
    app.refresh_lock.acquire()
    app.results = {}
    app.ui_queue = FakeQueue()
    app._finish_one = lambda i, r: None
    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def slow_check(p, k, b):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.3)
        with lock:
            active["n"] -= 1
        return {"ok": True, "value": "1", "unit": "CNY", "lines": []}

    orig = providers.check_account
    providers.check_account = slow_check
    try:
        t0 = time.time()
        app._worker_all()
        elapsed = time.time() - t0
        # 并行：两个账号应同时查询（并发度≥2），总耗时接近单个账号
        assert active["max"] >= 2, f"并发度={active['max']}，应并行≥2"
        assert elapsed < 0.55, f"总耗时={elapsed:.2f}s，串行应为~0.6s"
        print(f"并行验证: 并发max={active['max']} 总耗时={elapsed:.2f}s")
    finally:
        providers.check_account = orig


def test_network_error_detect():
    """开机网络未就绪的查询结果应识别为网络错误，不标账号异常。"""
    app = make_app()
    assert app._is_network_error({"ok": False, "error": "无法连接服务器：ConnectionError"})
    assert app._is_network_error({"ok": False, "error": "ConnectionError"})
    assert app._is_network_error({"ok": False, "error": "HTTPSConnectionPool ... Max retries"})
    assert app._is_network_error({"ok": False, "error": "连接超时 timed out"})
    # 非网络错误不误判
    assert not app._is_network_error({"ok": False, "error": "API Key 无效或没有权限 (401/403)"})
    assert not app._is_network_error({"ok": False, "error": "余额不足 (402)"})
    assert not app._is_network_error(None)
    assert not app._is_network_error({"ok": True, "value": "5"})


def test_global_click_saves():
    """点击输入框以外的地方：立即保存 + 焦点移出输入框（光标不再停留）；点击输入框内保持编辑。"""
    app = make_app()
    calls = []
    app.auto_spin = object()
    app.sync_spin = object()
    app._on_minutes_change = lambda: calls.append("auto")
    app._on_sync_minutes_change = lambda: calls.append("sync")

    focus_sets = []

    class FakeRoot:
        target = None

        @classmethod
        def focus_get(cls):
            return cls.target

        @classmethod
        def focus_set(cls):
            focus_sets.append(1)

    app.root = FakeRoot

    class Ev:
        def __init__(self, w):
            self.widget = w

    # 自动刷新框持有焦点，点击空白（其他 widget）→ 保存 + 移焦
    FakeRoot.target = app.auto_spin
    app._on_global_click(Ev(object()))
    assert calls == ["auto"], calls
    assert len(focus_sets) == 1, focus_sets
    # 自动同步框持有焦点，点击空白 → 保存 + 移焦
    FakeRoot.target = app.sync_spin
    app._on_global_click(Ev(object()))
    assert calls == ["auto", "sync"], calls
    assert len(focus_sets) == 2, focus_sets
    # 焦点在别处/无焦点 → 不触发
    FakeRoot.target = None
    app._on_global_click(Ev(object()))
    assert calls == ["auto", "sync"], calls
    # 点击输入框自身（继续编辑）→ 不保存不移焦
    FakeRoot.target = app.auto_spin
    before = len(calls)
    app._on_global_click(Ev(app.auto_spin))
    assert len(calls) == before, calls
    assert len(focus_sets) == 2, focus_sets


if __name__ == "__main__":
    test_clamp()
    test_network_error_detect()
    test_worker_all_parallel()
    test_global_click_saves()
    print("PASS: 自动刷新/同步时间设置测试通过")
