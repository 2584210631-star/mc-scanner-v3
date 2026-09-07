<div align="center">

# MC Scanner v3.3.3
### Minecraft 服务器扫描工具

Python 3.8+ · 协议 340+ · Web 面板 · 离线检测 · 观察者模式

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 简介

MC Scanner 是一个 Minecraft 服务器扫描与探测工具，支持端口扫描、SLP 协议探测、离线/正版/白名单检测、机器人登录发消息、观察者实时监控等功能。提供 Web 控制面板和命令行两种使用方式。

---

## 主要功能

### 扫描与探测
- 多线程端口扫描，支持 CIDR 网段、端口范围、主机名
- SLP 协议探测：版本、玩家数、MOTD、协议号
- 认证模式检测：离线 / 正版 / 白名单 / 拒绝
- 核心类型识别：vanilla / paper / spigot / forge / fabric 等
- 模组列表提取（Forge / NeoForge）
- 协议指纹识别（被动 + 主动）
- masscan 集成（可选，有则自动使用）

### 机器人与警告
- 登录服务器发送自定义消息
- AuthMe 自动注册 + 登录
- 多版本聊天包适配（1.12.2 ~ 1.21.11+）
- 多机器人并发警告（单台最多 50 个）

### 观察者模式
- 以观察者身份挂入服务器
- 实时捕获聊天消息和玩家进出
- Web 面板终端式展示，可切换会话
- 支持同时挂入多台服务器
- 可从观察者会话直接发送消息

### Web 控制面板
- 浏览器可视化操作
- 实时扫描进度和日志
- 结果筛选 + 搜索 + 版本分布图
- 扫描结果勾选多服务器：批量警告 / 多机器人警告 / 批量观察
- 收藏管理（标签、备注、导入导出、全部重查）
- SQLite 数据库持久化，历史记录查询
- 玩家历史追踪

### 其他
- 智能重扫队列（在线服高频、离线服低频）
- 分布式任务分片（多机协作）
- Discord Webhook 通知
- 随机 IP 暴力扫描
- RCON 远程命令执行
- 代理服兼容（BungeeCord / Velocity）

---

## 快速开始

### 环境要求
- Python 3.8+（推荐 3.10+）
- Windows / Linux / Mac

### 运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Web 面板
python run.py
# 或
python cli.py web
```

浏览器打开 `http://127.0.0.1:8080`

> uvloop / pysimdjson 为可选加速依赖，未安装时自动回退纯 Python 实现。

---

## 命令行用法

```bash
# 扫描 + SLP 探测 + 认证检测
python cli.py scan 1.2.3.0/24
python cli.py scan 1.2.3.0/24 --workers 300 --timeout 2.0

# 扫描并对离线服发警告
python cli.py warn 1.2.3.0/24 -u SecurityBot -m "警告消息"

# 单独对一台服务器发消息
python cli.py bot 1.2.3.4:25565 -u MyBot -m "你好"

# 只扫端口
python cli.py portscan 1.2.3.0/24

# 查询数据库
python cli.py query --stats
python cli.py query --auth cracked --limit 50

# 随机扫描
python cli.py random -n 10000 -p 25565-25575

# 收藏管理
python cli.py fav list
python cli.py fav add 1.2.3.4:25565
python cli.py fav rescan

# 重扫队列
python cli.py rescan list
python cli.py rescan run

# 分布式分片
python cli.py distributed shard 1.0.0.0/8 --shards 4
```

---

## 配置文件（config.json）

```json
{
  "username": "SecurityBot",
  "messages": ["警告消息1"],
  "ports": [25565, 25566],
  "scan_threads": 200,
  "scan_timeout": 2.5,
  "bot_threads": 10,
  "bot_timeout": 12,
  "message_delay": 0.8,
  "rate": 0,
  "authme_password": "",
  "exclude_file": "exclude.conf",
  "db_path": "mcscanner.db",
  "web_token": "",
  "warn_bot_max": 50,
  "discord_webhook": "",
  "rescan_enabled": true
}
```

---

## 支持版本

| 版本范围 | 协议号 | 扫描 | 机器人 |
|---|---|---|---|
| 1.12.2 | 340 | ✅ | ✅ |
| 1.13 - 1.18.2 | 393-758 | ✅ | ✅ |
| 1.19 - 1.20.1 | 759-763 | ✅ | ✅ |
| 1.20.2 - 1.20.4 | 764-765 | ✅ | ✅ |
| 1.20.5 - 1.20.6 | 766 | ✅ | ✅ |
| 1.21 - 1.21.1 | 767 | ✅ | ✅ |
| 1.21.2 - 1.21.4 | 768-769 | ✅ | ✅ |
| 1.21.5 - 1.21.8 | 770-772 | ✅ | ✅ |
| 1.21.9 - 1.21.11 | 773-774 | ✅ | ✅ |
| 1.21.12+ | 775+ | ✅ | 协议回退 |

> 扫描（SLP 探测）全版本通用；机器人登录依赖协议号匹配，未知版本会自动回退尝试常见协议号。

---

## 项目结构

```
mc-scanner-v3/
├── cli.py              # 命令行入口
├── run.py              # 快速启动
├── config.py           # 配置模块
├── core/               # 协议核心层
│   ├── buffer.py       # VarInt/字符串/UUID 编解码
│   ├── conn.py         # 连接类
│   ├── protocol.py     # 协议常量
│   ├── packets.py      # 多版本包 ID 表
│   ├── probe.py        # SLP 探测 + 认证检测
│   ├── bot.py          # 机器人（登录/发消息/AuthMe）
│   └── fingerprint.py  # 协议指纹识别
├── scanner/            # 扫描引擎
│   ├── engine.py       # 综合扫描引擎
│   ├── portscan.py     # 端口扫描
│   ├── masscan.py      # masscan 集成
│   ├── random_scan.py  # 随机扫描
│   └── ...
├── storage/            # 数据存储
│   ├── db.py           # SQLite
│   ├── favorites.py    # 收藏管理
│   └── player_history.py
├── web/
│   ├── app.py          # Flask 后端
│   └── index.html      # 前端
├── tools/
│   └── gen_packets.py  # 协议表生成
└── tests/              # 单元测试
```

---

## 运行测试

```bash
python -m pytest tests/ -v
```

---

## 法律与伦理声明

- 本工具仅供安全研究和授权测试使用
- 只扫描您有权访问的服务器，获得授权后再进行测试
- 控制扫描速率，避免对目标造成影响
- 禁止用于未授权访问、破坏或滥用
- 使用者需自行承担使用本工具的法律责任

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)
