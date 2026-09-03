# MC Scanner v3.3 更新日志

## 版本
v3.3 (2026-09-03)

## 新增功能（4大模块 + 3个CLI命令 + 5个Web API）

### 1. 代理支持模块 (`core/proxy.py`, 431行)
- 纯 Python 实现 SOCKS5 和 HTTP CONNECT 代理协议，无额外依赖
- 启动时从 ProxyScrape API 自动获取新鲜代理（HTTP + SOCKS5）
- 智能轮换：优先选失败次数少、最近没用过的代理
- 失败自动剔除：连续失败超过阈值自动移除
- 健康检查：批量测试代理可用性
- 支持格式：`host:port`、`host:port:user:pass`、`socks5://host:port`、`http://user:pass@host:port`

### 2. 插件抓取模块 (`core/plugins.py`, 189行)
- 进服后自动发送 `/plugins`、`/version` 等探测命令
- 解析插件列表（名称+版本）、服务端软件、版本号
- 自动识别常见插件：AuthMe、Factions、Economy、WorldGuard、CoreProtect、LuckPerms、Vault
- 反作弊检测：NCP、Vulcan、Matrix、Spartan、AAC、Sparky、Intave、Horizon、Karhu 等12种

### 3. RCON 客户端 (`core/rcon.py`, 185行)
- 纯 Python 实现 Minecraft RCON 协议
- 支持认证、单命令执行、批量命令执行
- 多包响应正确处理（用空命令标记响应结束）
- 便捷函数 `rcon_execute()` 一行调用

### 4. 命令执行器 (`core/command_runner.py`, 191行)
- Bot 登录服务器后自动执行预设命令列表
- 支持从文件加载命令脚本（每行一条，`#` 开头为注释）
- 条件命令：`IF <关键词> THEN <命令>`
- 命令间延迟控制、超时控制
- 执行结果统计和摘要输出

## CLI 新增命令
- `python cli.py proxy --fetch` - 从 ProxyScrape 获取代理
- `python cli.py proxy --check` - 健康检查所有代理
- `python cli.py proxy --add host:port` - 添加代理
- `python cli.py rcon host:port -p password -c "命令"` - RCON 执行命令
- `python cli.py rcon host:port -p password -f commands.txt` - RCON 批量执行
- `python cli.py commands host:port -u BotName -c "/plugins;/version"` - 登录后执行命令
- `python cli.py commands host:port -s script.txt` - 从脚本文件执行

## Web API 新增端点
- `GET /api/proxy` - 代理列表
- `POST /api/proxy/fetch` - 获取代理
- `POST /api/proxy/check` - 健康检查
- `POST /api/rcon/execute` - RCON 命令执行
- `POST /api/plugins/capture` - 插件抓取
- `POST /api/commands/run` - 命令执行

## 测试
- 新增 44 个测试用例（proxy 11 + plugins 12 + rcon 9 + command_runner 12）
- 全部 144 个测试通过

## 基础
- 基于 mc-scanner-v3 最新版（含异步扫描引擎 asyncio+uvloop+pysimdjson）
- 保留 v3.2.1 全部功能（指纹/玩家历史/重扫/重复检测/Discord/分布式）
