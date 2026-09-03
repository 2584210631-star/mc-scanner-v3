# MC Scanner v3.2.1 更新日志

## 概述
在原版 mc-scanner-v3 基础上的增量优化版，融合 matscan（mat-1）的核心特性。
**不重写原有代码**，所有新功能以模块化方式集成，保持原版开箱即用、零依赖（vendored libs）的特性。

## 新增特性

### 1. 扩展服务端指纹识别 (`core/fingerprint.py`)
- 在原版 `core_type` 基础上，增加更细粒度的服务端类型识别
- 支持：BungeeCord/Waterfall/Travertine、Velocity、CatServer、Mohist、Arclight、Magma、node-minecraft-protocol 等
- 多级检测：原版 core_type 优先 → Forge 数据字段 → 玩家样本标记 → 版本名关键词 → MOTD 关键词 → 纯净版本号
- 返回置信度和检测来源，便于调试

### 2. 玩家历史追踪 (`storage/player_history.py`)
- 记录每个服务器上出现过的玩家，支持玩家-服务器双向查询
- 自动去重（同一玩家在同一服务器只记录一次）
- API：
  - `update_players(db, ip, port, player_list)` — 更新玩家历史
  - `get_player_history(db, player_name, ip, port)` — 查询历史
  - `get_player_servers(db, player_name)` — 查某玩家去过哪些服
  - `get_server_players(db, ip, port)` — 查某服出现过哪些玩家
  - `get_stats(db)` — 统计（唯一玩家数、唯一服务器数、总记录数）

### 3. 智能重扫队列 (`storage/rescan.py` + `scanner/rescanner.py`)
- 根据服务器状态动态调整重扫频率，融合 matscan 的重扫策略
- 策略表：
  | 策略 | 间隔 | 适用场景 |
  |------|------|----------|
  | new | 1分钟 | 新发现服务器，前5次快速确认 |
  | has_players | 5分钟 | 有人在线的服务器，追踪玩家变化 |
  | cracked | 30分钟 | 离线/破解服 |
  | online | 2小时 | 正版验证服 |
  | whitelist | 2小时 | 白名单服 |
  | default | 1小时 | 其他 |
- CLI：`python cli.py rescan --list/--run/--clear/--remove ip:port`
- Web API：`/api/rescan`、`/api/rescan/run`、`/api/rescan/clear`

### 4. 重复服务器检测 (`scanner/duplicate.py`)
- 识别同一台服务器在多个 IP/端口上运行的情况（常见于中转/镜像服）
- 双重指纹：
  - 精确指纹：MOTD + 版本 + 最大玩家数 + 协议号 + favicon
  - 软指纹：MOTD（去动态内容）+ 最大玩家数（宽松匹配）
- 自动合并重复组，支持统计

### 5. Discord Webhook 通知 (`notify/discord.py`)
- 纯 urllib 实现，与原版 vendored 风格一致，无需额外依赖
- 通知事件：
  - 新服务器发现
  - 破解服发现（可用于安全告警）
  - 玩家加入/离开
- 内置冷却机制（5分钟），防止重复通知刷屏
- 配置：`config.json` 中设置 `"discord_webhook": "https://discord.com/api/webhooks/..."`

### 6. 分布式任务分片 (`distributed/shard.py`)
- 将大网段扫描任务分割为多个分片，分配给多台机器并行执行
- 基于文件的简单状态管理（不依赖 Redis/Zookeeper），与原版轻量风格一致
- 支持 CIDR 网段分片和目标文件分片（一致性哈希）
- CLI：
  - `python cli.py distributed --create 10.0.0.0/8 --shards 8` — 创建任务
  - `python cli.py distributed --worker worker1 --job default` — 领取并执行分片
  - `python cli.py distributed --status default` — 查看任务进度

## 集成修改（原有文件）

| 文件 | 修改内容 |
|------|----------|
| `scanner/engine.py` | `__init__` 增加 `rescan_enabled`/`duplicate_detection`/`discord_webhook` 参数；`probe_one` 成功后调用 `_post_probe_hooks()`；新增 `rescan_due()`/`get_duplicates()` 方法 |
| `storage/db.py` | `init_db()` 中自动初始化 `player_history` 和 `rescan_queue` 表 |
| `config.py` | `DEFAULT_CONFIG` 增加 `discord_webhook`/`rescan_enabled`/`duplicate_detection` 配置项 |
| `service/__init__.py` | `_build_engine()` 传递新配置参数到 ScanEngine |
| `cli.py` | 新增 `rescan` 和 `distributed` 子命令；版本号更新为 v3.2.1 |
| `web/app.py` | 新增 `/api/players`、`/api/players/stats`、`/api/rescan`、`/api/rescan/run`、`/api/rescan/clear` API 端点 |

## 配置说明

在 `config.json` 中新增以下配置项（均为可选，默认关闭）：

```json
{
  "discord_webhook": "",
  "rescan_enabled": false,
  "duplicate_detection": false
}
```

- `discord_webhook`：填入 Discord Webhook URL 即启用通知
- `rescan_enabled`：设为 true 启用智能重扫和玩家历史追踪
- `duplicate_detection`：设为 true 启用重复服务器检测

## 测试

- 新增 6 个测试文件，共 71 个测试用例
- 全部 100 个测试（含原有 29 个）通过
- 测试覆盖：指纹识别、玩家历史、重扫队列、重复检测、Discord 通知、分布式分片

## 兼容性

- 完全向后兼容：所有新功能默认关闭，不影响原有行为
- 数据库自动迁移：`init_db()` 自动创建新表，旧数据库无需手动升级
- 零新增依赖：所有新模块使用标准库（sqlite3/urllib/hashlib/ipaddress），与原版 vendored libs 风格一致
