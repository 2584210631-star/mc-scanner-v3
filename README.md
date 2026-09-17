<div align="center">

# MC Scanner v3.4.0
### Minecraft 服务器扫描工具

Python 3.8+ · 协议 340+ · Web 面板 · 离线检测 · 观察者模式 · AI托管 · 多AI吵架

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
- 预设人格见 `core/ai_personas.py`
- 多 AI 群聊（2-8 个）

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

---

## 法律与伦理

- 仅供安全研究和授权测试
- 请控制扫描速率，禁止未授权滥用
- 使用者自行承担法律责任

## 许可证

MIT License
