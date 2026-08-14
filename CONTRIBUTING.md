# 贡献指南

欢迎参与「大模型余额监控」的开发！任何形式的贡献都欢迎：提交 Issue、完善文档、修复 Bug、新增服务商支持。

## 一、本地开发环境搭建

1. 安装 **Python 3.8+**（建议 3.10+）
2. 克隆仓库并进入目录：
   ```bash
   git clone https://github.com/zyy20080117/API-balance-monitor.git
   cd API-balance-monitor
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
   - Linux 用户还需安装 tkinter：`sudo apt install python3-tk`
4. 运行程序：
   ```bash
   python main.py
   ```

## 二、如何运行全部测试

```bash
python run_tests.py
```

该脚本会自动发现并执行 `tests/` 下所有 `test_*.py`，输出每个测试的通过/失败与汇总统计。

也可以单独运行某个测试：
```bash
python tests/test_master.py
```

> 测试均为 mock 方式，不访问真实网络 / 不启动浏览器，可在无网络环境运行。

## 三、代码风格规范

- 遵循 **PEP 8**，缩进用 4 空格，文件编码 **UTF-8**，文件头标注 `# -*- coding: utf-8 -*-`
- 注释使用中文（与服务商名等保持一致）
- 类名 `CamelCase`，函数/变量 `snake_case`，常量全大写
- 每个公开方法有 docstring，说明用途、参数、返回值
- 异常处理使用 `except Exception:  # noqa: BLE001` 的写法（参考现有代码），避免裸 except
- 日志通过 `logger.log(...)` 输出，不要用 `print` 调试

## 四、新增服务商的开发流程

以新增服务商 `foo` 为例：

1. **在 `providers.py` 注册**
   - 在 `PROVIDERS` 列表新增一项：
     ```python
     {"id": "foo", "name": "Foo 服务商", "default_base": "https://api.foo.com",
      "hint": "余额单位：元 (CNY)", "check": check_foo}
     ```
   - 实现 `check_foo(api_key, base_url)`，返回统一结构：
     `{"ok": True, "value": ..., "unit": ..., "lines": [...], "badge": ...}` 或 `{"ok": False, "error": ...}`

2. **（可选）每日用量 / 浏览器同步**
   - 若需要每日用量，新建 `foo_sync.py`（参考 `kimi_sync.py` / `siliconflow_sync.py`）
   - 实现 `fetch_foo_usage_daily(headless=True, timeout=90)`，返回 `{"ok", "data", "daily", "error"}`
   - 在 `gui.py` 中接入：`_worker_foo_sync` / `_finish_foo`、卡片显示、`_filtered_daily` 过滤、缓存读写
   - 浏览器同步必须使用 `browser_sync._BROWSER_LOCK` 串行（所有平台共用同一浏览器 profile）

3. **编写测试**
   - 在 `tests/` 下新建 `test_foo.py`，用 mock 覆盖余额解析 / 每日用量解析 / 异常场景
   - 测试**不要**访问真实网络或启动浏览器

4. **更新文档**
   - `README.md` 服务商列表、`DOCS.md` 配置教程补充

## 五、提交 PR 的步骤和要求

1. **Fork** 本仓库，新建分支（`feature/xxx` 或 `fix/xxx`）
2. 在分支上完成修改，**运行 `python run_tests.py` 确保全部通过**
3. 提交并推送分支，创建 **Pull Request**
4. PR 描述说明：改动内容、测试情况、如有 UI 改动附截图

合并要求：
- 全部测试通过
- 遵循代码风格
- 不引入第三方新依赖（除非确有需要并在 PR 说明）
