# -*- coding: utf-8 -*-
"""语法 / 逻辑自测：不联网的部分直接跑，联网部分打印结果供人工判断。"""
import os
import sys

import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import providers
import storage


def main():
    # 1) 模块可导入
    importlib.reload(providers)
    importlib.reload(storage)
    print("[OK] 模块导入正常")

    # 2) 服务商注册表完整
    for p in providers.PROVIDERS:
        assert p["id"] and p["name"] and callable(p["check"]), f"服务商配置不完整: {p}"
    print(f"[OK] 已注册 {len(providers.PROVIDERS)} 个服务商：",
          "、".join(p["name"] for p in providers.PROVIDERS))

    # 3) 存储往返（用临时配置路径，不写正式文件）
    import os
    backup = storage.CONFIG_PATH
    storage.CONFIG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_test_accounts.json")
    accs = [{"id": "abc", "name": "测试", "provider": "deepseek",
             "api_key": "sk-test-12345", "base_url": ""}]
    storage.save_accounts(accs)
    loaded = storage.load_accounts()
    # 保存时会补 created_at，比较关键字段
    assert loaded and loaded[0]["id"] == accs[0]["id"]
    assert loaded[0]["api_key"] == accs[0]["api_key"]
    assert loaded[0]["provider"] == accs[0]["provider"]
    assert loaded[0]["name"] == accs[0]["name"]
    os.remove(storage.CONFIG_PATH)
    storage.CONFIG_PATH = backup
    print("[OK] 存储加密/解密往返正常")

    # 4) 各服务商：无 Key 时返回明确错误（不联网）
    for p in providers.PROVIDERS:
        r = providers.check_account(p["id"], "", p["default_base"])
        assert r.get("ok") is False, f"{p['id']} 空 Key 应报错: {r}"
    print("[OK] 空 API Key 均能给出友好提示")

    # 5) 可选：真实 Key 验证（从环境变量读，未设置则跳过）
    import os
    real_key = os.environ.get("MB_TEST_DEEPSEEK_KEY")
    if real_key:
        r = providers.check_account("deepseek", real_key, "")
        print(f"[网络] DeepSeek 真实查询结果: {r}")
    else:
        print("[跳过] 未设置 MB_TEST_DEEPSEEK_KEY，跳过真实网络查询")

    print("\n全部自测通过")


if __name__ == "__main__":
    main()
