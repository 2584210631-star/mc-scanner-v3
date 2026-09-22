<div align="center">

# MC Scanner v3.6.0
### Minecraft 服务器扫描工具

Python 3.8+ · 协议 340+ · Web 面板 · 离线检测 · 观察者模式 · AI托管 · 多AI吵架 · AI分层记忆 · 防封禁扫描

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
- masscan 集成（可选）

### 机器人与警告
- 登录服务器发送自定义消息
- AuthMe 自动注册 + 登录
- 多版本聊天包适配（1.12.2 ~ 1.21.x）
- 多机器人并发警告（单台最多 20 个，可由 warn_bot_max 配置）

### AI 托管 / 多 AI
- AI 驱动聊天机器人（DeepSeek / OpenAI 兼容 API）
- 16 种预设人格，支持 Web 端热更新（新增/修改/删除即时生效）
- 多 AI 群聊（2-8 个），可选历史对立人物
- **三层记忆系统**（`core/ai_memory.py`）：
  - 短期：最近 50 条原文
  - 中期：每 30 条自动压缩话题摘要，保留 3 段
  - 长期：玩家档案（身份/名字/喜好/年龄），持久化到 `ai_memory.json`
  - 纯本地规则提取，不消耗 API token
- AI 自动重连（指数退避，最多 10 次），重连保留聊天记录和记忆
- 回复冷却可配置（设置页调整，填 0 关闭）

### 扫描引擎
- 同步 / 异步 / masscan 三种扫描模式
- 扫描任务队列（多任务排队，不互相覆盖）
- SLP 探测缓存（60 秒 TTL，避免重复探测）
- 随机 IP 暴力扫描

### 防封禁扫描（v3.6.0 新增）
- 扫描模式分级：`stealth`（防封禁）/ `balanced`（平衡默认）/ `aggressive`（仅内网）
- 端口随机化：打乱扫描顺序，去掉"顺序递增"特征
- 批次冷却：每批扫完暂停，降低突发连接风暴
- 自适应速率：超时率突变自动降速，连续高超时判定疑似封禁并记录事件
- 断点续扫：中断/暂停后从上次位置继续（`--resume`）
- CLI 新增 `--port '1-65535'` 端口范围参数（全端口扫描入口）

### 安全与运维
- 全局只读模式（一键锁死警告/AI进服/观察者等危险操作）
- API 按模块限流（scan/warn/ai，可配置次数/分钟）
- 0.0.0.0 绑定时输出安全警告（当前版本无内置认证，公网暴露需自行加反向代理鉴权）
- config.json 不入库（敏感配置用环境变量 `MC_*` 覆盖）
- 定期清理超旧离线记录（可配置保留天数）

### Web 面板
- `python run.py` 后打开 http://127.0.0.1:8080
- 默认绑定 127.0.0.1；敏感配置可用环境变量 `MC_*` 覆盖

---

## 快速开始

```bash
pip install -r requirements.txt
cp config.example.json config.json   # 首次可选
python run.py
```

敏感项可用环境变量：`MC_WEB_TOKEN` / `MC_AI_API_KEY` / `MC_AI_BASE_URL` / `MC_AI_MODEL` / `MC_DISCORD_WEBHOOK` / `MC_EMAIL_*` / `MC_AUTHME_PASSWORD`

### 防封禁全端口扫描（v3.6.0 推荐用法）

```bash
# 单 IP 全端口，隐蔽模式（低速率+随机化+批次冷却+自适应降速）
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode stealth

# 全端口 + 断点续扫（中断后再次运行同命令自动从断点继续）
python3 cli.py scan 1.2.3.4 --port 1-65535 --mode stealth --resume

# 只扫端口（不探测 MC），隐蔽模式
python3 cli.py portscan 1.2.3.0/24 --port 1-65535 --mode stealth

# masscan 全网（stealth 自动限速 100pps，防封）
python3 cli.py masscan --targets 0.0.0.0/0 --port 1-65535 --mode stealth

# 仅内网/信任网络用高速模式
python3 cli.py scan 192.168.1.0/24 --mode aggressive
```

---

## 更新日志

### v3.6.0
- 新增防封禁扫描引擎（`scanner/stealth.py`）：stealth/balanced/aggressive 模式分级
- 新增端口随机化：默认打乱扫描顺序，防 IDS 顺序扫描特征
- 新增批次冷却：`--batch-cooldown` 控制批间暂停，防连接突发
- 新增自适应速率：超时率突变自动降速，连续高超时判定疑似封禁并记录
- 新增断点续扫：`--resume` 中断后从上次位置继续（进度存 `scan_progress.json`）
- 新增 `--port '1-65535'` 端口范围参数（scan/portscan）
- masscan 集成安全限速：`--mode stealth` 自动 100pps 并提示
- 修复异步 CLI 逗号分隔多目标无法解析的问题
- 配置新增：`scan_mode` / `shuffle` / `batch_cooldown` / `progress_file`
- 新增 AI 三层记忆系统（短期原文 + 中期话题摘要 + 长期玩家档案）
- 新增扫描任务队列（多任务排队执行）
- 新增全局只读模式（危险 API 返回 403）
- 新增 AI 人格热更新（Web 端增删改即时生效）
- 新增 API 按模块限流
- 新增定期清理超旧离线记录
- 新增 SLP 探测缓存（60 秒 TTL）
- AI bot / 观察者自动重连（指数退避）
- 观察者聊天记录实时落盘 + 关键词告警
- 安全加固：0.0.0.0 无 token 拒绝启动，config.json 不入库
- 修复多个运行时 NameError 和竞态条件

### v3.4.0
- Web 面板模块化拆分（11 个路由模块 + 3 个服务层）
- Web UI 视觉升级 + 移动端适配
- AI 助手浮窗（Agent 模式，可控制扫描/警告/观察者）
- 服务器健康监控（有人上线/掉线邮件推送）
- 人数历史曲线
- 收藏 / 数据库导出
- 批量 AI 托管

---

## 法律与伦理

- 仅供安全研究和授权测试
- 请控制扫描速率，禁止未授权滥用
- 使用者自行承担法律责任

## 许可证

MIT License
