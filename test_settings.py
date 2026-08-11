# -*- coding: utf-8 -*-
"""自动刷新/自动同步时间设置逻辑测试：手动输入解析 + 1~120 上限。不启动 GUI。"""
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
    test_global_click_saves()
    print("PASS: 自动刷新/同步时间设置测试通过")
