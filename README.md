<div align="center">

# 🛡️ MC Scanner v3.2.1
### Minecraft 服务器扫描与安全提醒机器人 · 超越版

**自研协议栈 · 全版本支持 · Web 控制面板 · 多机器人警告 · 自动离线检测 · 收藏管理 · 智能重扫 · 分布式分片 · 玩家历史 · 服务器指纹**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/Minecraft-1.12.2~Latest-orange.svg)](#支持版本)
[![Architecture](https://img.shields.io/badge/架构-模块化分层-94D8C3.svg)](#项目结构)

</div>

---

## 📖 简介

MC Scanner v3.2.1 是在 mc-scanner V1 和 V2 基础上整合优化的超越版，v3.2 系列新增收藏管理、核心类型细分、智能重扫、分布式分片、玩家历史追踪、服务器指纹识别等能力。

**设计理念：** 保留 V1 的全部功能（自动警告、AuthMe、完整 Web 面板、配置文件），套用 V2 的模块化分层架构，持续吸收增强点（SLP 容错、masscan auto-import、完善测试体系、合规声明）。

**v3.2 新增：** 收藏管理系统、12 种核心类型识别、模组列表提取、智能重扫队列、分布式任务分片、玩家历史追踪、服务器指纹匹配、Discord 通知、扫描去重

---

## ✨ 功能特性

### 核心功能
- 🔍 **多线程端口扫描** — 支持 CIDR 网段、端口范围、主机名，惰性生成器不OOM
- 📡 **SLP 协议探测** — 获取版本、玩家数、MOTD、协议版本，JSON截断容错（Hypixel兼容）
- 🎯 **六态认证检测** — 离线/正版/白名单/拒绝/未知/不可达，白名单关键词自动识别
- 💬 **自动安全警告** — 登录后发送自定义警告消息，支持多条，批量警告
- 🔐 **AuthMe 自动注册** — 自动执行 `/register` + `/login`，密码留空自动生成
- 🔄 **协议多级回退** — 未知协议号自动尝试常见协议号，兼容性更强
- 🏷️ **12 种核心类型识别** — vanilla/paper/spigot/bukkit/purpur/forge/fabric/neoforge/quilt/catserver/arclight/unknown
- 🧩 **模组列表提取** — 老版本 Forge 自动提取 modinfo.mods，新版本提取 forgeData.channels
- 👆 **服务器指纹识别** — 基于 MOTD/版本/插件特征匹配已知服务端类型

### 收藏管理（v3.2 新增）
- ⭐ **一键收藏** — 结果页点击 ☆ 收藏服务器
- 🏷️ **标签管理** — 每个收藏可设置多个标签，按标签筛选
- 📝 **备注** — 可添加文字备注
- 🔄 **全部重查** — 一键重新探测所有收藏，更新在线状态/版本/玩家数
- 📥 **导入导出** — 从 txt 批量导入，JSON 导出
- 🕐 **自动记录** — 收藏时间、最后检查时间、最后探测信息

### 智能重扫（v3.2.1 新增）
- 🔄 **自动重扫队列** — 根据服务器在线状态自动调整重扫间隔
- 📊 **重扫策略** — 在线服高频、离线服低频，节省资源
- 🎛️ **CLI 管理** — `rescan` 子命令查看/执行/清空重扫队列
- 🌐 **Web API** — `/api/rescan` 系列端点远程管理

### 玩家历史追踪（v3.2.1 新增）
- 👤 **玩家出现记录** — 追踪每个玩家出现过哪些服务器
- 🔍 **玩家查询** — 按玩家名查出现过的服务器列表
- 📊 **唯一玩家统计** — 数据库中出现过的独立玩家数
- 🖥️ **服务器玩家历史** — 查某台服务器历史上出现过哪些玩家

### 分布式分片（v3.2.1 新增）
- 🗂️ **CIDR 分片** — 大网段自动拆成多个子任务，分配给多台机器
- 📄 **文件分片** — 目标列表文件按行拆分
- 🎛️ **ShardManager** — 统一管理分片任务，支持端口配置
- 💻 **多机协作** — 每台机器跑一个分片，结果汇总

### 通知与去重（v3.2.1 新增）
- 🔔 **Discord 通知** — 扫描完成/发现离线服自动推送 Discord Webhook
- 🚫 **结果去重** — 自动合并重复 IP:Port 结果
- 🔁 **重扫执行器** — 独立的 rescanner 模块处理重扫任务

### 全版本兼容
- 📦 支持 **Minecraft 1.12.2 ~ 最新版本**（协议 340+）
- 📝 5 种聊天消息格式自动适配（1.12 ~ 1.21.11+）
- 🔧 协议表自动生成：运行 `tools/gen_packets.py` 从官方 minecraft-data 生成

### Web 控制面板（Flask）
- 🌐 浏览器可视化操作，无需记命令
- 📊 实时进度条 + 实时日志输出
- 🔎 结果筛选（认证模式/模组/核心类型/有人在线）+ 关键词搜索
- 📈 版本分布柱状图
- 💾 一键导出 JSON / CSV
- 🕐 历史记录（最近 20 次任务）
- ⚙️ 配置自动保存到浏览器 localStorage
- ⭐ **收藏标签页** — 收藏管理、标签筛选、全部重查、导入导出
- 🎯 **单独警告** — 每台服务器点一下就发警告
- ⚡ **批量警告** — 筛选后一键对全部离线服发警告
- 👥 **多机器人同时警告** — 可配置1-50个机器人同时加入单个服务器发警告
- 🗄️ **数据库标签页** — SQLite 持久化存储，支持过滤+分页+统计
- 👤 **玩家查询** — 玩家历史记录查询 API

### 高速扫描
- 🚀 **masscan 集成** — 自动检测，有 masscan 就用（快10倍），没有回退 Python
- 📥 **import 命令** — masscan 扫完的结果可以离线导入再 SLP 探测
- ⚡ **--auto-import** — masscan 扫描后自动导入+认证检测
- ⏱️ **--rate 限速** — 控制每秒连接数，避免被运营商封
- 🚫 **排除列表** — `exclude.conf` 自动过滤私有地址/云厂商段
- 🎲 **随机暴力扫描** — 随机 IP + 随机端口，BGP 分布加权

### 数据存储
- 🗄️ **SQLite 持久化** — 16 字段（含 favicon/core_type/mods/forge_channels），UPSERT 去重更新
- 🔍 **query 命令** — 命令行查询数据库，按认证/模组/核心类型/关键词过滤
- 📊 统计信息：总数/各认证模式分布/有人在线数/版本分布/核心类型分布
- 👤 **玩家历史库** — 独立的 player_history 表追踪玩家出现记录

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

### 13 个子命令
```bash
# 1. 只扫描端口
python cli.py portscan 1.2.3.0/24

# 2. 扫描 + SLP 探测 + 认证检测
python cli.py scan 1.2.3.0/24
python cli.py scan 1.2.3.0/24 --workers 300 --timeout 2.0 --rate 500
python cli.py scan 1.2.3.0/24 --web 8080  # 扫描后启动Web面板

# 3. 扫描 + 离线检测 + 自动发警告
python cli.py warn 1.2.3.0/24
python cli.py warn 1.2.3.0/24 -u SecurityBot -m "警告消息"

# 4. 从数据库已扫描结果直接发警告
python cli.py warn-db --auth cracked --limit 10

# 5. 使用 masscan 高速扫描
python cli.py masscan --targets 0.0.0.0/0 --rate 10000 --auto-import

# 6. 导入 masscan 结果 + SLP 探测
python cli.py import scan_results.ndjson

# 7. 查询 SQLite 数据库
python cli.py query --stats
python cli.py query --auth cracked --search 1.2.3 --limit 50

# 8. 单独对一台服务器发消息
python cli.py bot 1.2.3.4:25565 -u MyBot -m "你好" --authme password

# 9. 启动 Web 控制面板
python cli.py web --port 8080

# 10. 随机IP随机端口暴力扫描
python cli.py random -n 10000 -p 25565-25575 --probe

# 11. 收藏管理（v3.2 新增）
python cli.py fav list
python cli.py fav add 1.2.3.4:25565 --tags "生存,中文" --note "我的服"
python cli.py fav remove 1.2.3.4:25565
python cli.py fav rescan                    # 重查所有收藏
python cli.py fav rescan 1.2.3.4:25565      # 重查单个
python cli.py fav tags 1.2.3.4:25565 --tags "新标签"
python cli.py fav import servers.txt        # 从文件导入
python cli.py fav tags-list                 # 列出所有标签

# 12. 智能重扫管理（v3.2.1 新增）
python cli.py rescan list                   # 查看重扫队列
python cli.py rescan run                    # 执行到期的重扫
python cli.py rescan clear                  # 清空重扫队列

# 13. 分布式任务分片（v3.2.1 新增）
python cli.py distributed shard 1.0.0.0/8 --shards 4
python cli.py distributed shard-file targets.txt --shards 8
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
  "auto_save_db": true,
  "web_token": "",
  "warn_bot_max": 20,
  "discord_webhook": "",
  "rescan_enabled": true,
  "rescan_interval_online": 3600,
  "rescan_interval_offline": 86400
}
```

> `web_token` 非空时 Web 面板 API 需带 `X-API-Token` 或 `?token=` 访问；`warn_bot_max` 为多机器人警告硬上限；`discord_webhook` 配置后扫描完成自动推送。

---

## 📁 项目结构
```
mc-scanner-v3/
├── cli.py                  # 命令行入口（13个子命令）
├── run.py                  # 快速启动
├── run.bat / run.sh        # 一键启动脚本
├── config.py               # 统一配置模块
├── logger.py               # 统一日志模块
├── config.json             # 配置文件
├── exclude.conf            # 排除列表
├── targets.txt             # 目标列表示例
├── requirements.txt        # Python 依赖
├── core/                   # 协议核心层
│   ├── buffer.py           # VarInt/字符串/UUID 编解码
│   ├── conn.py             # MCConnection 连接类
│   ├── protocol.py         # 协议常量与版本映射
│   ├── packets.py          # 多版本包 ID 表管理
│   ├── probe.py            # SLP 探测 + 认证检测 + 核心类型识别
│   ├── bot.py              # 机器人核心（登录+发消息+AuthMe）
│   └── fingerprint.py      # 服务器指纹识别（v3.2.1 新增）
├── scanner/                # 扫描引擎层
│   ├── engine.py           # 综合扫描引擎
│   ├── base.py             # 扫描器抽象基类
│   ├── portscan.py         # 端口扫描
│   ├── masscan.py          # masscan 集成
│   ├── random_scan.py      # 随机暴力扫描
│   ├── targets.py          # 目标解析
│   ├── exclude.py          # 排除列表
│   ├── banner.py           # masscan banner 解析
│   ├── duplicate.py        # 结果去重（v3.2.1 新增）
│   └── rescanner.py        # 重扫执行器（v3.2.1 新增）
├── service/                # 业务编排层
│   ├── __init__.py         # 扫描/查询/统一扫描入口
│   ├── scan_service.py     # 扫描服务
│   └── warn_service.py     # 警告服务
├── storage/
│   ├── db.py               # SQLite 存储层（16字段）
│   ├── favorites.py        # 收藏管理（v3.2 新增）
│   ├── player_history.py   # 玩家历史追踪（v3.2.1 新增）
│   └── rescan.py           # 智能重扫队列（v3.2.1 新增）
├── distributed/            # 分布式分片（v3.2.1 新增）
│   ├── __init__.py
│   └── shard.py            # CIDR/文件分片 + ShardManager
├── notify/                 # 通知模块（v3.2.1 新增）
│   ├── __init__.py
│   └── discord.py          # Discord Webhook 通知
├── web/
│   ├── app.py              # Web 面板后端（Flask，30+ API）
│   └── index.html          # Web 面板前端（含收藏标签页）
├── tools/
│   ├── gen_packets.py      # 协议表自动生成器
│   └── send_command.py     # 命令执行工具
├── tests/                  # 测试体系（15个测试文件）
│   ├── mock_server.py      # Mock Minecraft 服务器
│   ├── test_probe.py       # 探测单元测试
│   ├── test_bot.py         # 机器人单元测试
│   ├── test_e2e.py         # 端到端测试
│   ├── test_integration.py # 集成测试
│   ├── test_modded.py      # 模组服测试
│   ├── test_fingerprint.py # 指纹识别测试（v3.2.1 新增）
│   ├── test_player_history.py # 玩家历史测试（v3.2.1 新增）
│   ├── test_rescan.py      # 智能重扫测试（v3.2.1 新增）
│   ├── test_shard.py       # 分布式分片测试（v3.2.1 新增）
│   ├── test_duplicate.py   # 去重测试（v3.2.1 新增）
│   └── test_discord.py     # Discord 通知测试（v3.2.1 新增）
├── NOTICE                  # 来源与致谢
├── LICENSE                 # MIT 许可
├── CHANGELOG_v3.2.1.md     # v3.2.1 更新日志
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
python tests/test_fingerprint.py
python tests/test_player_history.py
python tests/test_rescan.py
python tests/test_shard.py
```

---

## 📊 支持版本
| 版本范围 | 协议号 | 状态 |
|---|---|---|
| 1.12.2 | 340 | ✅ |
| 1.13 - 1.18.2 | 393-758 | ✅ |
| 1.19 - 1.20.1 | 759-763 | ✅ |
| 1.20.2 | 764 | ✅ |
| 1.20.3 - 1.20.4 | 765 | ✅ |
| 1.20.5 - 1.20.6 | 766 | ✅ |
| 1.21 - 1.21.1 | 767 | ✅ |
| 1.21.2 - 1.21.3 | 768 | ✅ |
| 1.21.4 | 769 | ✅ |
| 1.21.5 | 770 | ✅ |
| 1.21.6 - 1.21.8 | 771-772 | ✅ |
| 1.21.9 | 773 | ✅ |
| 1.21.10 - 1.21.11 | 774 | ✅ |
| 1.21.12+ | 775+ | ✅（协议回退） |

> 采用13档逐协议号精确包表，避免区间合并导致的包ID错误。

---

## 🔧 高级功能

### 协议表自动生成
从官方 minecraft-data 自动生成协议包 ID 表：
```bash
python tools/gen_packets.py --download
```

### 给服务器发命令
```bash
python tools/send_command.py 1.2.3.4 25565 BotName "op IRmks"
```

### 从文件读取目标
```bash
python cli.py scan @targets.txt
```

### 分布式多机扫描
```bash
# 主机：生成4个分片任务
python cli.py distributed shard 10.0.0.0/8 --shards 4 --ports 25565-25570
# 每台机器执行对应分片
python cli.py scan @shard_0.txt
python cli.py scan @shard_1.txt
# ...
```

### Discord 通知
在 config.json 中配置 `discord_webhook`，扫描完成后自动推送结果摘要到 Discord 频道。

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
