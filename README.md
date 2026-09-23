<div align="center">

# 🛠️ MC Scanner v3.6.0

### Minecraft 服务器扫描与探测工具

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/MC%20Protocol-340%2B-orange.svg)](#)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#)

**端口扫描 · SLP探测 · 认证检测 · 观察者模式 · AI托管 · 安全扫描 · Web面板**

</div>

---

## 📖 目录

- [简介](#简介)
- [功能一览](#功能一览)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [更新日志](#更新日志)
- [法律与伦理](#法律与伦理)
- [许可证](#许可证)

---

## 简介

MC Scanner 是一个用 Python 编写的 Minecraft 服务器扫描与探测工具。支持端口扫描、SLP 协议探测、离线/正版/白名单认证模式检测、机器人登录发消息、观察者实时监控、AI 托管聊天等功能。提供 Web 控制面板和命令行两种使用方式。

> ⚠️ **本工具仅供安全研究和授权测试使用。** 对未授权服务器进行扫描、登录或命令执行可能违反法律法规。详见[法律与伦理](#法律与伦理)。

---

## 功能一览

### 🔍 扫描与探测

| 功能 | 说明 |
|------|------|
| 多线程端口扫描 | 支持 CIDR 网段、端口范围、主机名 |
| SLP 协议探测 | 版本、玩家数、MOTD、协议号、玩家列表 |
| 认证模式检测 | 离线 / 正版 / 白名单 / 拒绝 |
| 核心类型识别 | vanilla / paper / spigot / forge / fabric 等 |
| masscan 集成 | 大范围扫描自动启用两阶段（masscan探活 → SLP探测） |

### 🤖 机器人与观察者

| 功能 | 说明 |
|------|------|
| 登录发消息 | 登录服务器发送自定义警告消息 |
| AuthMe 支持 | 自动注册 + 登录 |
| 多版本适配 | 协议表从 minecraft-data 自动生成（41个协议版本），重点验证 1.12.2 / 1.20.x / 1.21.x |
| 多机器人并发 | 单台最多 20 个（`warn_bot_max` 可配置） |
| 观察者模式 | 实时监控服务器聊天，关键词告警，聊天记录落盘 |
| 正版账号登录 | 支持 Microsoft 账号 OAuth 设备码流程，多账户管理（**注意：不发送真实聊天签名，强制签名服可能拒收聊天**） |

### 🧠 AI 托管（实验性）

> ⚠️ 以下功能为实验性，可能存在稳定性问题，默认不加载，需在配置中显式启用。

| 功能 | 说明 |
|------|------|
| AI 聊天机器人 | DeepSeek / OpenAI 兼容 API |
| 预设人格 | 16 种，Web 端热更新（增删改即时生效） |
| 多 AI 群聊 | 2-8 个机器人同服互动 |
| 三层记忆系统 | 短期原文（50条）+ 中期话题摘要（3段）+ 长期玩家档案 |
| 自动重连 | 指数退避，最多 10 次，保留聊天记录和记忆 |

### 🛡️ 安全扫描（v3.6.0）

| 模式 | 并发 | 速率 | 适用场景 |
|------|------|------|---------|
| `safe` | 低 | 自适应降速 | 公网/授权测试，低速安全扫描 |
| `balanced` | 中 | 适中 | 默认模式，日常扫描 |
| `aggressive` | 高 | 全速 | 仅内网/信任网络 |

- 端口随机化：打乱扫描顺序，去除顺序递增特征
- 批次冷却：每批扫完暂停，降低连接风暴
- 自适应速率：超时率突变自动降速，连接异常时暂停/中止
- 断点续扫：中断后 `--resume` 从上次位置继续

### 🌐 Web 面板

- 启动后访问 `http://127.0.0.1:8090`
- 扫描任务管理、观察者控制、AI 托管配置、正版账号管理
- 服务器数据库、收藏夹、人数历史曲线
- 默认绑定 `127.0.0.1`；`0.0.0.0` 绑定时输出安全警告

### 🔒 安全与运维

- 全局只读模式：一键锁死警告/AI进服/观察者等操作
- API 按模块限流（scan/warn/ai，可配置次数/分钟）
- 敏感配置支持环境变量 `MC_*` 覆盖
- 定期清理超旧离线记录（可配置保留天数）
- SLP 探测缓存（60 秒 TTL，避免重复探测）

---

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/2584210631-star/mc-scanner-v3.git
cd mc-scanner-v3

# 安装依赖
pip install -r requirements.txt

# （可选）复制配置模板
cp config.example.json config.json
```

### 启动 Web 面板

```bash
python3 cli.py web --port 8090 --host 127.0.0.1
# 打开 http://127.0.0.1:8090
```

### 命令行扫描

```bash
# 单 IP 全端口，安全模式
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode safe

# 网段扫描，平衡模式
python3 cli.py scan 192.168.1.0/24 --mode balanced

# 全端口 + 断点续扫
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode safe --resume

# 只扫端口（不探测 MC 协议）
python3 cli.py portscan 192.168.1.0/24 --port 1-65535 --mode safe

# masscan 大范围扫描（自动两阶段）
python3 cli.py scan 10.0.0.0/8 --port 25565 --use-masscan auto
```

### 正版账号登录

1. Web 面板 → 配置页 → 正版账号 → 「获取设备码」
2. 浏览器打开 `microsoft.com/link`，输入设备码并登录 Microsoft 账号
3. 登录成功后自动保存，观察者/AI 进服时勾选「正版验证」即可使用

### 环境变量（敏感配置）

```bash
MC_AI_API_KEY=your_key
MC_AI_BASE_URL=https://api.deepseek.com
MC_AI_MODEL=deepseek-chat
MC_DISCORD_WEBHOOK=your_webhook
MC_AUTHME_PASSWORD=your_password
```

---

## 项目结构

```
mc-scanner-v3/
├── cli.py                  # 命令行入口
├── config.py               # 配置管理
├── core/
│   ├── bot.py              # Minecraft 机器人核心
│   ├── conn.py             # 连接层（加密/协议）
│   ├── probe.py            # SLP/认证探测
│   ├── microsoft_auth.py   # Microsoft OAuth 正版登录
│   ├── rcon.py             # RCON 远程控制台
│   ├── command_runner.py   # 命令执行器
│   ├── plugins.py          # 插件扫描
│   ├── fingerprint.py      # 服务器指纹识别
│   ├── ai_bot.py           # AI 机器人会话
│   ├── ai_memory.py        # AI 三层记忆
│   ├── ai_personas.py      # AI 人格预设
│   └── protocols/          # 各版本协议实现
├── scanner/
│   ├── safe.py          # 安全扫描配置
│   ├── portscan.py         # 同步端口扫描
│   └── engine.py           # 扫描引擎
├── web/
│   ├── app.py              # Flask 应用
│   ├── index.html          # 前端面板
│   └── routes_*.py         # 各模块 API 路由
├── service/
│   ├── scan_service.py     # 扫描任务服务
│   └── warn_service.py     # 警告机器人服务
├── storage/
│   └── favorites.py        # 收藏管理
├── tools/
│   ├── gen_packets.py      # 协议表自动生成
│   └── send_command.py     # 命令执行工具
├── distributed/            # ⚠️ 实验性：分布式分片扫描
├── android_patches/        # ⚠️ 实验性：Android/Termux 适配补丁
├── tests/                  # 单元测试
├── config.example.json     # 配置模板
├── requirements.txt        # Python 依赖
├── LICENSE                 # MIT 许可证
└── README.md               # 本文件
```

---

## 更新日志

### v3.6.0

**扫描引擎**
- 新增安全扫描引擎：`safe` / `balanced` / `aggressive` 三档模式
- 端口随机化、批次冷却、自适应降速、连接异常检测
- 断点续扫（`--resume`）
- masscan 两阶段集成（大范围自动启用）
- 扫描任务队列（多任务排队执行）

**AI 功能**
- 三层记忆系统（短期原文 + 中期摘要 + 长期玩家档案）
- AI 人格 Web 端热更新
- AI bot / 观察者自动重连（指数退避）

**正版登录**
- Microsoft OAuth 设备码流程
- 多正版账户管理与切换
- 所有进服入口支持正版验证开关
- ⚠️ 当前不发送真实聊天签名（hasSignature=false），开启强制聊天签名的服务器可能拒收聊天消息

**安全加固**
- 全局只读模式
- API 按模块限流
- 0.0.0.0 绑定安全警告
- 定期清理超旧记录

### v3.4.0

- Web 面板模块化拆分（11 个路由模块 + 3 个服务层）
- Web UI 视觉升级 + 移动端适配
- AI 助手浮窗（Agent 模式）
- 服务器健康监控（上线/掉线邮件推送）
- 人数历史曲线、收藏/数据库导出、批量 AI 托管

---

## 法律与伦理

### 使用范围

本工具仅供以下合法用途：
- **安全研究**：在获得明确授权的前提下，对目标系统进行安全评估
- **自有资产巡检**：扫描和管理您自己拥有或管理的服务器
- **授权测试**：在书面授权范围内对第三方系统进行渗透测试

### 禁止行为

使用本工具时，您不得：
- 对未授权的服务器进行端口扫描、服务探测或漏洞扫描
- 登录未授权的服务器（包括离线模式服务器）或以任何方式访问其数据
- 在未授权服务器上执行任何命令（包括但不限于 `/op`、`/gamemode`、`/ban`、`/kick`、`/stop` 等）
- 使用 RCON 功能连接未授权的服务器
- 利用本工具进行 DDoS、僵尸网络、垃圾消息或任何形式的拒绝服务攻击
- 收集、存储或传播第三方服务器的玩家数据、IP 地址或其他个人信息
- 规避或突破任何服务器的安全保护措施（包括但不限于防火墙、白名单、正版验证）

### 各功能使用限制

| 功能 | 合法用途 | 禁止用途 |
|------|---------|---------|
| 端口扫描 / SLP 探测 | 自有网段、授权测试 | 未授权全网扫描、批量探测第三方服务器 |
| 观察者 / AI 进服 | 自有服务器、授权测试 | 未授权登录第三方服务器、骚扰服务器 |
| 命令执行 / RCON | 自有服务器管理、授权运维 | 未授权执行命令、提权、破坏服务器 |
| 多机器人警告 | 自有服务器压力测试 | 对第三方服务器进行消息轰炸或骚扰 |
| 安全扫描 | 授权范围内的低速测试 | 规避检测进行未授权扫描 |

### 数据隐私

- 本工具不会向任何第三方服务器上传您的扫描数据或配置
- 扫描结果仅存储在本地 SQLite 数据库中，由您自行管理
- 请勿将包含真实服务器 IP、玩家信息的扫描结果提交到公开代码仓库
- 建议在 `.gitignore` 中排除 `*.db`、`scan_*.json`、`*_full.json` 等数据文件

### 法律依据

未经授权扫描、登录或控制计算机信息系统，可能违反以下法律法规：
- 《中华人民共和国刑法》第 285 条（非法侵入计算机信息系统罪、非法获取计算机信息系统数据罪、提供侵入/非法控制计算机信息系统程序工具罪）
- 《中华人民共和国刑法》第 286 条（破坏计算机信息系统罪）
- 《中华人民共和国网络安全法》
- 《中华人民共和国数据安全法》
- 《中华人民共和国个人信息保护法》

### 免责声明

- 本工具按"现状"提供，作者不对工具的适用性、可靠性或安全性做任何担保
- 使用者需自行承担使用本工具产生的一切法律责任和后果
- 作者不对因使用本工具而导致的任何直接或间接损失负责
- 如您不同意上述条款，请立即停止使用并删除本工具

---

## 许可证

[MIT License](LICENSE)
