# 大模型余额监控（API Balance Monitor）

> 本项目使用 **MIT License** 开源，详见 [LICENSE](LICENSE)。

一个 Windows / macOS / Linux 桌面应用，把多家大模型 API 的**账户余额**和**累计已消费金额**集中到一个界面统一查看，并提供每日用量日历、每小时 Token 分布、余额预警等能力。

---

## 项目解决的问题

同时使用多个大模型 API（DeepSeek、Kimi、智谱、硅基流动、OpenRouter 等）时，余额和消费分散在各自平台的后台，需要频繁登录查看。本工具把这些平台的余额与累计消费集中到一个桌面界面，避免反复登录，并额外提供每日用量、Token 分布、余额预警等辅助能力。

## 功能概览

- **支持接入以下大模型服务商**，统一监控账户余额与累计消费：
  - DeepSeek
  - Kimi（Moonshot）
  - 智谱 GLM（BigModel）
  - 硅基流动（SiliconFlow）
  - OpenRouter
  - 通用中转站（兼容 OpenAI 计费 / new-api / one-api 等主流中转）
- **可读取的数据**：账户余额、累计已消费总金额（部分平台含充值 / 赠送明细）
- **每日用量日历**：按日展示消费金额（DeepSeek / OpenRouter 含 Token 用量）
- **每小时 Token 分布图**（DeepSeek / OpenRouter 官方接口提供）
- **金额显示自动适配服务商币种单位**（人民币 ¥ / 美元 $）
- **本地离线图标资源**：图标以内嵌 base64 保存，不依赖外部文件、可离线运行
- **多账号管理**：添加 / 编辑 / 删除 / 排序 / 设置主账号
- **余额预警**：主账号余额低于阈值时提醒
- **自动刷新余额、自动同步官方**（浏览器抓取官方数据）
- **开机自动同步官方数据**

## 快速开始

### 环境要求

- Windows / macOS / Linux
- Python 3.8+
- 浏览器同步依赖本机 Chromium 内核（Windows 使用系统 Edge）

### 从源码运行

```bash
pip install -r requirements.txt
python main.py
```

> 依赖：`tkinter`、`PIL(Pillow)`、`requests`、`playwright`

### 使用步骤

1. 点击「＋ 添加账号」，选择服务商，填入该平台的 **API Key**（智谱还需在软件弹出的浏览器里登录一次）
2. 余额会自动通过 HTTP 接口查询；点击「同步官方」可获取浏览器侧的官方数据（消费 / 每日用量）
3. 在「主账号」里选择一个账号，每日用量 / 预警设置将跟随它

详细配置教程、参数说明与故障排错见 [DOCS.md](DOCS.md)。

### 打包安装包

安装包（Windows exe / macOS / Linux）不提交到源码仓库，发布在 **GitHub Releases** 页面。需要打包可运行：

```bash
pyinstaller ModelBalance.spec --noconfirm
```

多平台自动构建见 [.github/workflows/build.yml](.github/workflows/build.yml)。

## 已知限制

1. 当前所有接入模型，仅能够获取账户余额、累计已消费总金额；本工具**不支持查询单条 Token 消耗明细**。
2. 绝大多数服务商官方 API 不提供账单明细接口：**无法获取单次请求消耗、无法按日期查看历史消费、无法区分不同 API‑Key 各自消耗**。
3. 软件内部本地统计仅供参考，统计数值会和官方网页后台存在偏差，**一切以服务商网页账单为准**。
4. 部分平台没有官方余额查询 API，暂时无法接入，列入待开发。
5. 待开发功能：**GPT、Gemini、Claude 三家模型余额查看功能，尚未实现**。

## 开发计划

当前正在开发功能：GPT、Gemini、Claude 三家模型的余额查看功能。

## 贡献指引

欢迎任何形式的贡献：提交 Issue、完善文档、修复 Bug、新增服务商支持。

1. **Fork** 本仓库，并新建分支（`feature/xxx` 或 `fix/xxx`）
2. 修改代码，补充/更新测试（`test_*.py`）
3. 提交并推送分支，然后创建 **Pull Request**
4. 说明改动内容与测试结果

编码规范：
- 遵循现有代码风格（Python 3，中文注释）
- 每个新增服务商同步模块放在独立文件（如 `xxx_sync.py`），并在 `providers.py` 注册
- 合并前需通过现有测试：`python test_*.py`

## 开源协议

本项目使用 [MIT License](LICENSE)。
