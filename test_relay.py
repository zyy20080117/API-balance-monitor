# -*- coding: utf-8 -*-
"""通用中转站余额查询测试：兼容 OpenAI / new-api(quota) / 通用 balance 格式。mock HTTP。"""
import sys

sys.path.insert(0, r"c:/Users/13404/model_balance_app")
import providers  # noqa: E402


class FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = ""
        self._data = data

    def json(self):
        return self._data


def _run(route):
    orig = providers.requests.get
    providers.requests.get = lambda url, headers=None, timeout=None: route(url)
    try:
        return providers.check_relay("sk-key", "https://relay.example.com")
    finally:
        providers.requests.get = orig


def _route_map(mapping):
    def route(url):
        for sub, resp in mapping.items():
            if sub in url:
                return resp
        return FakeResp(404, {})
    return route


def test_openai_credit_grants():
    """OpenAI 格式 total_available → 余额 USD。"""
    route = _route_map({"/credit_grants": FakeResp(200, {
        "total_available": "50.5", "total_granted": "100", "total_used": "49.5"})})
    r = _run(route)
    assert r["ok"], r
    assert r["value"] == 50.5, r
    assert r["unit"] == "USD"
    assert any("已使用" in l for l in r["lines"])


def test_newapi_quota():
    """new-api/one-api /api/user/self：data.quota (1 quota=1/500000 USD)。"""
    route = _route_map({"/api/user/self": FakeResp(200, {
        "success": True, "data": {"quota": 500000, "used_quota": 100000}})})
    r = _run(route)
    assert r["ok"], r
    assert abs(r["value"] - 1.0) < 0.001, r   # 500000/500000 = 1 USD
    assert r["unit"] == "USD"
    assert any("0.20" in l for l in r["lines"])  # used 100000/500000=0.2


def test_generic_balance():
    """通用 {"balance":..,"currency":..} 格式。"""
    route = _route_map({"/v1/user/balance": FakeResp(200, {
        "balance": "10", "currency": "CNY"})})
    r = _run(route)
    assert r["ok"], r
    assert r["value"] == 10, r
    assert r["unit"] == "CNY"


def test_nested_balance():
    """嵌套 data.balance 格式。"""
    route = _route_map({"/api/balance": FakeResp(200, {
        "code": 20000, "data": {"balance": "7.5"}})})
    r = _run(route)
    assert r["ok"], r
    assert r["value"] == 7.5, r


def test_all_paths_fail():
    r = _run(lambda url: FakeResp(404, {}))
    assert not r["ok"], r


def test_401_invalid_key():
    r = _run(lambda url: FakeResp(401, {"error": "invalid key"}))
    assert not r["ok"], r


if __name__ == "__main__":
    test_openai_credit_grants()
    test_newapi_quota()
    test_generic_balance()
    test_nested_balance()
    test_all_paths_fail()
    test_401_invalid_key()
    print("PASS: 通用中转站余额查询测试通过")
