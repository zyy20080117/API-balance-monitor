# -*- coding: utf-8 -*-
"""统一测试入口：自动发现并运行所有 test_*.py。

用法：
    python run_tests.py

输出每个测试文件的通过/失败结果与汇总统计。
纯 Python 实现，不依赖 pytest。
"""
import glob
import os
import subprocess
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    tests = sorted(glob.glob(os.path.join(here, "test_*.py")))
    if not tests:
        print("未找到任何 test_*.py")
        return 1

    passed = []
    failed = []
    print("=" * 60)
    print(f"发现 {len(tests)} 个测试文件，开始运行...")
    print("=" * 60)
    for t in tests:
        name = os.path.basename(t)
        print(f"\n▶ {name}")
        try:
            r = subprocess.run([sys.executable, t], cwd=here,
                               capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                passed.append(name)
                print("  ✓ 通过")
            else:
                detail = (r.stderr or r.stdout or "").strip()[-800:]
                failed.append((name, detail))
                print("  ✗ 失败")
        except subprocess.TimeoutExpired:
            failed.append((name, "运行超时(>120s)"))
            print("  ✗ 超时")

    print("\n" + "=" * 60)
    print(f"结果：共 {len(tests)} 个，通过 {len(passed)}，失败 {len(failed)}")
    if failed:
        print("\n失败详情：")
        for name, err in failed:
            print(f"  ✗ {name}:\n    {err[:400]}")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
