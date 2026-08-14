# 架构说明

5 分钟了解项目结构、启动流程、数据流与浏览器同步原理。

## 一、项目文件结构

```
API-balance-monitor/
├── main.py                  # 程序入口：调用 gui.main() 启动
├── gui.py                   # 主界面（BalanceApp）：所有 UI、事件调度、同步协调
├── providers.py             # 服务商注册表 + 各服务商 HTTP 余额查询
├── storage.py               # 本地存储：账号（API Key 用 DPAPI 加密）、设置
├── browser_sync.py          # DeepSeek 浏览器同步：令牌缓存 + 官方页面抓取 + 逐日/小时数据
├── kimi_sync.py             # Kimi 浏览器同步（每日账单 organizationDailyBills）
├── zhipu_sync.py            # 智谱浏览器同步（账户报告 + 按日费用明细）
├── siliconflow_sync.py      # 硅基流动浏览器同步（钱包余额 + 按日聚合账单）
├── openrouter_sync.py       # OpenRouter 同步（HTTP 余额 + analytics 每日/小时）
├── ios_ui.py                # iOS 风格 UI 组件（抗锯齿圆角按钮、配色）
├── logo_data.py             # 模型/功能图标（base64 内嵌，离线可用）
├── logger.py                # 日志输出
├── make_icon.py             # 生成应用图标 assets/icon.ico
├── mobile_preview.py        # 移动端界面预览辅助
├── self_check.py            # 自检脚本（调试用）
├── requirements.txt         # 依赖清单（含版本范围）
├── run_tests.py             # 统一测试入口
├── tests/                   # 单元测试（test_*.py，mock，不联网）
├── ModelBalance.spec        # PyInstaller 打包配置
└── assets/                  # 图标与截图（离线资源）
```

## 二、程序启动流程

```
main.py
  └─ gui.main()
       └─ BalanceApp.__init__()
            ├─ 加载本地账号/设置（storage.load_accounts / load_settings）
            ├─ 构建界面（_build_header / _build_list / _build_footer）
            ├─ 恢复上次排序
            └─ refresh_all()          # 启动即刷新余额
                 └─ _worker_all（并行线程）
                      ├─ providers.check_account()  # HTTP 查各账号余额
                      └─ _finish_all()              # 完成：触发浏览器同步、自动重试、预警检查
                           └─ 各平台浏览器同步（Kimi/智谱/硅基/OpenRouter/DeepSeek）
```

## 三、数据流向

### 余额查询（HTTP，快）

```
用户添加账号（填 API Key）
  └─ storage.save_accounts（DPAPI 加密落盘）
  └─ refresh_all → _worker_all（并行）
       └─ providers.check_account(provider, key, base_url)
            ├─ check_deepseek → GET /user/balance
            ├─ check_moonshot  → GET /v1/users/me/balance
            ├─ check_zhipu     → 无公开接口（404，需浏览器同步）
            └─ ... 各服务商 check_xxx
       └─ results[id] → 主线程 _finish_one → 卡片显示余额
```

### 浏览器同步（慢，官方权威数据）

```
用户点「同步官方」或打开每日用量
  └─ sync_official / show_daily
       └─ _worker_xxx_sync（线程，持 _BROWSER_LOCK）
            └─ xxx_sync.fetch_xxx_usage_daily()
                 ├─ playwright 启动 Edge（复用 browser_profile 登录态）
                 ├─ 打开平台控制台，捕获内部 API 令牌
                 ├─ page.evaluate(fetch) 调内部接口
                 └─ 解析 → {data, daily, error}
       └─ _finish_xxx（主线程）
            ├─ xxx_data → 卡片显示（余额/已消费/今日消费）
            └─ daily → _merge_daily 合并到 daily_data → 日历显示
```

## 四、浏览器同步模块工作原理

各 `xxx_sync.py` 统一使用 `browser_sync` 的浏览器配置：

- **浏览器 profile**：`~/.model_balance/browser_profile`，独立于日常浏览器，登录态仅保存在本地
- **启动方式**：`playwright` + 系统 Edge（`launch_persistent_context`），`headless=True`（无窗口）
- **令牌获取**：打开平台控制台页面，监听请求头捕获 `authorization` / `token` 或账户标识
- **数据抓取**：`page.evaluate(fetch(...))` 在已登录页面内调用平台内部 API，携带捕获的令牌
- **缓存**：抓取结果写 `~/.model_balance/*_cache.json`，下次启动优先读缓存，避免每次都开浏览器
- **串行锁**：所有平台共用同一个 browser_profile，同一时刻只允许一个浏览器会话，`browser_sync._BROWSER_LOCK`（threading.Lock）保证串行，避免 Chromium profile 冲突

### 各平台数据来源对照

| 平台 | 余额 | 每日用量 | 每小时分布 |
|---|---|---|---|
| DeepSeek | HTTP `/user/balance` | 官方 `/usage` 接口 | ✅ 官方小时接口 |
| Kimi | HTTP `/v1/users/me/balance` | 浏览器 organizationDailyBills | 无 |
| 智谱 | 仅浏览器（无 HTTP） | 浏览器 expenseBillListByDay | 无 |
| 硅基流动 | HTTP `/v1/user/info` | 浏览器按日聚合账单 | 无 |
| OpenRouter | HTTP `/api/v1/credits` | 浏览器 analytics | ✅ analytics hour |
| 通用中转站 | HTTP 多路径探测 | 无 | 无 |

## 五、线程模型

- 所有网络/浏览器操作在**后台线程**执行，通过 `ui_queue`（queue.Queue）+ 主线程 `_poll_queue`（每 100ms）回调更新 UI
- 禁止在后台线程直接操作 UI；UI 更新统一走 `ui_queue.put(lambda ...: 主线程方法(...))`
- 浏览器操作必须持 `_BROWSER_LOCK`，且用 `ui_queue` 返回结果到主线程
