<div align="center">

# 🛡️ MC Scanner v3Pro
### Minecraft 服务器扫描与安全提醒机器人 · 超越版

**整合 V1 功能完整性 + V2 架构优势 · 全版本支持 · Web 控制面板 · 自动离线检测 · SQLite存储 · 协议回退**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/Minecraft-1.12.2~Latest-orange.svg)](#支持版本)
[![Architecture](https://img.shields.io/badge/架构-模块化分层-94D8C3.svg)](#项目结构)

</div>

---

## 📖 简介

MC Scanner v3Pro 是在 mc-scanner V1 和 V2 基础上整合优化的超越版。

**设计理念：** 保留 V1 的全部功能（自动警告、AuthMe、完整 Web 面板、配置文件），套用 V2 的模块化分层架构，吸收两者的增强点（SLP 容错、masscan auto-import、完善测试体系、合规声明）。

**与 V1 相比：** 代码模块化，单文件≤200行，测试更完善，SLP 探测容错更强
**与 V2 相比：** 功能完整不阉割，保留自动警告/AuthMe/完整Web面板/配置文件，MIT许可

---

## ✨ 功能特性

### 核心功能
- 🔍 **多线程端口扫描** — 支持 CIDR 网段、端口范围、主机名，惰性生成器不OOM
- 📡 **SLP 协议探测** — 获取版本、玩家数、MOTD、协议版本，JSON截断容错（Hypixel兼容）
- 🎯 **六态认证检测** — 离线/正版/白名单/拒绝/未知/不可达，白名单关键词自动识别
- 💬 **自动安全警告** — 登录后发送自定义警告消息，支持多条，批量警告
- 🔐 **AuthMe 自动注册** — 自动执行 `/register` + `/login`，密码留空自动生成
- 🔄 **协议多级回退** — 未知协议号自动尝试常见协议号，兼容性更强

### 全版本兼容
- 📦 支持 **Minecraft 1.12.2 ~ 最新版本**（协议 340+）
- 📝 5 种聊天消息格式自动适配（1.12 ~ 1.21.11+）
- 🔧 协议表自动生成：运行 `tools/gen_packets.py` 从官方 minecraft-data 生成

### Web 控制面板（Flask）
- 🌐 浏览器可视化操作，无需记命令
- 📊 实时进度条 + 实时日志输出
- 🔎 结果筛选（认证模式/模组/有人在线）+ 关键词搜索
- 📈 版本分布柱状图
- 💾 一键导出 JSON / CSV
- 🕐 历史记录（最近 20 次任务）
- ⚙️ 配置自动保存到浏览器 localStorage
- 🎯 **单独警告** — 每台服务器点一下就发警告
- ⚡ **批量警告** — 筛选后一键对全部离线服发警告
- 🗄️ **数据库标签页** — SQLite 持久化存储，支持过滤+分页+统计

### 高速扫描
- 🚀 **masscan 集成** — 自动检测，有 masscan 就用（快10倍），没有回退 Python
- 📥 **import 命令** — masscan 扫完的结果可以离线导入再 SLP 探测
- ⚡ **--auto-import** — masscan 扫描后自动导入+认证检测
- ⏱️ **--rate 限速** — 控制每秒连接数，避免被运营商封
- 🚫 **排除列表** — `exclude.conf` 自动过滤私有地址/云厂商段

### 数据存储
- 🗄️ **SQLite 持久化** — 13 字段（含 favicon），UPSERT 去重更新
- 🔍 **query 命令** — 命令行查询数据库，按认证/模组/关键词过滤
- 📊 统计信息：总数/各认证模式分布/有人在线数/版本分布

---

## 🚀 快速开始

### 环境要求
- Python 3.8+（推荐 3.10+）
- Windows / Linux / Mac 均可
- 可选：masscan（全网高速扫描）

### 安装依赖
```bash
pip install -r requirements.txt
```

### 一键启动（推荐）
**Windows:**
```bash
双击 run.bat
```
**Linux/Mac:**
```bash
chmod +x run.sh
./run.sh
```
然后浏览器打开 `http://127.0.0.1:8080`

---

## 💻 命令行用法

### 8 个子命令
```bash
# 1. 只扫描端口
python cli.py portscan 1.2.3.0/24

# 2. 扫描 + SLP 探测 + 认证检测
python cli.py scan 1.2.3.0/24
python cli.py scan 1.2.3.0/24 --workers 300 --timeout 2.0 --rate 500
python cli.py scan 1.2.3.0/24 --web 8080  # 扫描后启动Web面板

# 3. 扫描 + 离线检测 + 自动发警告
python cli.py warn 1.2.3.0/24
python cli.py warn 1.2.3.0/24 -u SecurityBot -m "警告消息" --no-auth
python cli.py warn 1.2.3.0/24 --rate 200 --workers 200 --bot-workers 10

# 4. 使用 masscan 高速扫描
python cli.py masscan --targets 0.0.0.0/0 --rate 10000 --auto-import

# 5. 导入 masscan 结果 + SLP 探测
python cli.py import scan_results.ndjson

# 6. 查询 SQLite 数据库
python cli.py query --stats
python cli.py query --auth cracked --search 1.2.3 --limit 50

# 7. 单独对一台服务器发消息
python cli.py bot 1.2.3.4:25565 -u MyBot -m "你好" --authme password

# 8. 启动 Web 控制面板
python cli.py web --port 8080
```

### 常用参数
| 参数 | 说明 |
|---|---|
| `--workers N` | 探测线程数 |
| `--scan-threads N` | 端口扫描线程数 |
| `--timeout S` | 超时秒数 |
| `--rate N` | 每秒最大连接数（0=不限速） |
| `--exclude 文件` | 排除列表文件 |
| `--no-auth` | 只 SLP 探测，不登录检测 |
| `-u, --username` | 机器人用户名 |
| `-m, --message` | 警告消息（可多次） |
| `-o, --output` | 结果输出文件 |
| `-c, --config` | 配置文件路径 |

---

## ⚙️ 配置文件（config.json）

```json
{
  "username": "SecurityBot",
  "messages": ["警告消息1", "警告消息2"],
  "ports": [25565, 25566, 25570],
  "scan_threads": 200,
  "scan_timeout": 2.5,
  "bot_threads": 10,
  "bot_timeout": 12,
  "message_delay": 0.8,
  "rate": 0,
  "authme_password": "",
  "exclude_file": "exclude.conf",
  "db_path": "mcscanner.db",
  "auto_save_db": true
}
```

---

## 📁 项目结构

```
mc-scanner-v3pro/
├── cli.py                  # 命令行入口（8个子命令）
├── run.py                  # 快速启动
├── run.bat / run.sh        # 一键启动脚本
├── config.json             # 配置文件
├── exclude.conf            # 排除列表
├── targets.txt             # 目标列表示例
├── requirements.txt        # Python 依赖
├── core/                   # 协议核心层
│   ├── buffer.py           # VarInt/字符串/UUID 编解码
│   ├── conn.py             # MCConnection 连接类
│   ├── protocol.py         # 协议常量与版本映射
│   ├── packets.py          # 多版本包 ID 表管理
│   ├── probe.py            # SLP 探测 + 认证检测
│   └── bot.py              # 机器人核心（登录+发消息+AuthMe）
├── scanner/                # 扫描引擎层
│   ├── engine.py           # 综合扫描引擎
│   ├── portscan.py         # 端口扫描
│   ├── masscan.py          # masscan 集成
│   ├── targets.py          # 目标解析
│   ├── exclude.py          # 排除列表
│   └── banner.py           # masscan banner 解析
├── storage/
│   └── db.py               # SQLite 存储层
├── web/
│   ├── app.py              # Web 面板后端（Flask）
│   └── index.html          # Web 面板前端
├── tools/
│   ├── gen_packets.py      # 协议表自动生成器
│   └── send_command.py     # 命令执行工具
├── tests/                  # 测试体系
│   ├── mock_server.py      # Mock Minecraft 服务器
│   ├── test_probe.py       # 探测单元测试
│   ├── test_bot.py         # 机器人单元测试
│   ├── test_e2e.py         # 端到端测试
│   └── test_integration.py # 集成测试
├── NOTICE                  # 来源与致谢
├── LICENSE                 # MIT 许可
└── README.md               # 本文档
```

---

## 🧪 运行测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 或使用 unittest
python -m unittest discover tests -v

# 单个测试
python tests/test_probe.py
python tests/test_bot.py
python tests/test_e2e.py
python tests/test_integration.py
```

---

## 📊 支持版本

| 版本范围 | 协议号 | 聊天格式 | 状态 |
|---|---|---|---|
| 1.12.2 | 340 | simple | ✅ |
| 1.13 - 1.18.2 | 393-758 | simple | ✅ |
| 1.19 | 759 | old_signed_759 | ✅ |
| 1.19.1/2 | 760 | old_signed_760 | ✅ |
| 1.19.3 - 1.20.4 | 761-765 | old_signed_761 | ✅ |
| 1.20.5 - 1.21.11 | 766-774 | new | ✅ |
| 1.21.12+ | 775+ | new | ✅ |

---

## 🔧 高级功能

### 协议表自动生成
从官方 minecraft-data 自动生成协议包 ID 表：
```bash
# 自动下载并生成
python tools/gen_packets.py --download

# 或使用本地路径
python tools/gen_packets.py --data ./minecraft-data --output packets_auto.py
```

### 给服务器发命令
```bash
python tools/send_command.py 1.2.3.4 25565 BotName "op IRmks"
```

### 从文件读取目标
```bash
python cli.py scan @targets.txt
```

---

## ⚠️ 法律与伦理声明

- 本工具仅供安全研究和授权测试使用
- 只扫描您有权访问的服务器，获得授权后再进行测试
- 控制扫描速率，避免对目标造成影响
- 禁止用于未授权访问、破坏或滥用
- 使用者需自行承担使用本工具的法律责任

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE)

来源与致谢详见 [NOTICE](NOTICE)
