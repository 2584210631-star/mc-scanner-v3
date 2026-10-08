<div align="center">

```text
  ◆──────────────────────────────────────◆
  ███╗   ███╗ ██████╗    ███████╗ ██████╗
  ████╗ ████║██╔════╝    ██╔════╝██╔════╝
  ██╔████╔██║██║         ███████╗██║
  ██║╚██╔╝██║██║         ╚════██║██║
  ██║ ╚═╝ ██║╚██████╗    ███████║╚██████╗
  ╚═╝     ╚═╝ ╚═════╝    ╚══════╝ ╚═════╝
  ◆──────────────────────────────────────◆
```

# 🛠️ MC Scanner v3.6.4

### Minecraft 服务器扫描 · 探测 · 观察者 · 安全提醒 / Minecraft Server Scanner · Probe · Observer · Security Alert

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-00d992.svg)](LICENSE)
[![Protocol](https://img.shields.io/badge/协议表-41%20版本%20(340%2B)-10b981.svg)](#协议与版本)
[![Tests](https://img.shields.io/badge/测试-193%20通过-00d992.svg)](#测试)
[![Platform](https://img.shields.io/badge/平台-Linux%20%7C%20macOS%20%7C%20Windows%20%7C%20Termux-555555.svg)](#)

**端口扫描 · SLP 探测 · 认证检测 · 观察者 · AI 托管 · 安全扫描 · Web 面板**

</div>

---

## 📑 目录

| | | |
|:---:|:---:|:---:|
| [🧭 简介](#-简介) | [✨ 功能一览](#-功能一览) | [🚦 能力边界](#-能力边界诚实对照) |
| [🚀 快速开始](#-快速开始) | [🧩 项目结构](#-项目结构) | [🧪 测试](#-测试) |
| [📜 更新日志](#-更新日志) | [⚖️ 法律与伦理](#️-法律与伦理) | [📄 许可证](#-许可证) |

---

## 🧭 简介

**MC Scanner** 是一个纯 Python 编写的 Minecraft 服务器扫描与探测工具，提供 **Web 控制面板** 和 **命令行** 两种使用方式。

它能做的事：扫描网段端口、通过 SLP 协议获取服务器信息（版本 / MOTD / 玩家数 / 在线玩家）、识别认证模式（离线 / 正版 / 白名单）、以机器人身份登录发消息、用观察者实时监控聊天、以及（实验性的）AI 托管聊天。

> 本项目是一个**功能完整的个人工具**，定位是「授权范围内的服务器巡检与安全提醒」，不是通用 Minecraft 客户端，也不鼓励任何未授权访问。

```text
┌─ 典型工作流 ─────────────────────────────────────────────┐
│  端口扫描  →  SLP 探测  →  认证识别  →  观察者 / 安全提醒  │
│  (找端口)    (取信息)     (离线/正版)    (监控 / 告知)      │
└──────────────────────────────────────────────────────────┘
```

---

## ✨ 功能一览

### 🔍 扫描与探测

| 功能 | 说明 |
|------|------|
| 多线程 / 异步端口扫描 | 支持 CIDR 网段、端口范围、主机名 |
| SLP 协议探测 | 版本、玩家数、MOTD、协议号、玩家列表 |
| 认证模式检测 | 离线 / 正版 / 白名单 / 拒绝 四态 |
| 核心 / 模组识别 | vanilla · paper · spigot · forge · fabric · neoforge 等 |
| masscan 两阶段集成 | 大范围自动 masscan 探活 → SLP 探测 |

### 🤖 机器人与观察者

| 功能 | 说明 |
|------|------|
| 登录发消息 | 登录服务器发送自定义消息 |
| AuthMe 支持 | `auto` / `login_only` / `register_then_login` 三种模式，按服务器反馈分支 |
| 多版本适配 | 协议表由 minecraft-data 自动生成（41 个协议版本） |
| 多机器人并发 | 单台上限可配置（`warn_bot_max`） |
| 观察者模式 | 实时监控聊天、关键词处理、记录落盘、断线指数退避重连 |
| 正版账号登录 | Microsoft 账号 OAuth 设备码流程，多账户管理 |

### 🧠 AI 托管（实验性）

> 实验性功能，默认不加载，需在配置中显式启用。

| 功能 | 说明 |
|------|------|
| AI 聊天机器人 | 兼容 DeepSeek / OpenAI 等接口 |
| 预设人格 | 多种人格，Web 端可编辑 |
| 多 AI 群聊 | 多个机器人同服互动 |
| 分层记忆 | 短期原文 + 中期摘要 + 长期玩家档案（可随时清除） |
| 安全护栏 | AI 回复以 `/` 开头会被拦截，API 连续失败自动退避 |

### 🛡️ 扫描模式

| 模式 | 并发 | 速率 | 适用场景 |
|------|------|------|---------|
| `safe` | 低 | 自适应降速 | 公网 / 授权测试，低速温和 |
| `balanced` | 中 | 适中 | 默认模式，日常扫描 |
| `aggressive` | 高 | 全速 | **仅内网 / 信任网络** |

- **多任务并发**：可同时运行多个扫描任务（`max_concurrent_scans`，默认 2），超出上限自动排队、跑完自动续启；扫描期间**进服、收藏重查、观察者、AI、健康监控均可并行**，互不阻塞
- **批次冷却**：每批扫完暂停，降低连接风暴
- **自适应速率**：超时率突变自动降速，连接异常时暂停 / 中止
- **断点续扫**：中断后 `--resume` 从上次位置继续（进度文件带版本校验，损坏即拒绝）

### 🌐 Web 面板

- 启动后访问 `http://127.0.0.1:8090`
- **无登录认证**：本工具默认绑定 `127.0.0.1` 本地使用，不设登录；若绑定 `0.0.0.0` 局域网可访问，**任何人都能操作，请确保网络可信**
- 深色界面，**桌面端 / 移动端自适应**
- 扫描任务、观察者、AI 托管、正版账号、数据库、收藏、人数历史一站管理
- 顶部常显当前能力状态徽章；默认绑定 `127.0.0.1`（本地使用）

### 🔒 安全与运维

- **能力分级开关**：扫描（默认开）/ 登录交互 / RCON 命令（默认关）
- **全局只读模式**：一键锁死所有写操作
- **操作审计日志**：写操作记录来源、目标、动作、结果
- API 按模块限流；敏感配置支持 `MC_*` 环境变量覆盖
- SLP 探测缓存，避免重复探测

### 💓 健康监控（收藏）

- 周期探测收藏服务器，记录在线/离线、人数、玩家进出，变化可汇总邮件
- **温和探测速率**（避免被限速/拉黑）：并发 ≤ `health_probe_concurrency`（默认 8）；同一 IP 两次探测间隔 ≥ `health_probe_ip_gap` 秒（默认 1.5）；每轮间隔 `health_interval` 秒（默认 300）——均在 Web 设置页或 `config.json` 可调
- 监控用 fast 模式只试自动版本不遍历所有协议，55个目标十几秒跑完；发现认证缺失时自动补一次认证检测
- 默认还会带上数据库里"有人气"的服务器（最多 20 个）；只想监控收藏时设 `health_monitor_db_extra: false`

---

## 🚦 能力边界（诚实对照）

为了不夸大，这里如实说明当前版本「能做什么、做不到什么」：

| 场景 | 状态 | 说明 |
|------|:----:|------|
| 端口扫描 / SLP 信息探测 | ✅ 可靠 | 主路径，覆盖各版本 |
| 离线（offline）服登录 + 发消息 | ✅ 可靠 | 安全提醒的主要场景 |
| 正版（online）服登录 | ✅ 可用 | 需先完成 Microsoft OAuth |
| 正版服**发送聊天** | ✅ 可用 | 正版登录后自动获取Mojang签发的RSA证书，用 pycryptodome 做 RSA-2048+SHA256 签名；签名失败自动回退无签名模式 |
| Forge / Fabric / NeoForge 模组服 | ⚠️ 部分 | 以原版姿态可通过部分验收；强制模组校验的服无法进入 |
| 1.12.2 等旧版本 | ⚠️ 尽力 | 协议表已覆盖并重点验证，但边缘情况较多 |
| 通用 Minecraft 客户端 | ❌ 非目标 | 不做完整游戏操作 / 真实签名 / 模组加载 |
| 未授权全网扫描 | 🚫 禁止 | 见[法律与伦理](#️-法律与伦理) |

---

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/2584210631-star/mc-scanner-v3.git
cd mc-scanner-v3
# 扫描/SLP探测/离线服警告：依赖已自带在 libs/，无需 pip install
# 以正版账号登录进服（可选）：需额外安装 pycryptodome
#   pip install pycryptodome
# 如需其他额外依赖（如 masscan）可执行：pip install -r requirements.txt
cp config.example.json config.json   # 可选
```

### 启动 Web 面板

```bash
python3 cli.py web --port 8090 --host 127.0.0.1
# 浏览器打开 http://127.0.0.1:8090
```

### 命令行扫描

```bash
# 单 IP 全端口，安全模式
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode safe

# 网段扫描，平衡模式
python3 cli.py scan 192.168.1.0/24 --mode balanced

# 断点续扫
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode safe --resume

# 只扫端口（不探测 MC 协议）
python3 cli.py portscan 192.168.1.0/24 --port 1-65535

# masscan 大范围扫描（自动两阶段）
python3 cli.py scan 10.0.0.0/8 --port 25565 --use-masscan auto
```

### 正版账号登录（设备码）

1. Web 面板 → 设置页 → 正版账号 →「获取设备码」
2. 浏览器打开 `microsoft.com/link`，输入设备码并登录
3. 成功后自动保存；观察者 / AI 进服时**手动勾选**「正版验证」即可

### 环境变量（敏感配置）

```bash
MC_AI_API_KEY=your_key
MC_AI_BASE_URL=https://api.deepseek.com
MC_AI_MODEL=deepseek-chat
MC_DISCORD_WEBHOOK=your_webhook
MC_AUTHME_PASSWORD=your_password
```

### 命令行退出码

| 码 | 含义 |
|:---:|------|
| 0 | 成功 |
| 1 | 无结果 / 失败 |
| 2 | 高速模式未确认 |
| 3 | 参数错误（缺参数 / 缺 `--yes`） |
| 4 | 能力开关拒绝 |

---

## 🧩 项目结构

```text
mc-scanner-v3/
├── cli.py                  # 命令行入口
├── config.py               # 配置管理
├── core/
│   ├── bot.py              # Minecraft 机器人核心
│   ├── conn.py             # 连接层（加密 / 协议）
│   ├── probe.py            # SLP / 认证探测
│   ├── protocol.py         # 版本映射 / 协议常量
│   ├── packets.py          # 协议表加载与完整性校验
│   ├── packets_auto.py     # 自动生成协议表（41 版本）
│   ├── microsoft_auth.py   # Microsoft OAuth 正版登录
│   ├── ed25519.py          # 纯Python Ed25519签名（零外部依赖）
│   ├── errors.py           # 统一错误码与映射
│   ├── nbt.py / chat.py    # NBT / JSON 文本解析
│   ├── buffer.py           # 字节流工具
│   ├── rcon.py             # RCON 远程控制台
│   ├── command_runner.py   # 命令执行器
│   ├── plugins.py          # 插件 / 反作弊识别
│   ├── fingerprint.py      # 服务器指纹
│   ├── ai_bot.py           # AI 机器人会话
│   ├── ai_memory.py        # AI 分层记忆
│   ├── ai_personas.py      # AI 人格预设
│   └── protocols/          # 各版本协议 handler
├── scanner/
│   ├── safe.py             # 安全扫描配置 / 进度存储
│   ├── async_engine.py     # 异步流水线
│   ├── portscan.py         # 同步端口扫描
│   └── engine.py           # 扫描引擎
├── web/
│   ├── app.py              # Flask 应用
│   ├── index.html          # 前端面板（桌面 / 移动自适应）
│   ├── state.py            # 共享状态
│   └── routes_*.py         # 各模块 API 路由
├── service/                # 扫描 / 警告任务服务
├── storage/                # 收藏等持久化
├── tools/
│   ├── gen_packets.py      # 协议表自动生成
│   ├── get_mc_token.py     # 正版设备码工具
│   └── send_command.py     # 命令发送工具（需授权，谨慎使用）
├── distributed/            # ⚠️ 实验性：分布式分片
├── android_patches/        # ⚠️ 实验性：Termux 适配
├── tests/                  # 单元 / 集成测试
├── config.example.json     # 配置模板
├── requirements.txt        # 依赖
├── LICENSE                 # MIT
└── README.md
```

---

## 🧪 测试

```bash
python3 -m pytest tests/ -q
```

当前 **193 个测试全部通过**，覆盖：协议表完整性、版本映射、认证探测、Login Start分档、Client Settings分档、AuthMe分支、进度存储、AI安全护栏、失败路径、无报告协议回退等。

重新生成协议表：

```bash
python3 tools/gen_packets.py --download
```

---

## 📜 更新日志 / Changelog

<details>
<summary><b>v3.6.4</b>（点击展开 / Click to expand）</summary>

**NeoForge 识别修复 / NeoForge Detection Fix**
- NeoForge 1.20.2+ 不在 SLP 响应暴露 `forgeData`/`modinfo`，纯 SLP 探测会误判为 vanilla
- 现在通过登录握手阶段的 LoginPluginRequest 频道（`neoforge:login` / `fml:loginwrapper`）自动修正 core_type
- 同步引擎和异步引擎均已接入；需开启认证检测（默认开启）才生效
- NeoForge 1.20.2+ no longer exposes `forgeData`/`modinfo` in SLP responses, causing false "vanilla" detection. Now corrected via LoginPluginRequest channels captured during auth probe (`neoforge:login` / `fml:loginwrapper`). Requires auth detection enabled (default on).

**人数趋势图修复 / Popularity Chart Fix**
- 修复收藏页人数趋势图不渲染：`popChart` 是 `<div>` 而非 `<canvas>`，无数据时写入的 `<p>` 标签残留导致 Chart.js 初始化失败
- 现在有数据时先清空 div 再创建 canvas 元素
- Fixed popularity chart not rendering: `popChart` was a `<div>` (not `<canvas>`), leftover "no data" `<p>` tag caused Chart.js init failure. Now clears div and creates canvas before chart init.

**扫描进度优化 / Scan Progress Optimization**
- 自适应限速器初始速率取 `min(用户配置, profile上限)`，不再被 profile 默认值覆盖
- 初始批次从 200 改为 `max_workers*2`，避免提交全部目标才进主循环
- 端口扫描进度步长动态化：`max(1, min(500, total//100))`，小目标也能实时更新
- Adaptive rate limiter now uses `min(user_config, profile_cap)` as initial rate. Initial batch reduced from 200 to `max_workers*2`. Port scan progress step is now dynamic (`max(1, min(500, total//100))`).

**路径基准统一 / Path Resolution Unification**
- `config.json` 中相对路径（如 `db_path`）统一以配置文件所在目录为基准解析，不再混用 CWD 和仓库目录
- 修复子目录配置文件保存后路径叠层的 bug
- Relative paths in `config.json` (e.g. `db_path`) are now resolved relative to the config file's directory, fixing path-stacking bugs when config is in a subdirectory.

**依赖清理 / Dependency Cleanup**
- 删除 `libs/uvloop` 和 `libs/simdjson` 空壳（仅有源码无编译产物 `.so`，约 8MB 死重量）
- `run.py` 移除自动 pip install 逻辑和空转导入循环
- Removed `libs/uvloop` and `libs/simdjson` empty shells (source only, no compiled `.so`, ~8MB dead weight). Removed auto pip-install logic from `run.py`.

**代码质量 / Code Quality**
- 8 处 `raise` 补 `from e` 保留异常链（rcon / conn / bot / microsoft_auth）
- `test_mark_failed` 补断言 `assertEqual(p.fail_count, before + 1)`
- `conftest.py` 测试结束自动清理 `observer_logs/`
- ruff 清理 21 处 unused import
- PWA：`sw.js` 缓存名加版本号，`index.html` 加 apple-touch-icon
- 8 `raise` statements now use `from e` to preserve exception chains. Added `test_mark_failed` assertion. `conftest.py` cleans `observer_logs/` after tests. Ruff cleaned 21 unused imports. PWA: `sw.js` cache versioned, apple-touch-icon added.

**调试 / Debugging**
- 离线账号发消息时打印 payload hex（`[聊天调试]`），便于排查 "larger than expected" 等协议格式问题
- Offline chat sends now log payload hex (`[聊天调试]`) for troubleshooting protocol format issues.

</details>

<details>
<summary><b>v3.6.3</b>（点击展开）</summary>

**聊天功能修复（核心）**
- 修复 1.21 (proto 767) 观察者收不到聊天消息：`extract_chat_text` 错误跳过 `globalIndex` 字段（该字段 1.21.2/768 才加入），导致解析字节错位、文本为空。消息实际一直在广播，只是观察者解析不出来
- 撤掉针对错误诊断的 workaround：离线账号 `/me` 兜底、自签名 Chat Session（对离线账号有害，服务器收到无法验证的密钥后会静默丢弃后续无签名消息）

**正版签名聊天（RSA-2048+SHA256）**
- Minecraft 1.19+ 聊天签名实际用 **RSA-2048 + SHA256 PKCS#1 v1.5**（非 Ed25519），Mojang `/player/certificates` 返回 RSA 密钥对
- `_build_signed_chat` 用 pycryptodome 做 RSA-SHA256 签名，签名数据 = sender UUID(16) + timestamp(8) + salt(8) + message(UTF-8)
- 766+ (1.20.5+) 签名字段是固定 256 字节 buffer，无 varint 长度前缀
- 离线服不获取证书、不发 Chat Session（离线 UUID 与正版证书 UUID 不匹配，发了会被 invalid_public_key_signature 踢）
- 修复 Chat Session / 签名聊天 base64 解码 `Incorrect padding`：Mojang 返回的密钥可能缺末尾 `=` padding，解码前自动补全

**认证状态机加固**
- `auth_mode` 在 `__init__` 初始化为 `unknown`，Play 成功时仅 unknown 才标 offline（正版账号走过 Encryption 后保留 online，不再被覆盖）
- bot 与 probe 白名单关键词对齐（whitelist / white list / not white-listed / not whitelisted / 白名单 / 不在白名单 / not on the whitelist）
- `join_and_warn` 异常路径改用 `BotError.code`（WHITELIST / ONLINE_MODE_REQUIRED / BANNED / KICKED / INCOMPATIBLE_VERSION），不再扫异常字符串
- neoforge 从 forge pattern 拆出单独分类
- plugin_channels 数据流接上：auth_probe 返回并落库，可辅助 Forge/模组识别
- 无报告协议时跨时代回退（775/767/763/761/754/340），不再只试最新 3 个版本
- `fingerprint_server` 改名为 `fingerprint_by_field_order`，避免和 `core/fingerprint.py` 同名冲突

**安全加固**
- `msa_refresh_token` 等敏感令牌掩码，前缀收窄到 2 位
- 修复两处存储型 XSS（logBox、观察者卡片）

**AI 与观察者**
- AI Bot 10 秒内收到一模一样的内容直接忽略，不再自己跟自己吵架
- 观察者聊天记录按日期分类、可搜索 IP、可手动删除 0 消息记录

**收藏与健康监控**
- 收藏人数显示 `online/max` 格式（如 2/20）并显示玩家名称
- 收藏页筛选增加认证方式（正版/盗版）和有人/没人
- 人数趋势图移到收藏页
- 健康监控发现认证缺失时自动补一次认证检测

**Web 面板**
- 右上角加关闭服务按钮
- 移动端界面优化

</details>

<details>
<summary><b>v3.6.2</b>（点击展开）</summary>

**修复与优化**
- 修复 1.19.3–1.20.4 协议层 bug（Login Start 字节分档、Client Settings 字段分档）
- 健康监控 fast 模式，不再遍历19个协议版本，速度提升10倍
- AI Bot 通过 UUID 真正识别自己发的消息，不再自己跟自己说话
- 正版登录后自动同步服务器实际用户名，支持 Ed25519 签名聊天
- 数据库页加导入/清空/收藏按钮，收藏列表白名单优先排序
- 收藏人数显示 online/max 格式并显示玩家名
- Web 面板加关闭服务按钮
- 移除登录认证（本地工具），README 诚实描述
</details>

<details>
<summary><b>v3.6.1</b>（点击展开）</summary>

**收藏与健康监控**
- 收藏保留上次在线信息（`last_good_info`），离线重查/监控不再覆盖
- 健康监控并发探测、按监控列表清理残留状态、事件改用在线状态判定（空服开机不再漏报）
- 健康监控支持 Web 面板配置轮询间隔、手动"立即检查"、逐台探测实时更新
- 收藏文件原子写 + 并发写加锁，监控写回无变化不重写盘

</details>

<details>
<summary><b>v3.6.0</b>（点击展开）</summary>

**扫描引擎**
- `safe` / `balanced` / `aggressive` 三档模式
- 批次冷却、自适应降速、连接异常检测、断点续扫
- masscan 两阶段集成、扫描任务队列

**协议地基**
- 协议表由 minecraft-data 自动生成（41 版本），发布前完整性校验
- 版本映射校准并以单测锁死
- 配置阶段包 ID 以自动表为准

**AI 功能**
- 分层记忆系统、人格编辑、自动重连
- AI 回复命令拦截、API 失败退避、记忆可清除

**正版登录**
- Microsoft OAuth 设备码流程、多账户管理
- 各进服入口支持正版验证开关（手动勾选）
- ⚠️ 不发送真实聊天签名，强制签名服可能拒收

**安全加固**
- 能力分级开关、全局只读、操作审计、API 限流

</details>

<details>
<summary><b>v3.4.0</b></summary>

- Web 面板模块化拆分（多路由模块 + 服务层）
- Web UI 视觉升级 + 移动端适配
- AI 助手浮窗、健康监控邮件、人数历史曲线

</details>

---

## ⚖️ 法律与伦理

> 本节是使用本工具的**硬性约束**，不是可选项。

### ✅ 合法使用范围

- **安全研究 / 授权测试**：在明确（最好书面）授权下评估目标系统
- **自有资产巡检**：扫描和管理你自己拥有或托管的服务器
- **内网教学**：在隔离的私有网络中学习网络与协议

### 🚫 禁止行为

- 对**未授权**服务器进行端口扫描、探测或漏洞扫描
- 登录未授权服务器（含离线服）或访问其数据
- 在未授权服务器执行 `/op`、`/gamemode`、`/ban`、`/stop` 等任何命令
- 用 RCON 连接未授权服务器
- 进行 DDoS、僵尸网络、垃圾消息等任何形式的拒绝服务 / 骚扰
- 收集、传播第三方服务器的玩家数据、IP 等个人信息
- 规避或突破防火墙、白名单、正版验证等安全保护措施

### 🔐 数据隐私

- 工具不会向任何第三方上传你的扫描数据或配置
- 扫描结果仅存于本地，由你自行管理
- 请勿把含真实 IP / 玩家信息的结果或凭据提交到公开仓库
- `.gitignore` 默认排除 `*.db`、`*.json` 等数据与凭据文件

<details>
<summary><b>📖 相关法律依据（中国大陆）</b></summary>

未经授权扫描、登录或控制计算机信息系统，可能涉及：

- 《中华人民共和国刑法》第 285 条 —— 非法侵入计算机信息系统罪、非法获取计算机信息系统数据罪、**提供侵入 / 非法控制计算机信息系统程序、工具罪**
- 《中华人民共和国刑法》第 286 条 —— 破坏计算机信息系统罪
- 《中华人民共和国刑法》第 287 条之二 —— 帮助信息网络犯罪活动罪
- 《中华人民共和国网络安全法》
- 《中华人民共和国数据安全法》
- 《中华人民共和国个人信息保护法》

在其他国家 / 地区，请遵守当地关于计算机滥用、未授权访问与数据保护的法律（如 CFAA、GDPR 等）。

</details>

<details>
<summary><b>📝 免责声明</b></summary>

- 本工具按「现状」提供，作者不对其适用性、可靠性或安全性作担保
- 使用者需自行承担使用本工具产生的一切法律责任与后果
- 作者不对因使用本工具导致的任何直接或间接损失负责
- 如不同意上述条款，请立即停止使用并删除本工具
- 以上为一般性信息，不构成法律意见；具体案件请咨询执业律师

</details>

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 发布。

<div align="center">

**请在授权范围内使用。Happy & Safe Scanning. 🟢**

</div>
