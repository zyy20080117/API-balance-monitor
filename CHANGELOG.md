# 变更日志

## v0.0.1（2026-08-13）

首个正式发布版本。

### 新增

- 支持 DeepSeek、Kimi（Moonshot）、智谱 GLM、硅基流动、OpenRouter、通用中转站 6 类服务商接入
- 账户余额、累计已消费总金额监控（部分平台含充值 / 赠送明细）
- 每日用量日历（DeepSeek / OpenRouter 含 Token 用量）
- 每小时 Token 分布图（DeepSeek / OpenRouter）
- 多账号管理：添加 / 编辑 / 删除 / 排序 / 主账号
- 余额预警、自动刷新余额、自动同步官方
- 开机自动同步官方数据
- 通用中转站多路径余额探测（OpenAI 计费 / new-api / one-api quota / 通用 balance）
- GitHub Actions 三平台（Windows / macOS / Linux）自动构建并发布 Release

### 修复

- Kimi 每日用量字段（voucher_fee / recharge_fee）解析，消费金额不再记 0
- 各平台累计消费不小于今日消费的口径兜底
- OpenRouter（国外站点）短超时，避免长时间「查询中」
- 主界面卡片更新去抖，减少闪烁
- DeepSeek 请求 / Token 以官方页面为准

### 优化

- 每日用量打开时缓存优先，避免每次都开浏览器
- 按钮圆角高倍超采样，小按钮更平滑
- 余额 / 消费金额统一格式化
