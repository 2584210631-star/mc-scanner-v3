# MC Scanner v3-3.1 优化说明

## 优化日期
2026-09-03

## 一、Bug修复（共13个）

### 🔴 严重Bug（3个）

1. **cli.py scan命令崩溃**
   - 问题：`args.probe_workers` 属性不存在，运行 `python cli.py scan` 直接 AttributeError
   - 修复：改为 `args.workers`

2. **core/probe.py SLP VarInt解析索引错误**
   - 问题：`payload[offset + i]` 中 offset 和 i 同时递增，跳过了 VarInt 第二个字节
   - 修复：改为 `payload[offset]`，只用 offset 做索引

3. **core/conn.py 连接失败时socket泄漏**
   - 问题：`connect()` 抛出异常时 socket 不关闭，`with` 语句的 `__exit__` 不被调用
   - 修复：`connect()` 内加 try/except，失败时关闭 socket

### 🟡 中等Bug（7个）

4. **cli.py cmd_random SLP探测串行**
   - 问题：发现开放端口后 for 循环逐个 `slp_probe()`，极慢
   - 修复：改用 `ScanEngine.probe_list()` 并发探测

5. **scanner/engine.py scan_targets OOM**
   - 问题：字典推导式一次性提交所有 future，大网段内存爆炸
   - 修复：新增 `_run_batch()` 分批提交方法，每批最多 `workers*4` 个任务

6. **scanner/portscan.py scan_ports OOM**
   - 问题：`targets = list(targets)` 物化生成器 + 一次性提交
   - 修复：同样改成分批提交，BATCH_SIZE 动态计算

7. **scanner/targets.py count_targets 不支持@文件**
   - 问题：遇到 `@targets.txt` 直接跳过，返回0
   - 修复：递归读取文件内容统计

8. **core/conn.py _recv_varint 错误有符号转换**
   - 问题：对所有 VarInt 做 `result -= (1<<32)`，但 packet_id/length 是无符号的
   - 修复：删除有符号转换代码

9. **storage/db.py search 通配符未转义**
   - 问题：用户搜索 `%` 会匹配所有记录
   - 修复：新增 `_escape_like()` 函数，转义 `%` 和 `_`，SQL 加 `ESCAPE '\'`

10. **web/app.py bot_command 死代码 + masscan_status 冗余字段**
    - 问题：`if not connected` 永远不执行（connect失败抛异常）；`path` 字段用 `__import__` 写了一长串冗余代码
    - 修复：删除死代码和冗余字段

### 🟢 轻微Bug（3个）

11. **scanner/random_scan.py check_port socket泄漏**
    - 问题：`connect_ex()` 抛异常时 `sock.close()` 不执行
    - 修复：加 `finally` 块保证关闭（与 portscan.py 同款修复，v3-3.1 现已补齐）

12. **cli.py scan 和 warn 的 --workers 语义不一致**
    - 问题：scan 的 --workers 只改端口扫描线程，warn 的同时改两个
    - 修复：统一为都改探测线程（scan 已修复）

13. **web/app.py 无访问认证**
    - 问题：Web 面板暴露公网后任何人都能控制扫描器
    - 修复：新增 token 认证中间件（见下方架构优化）

---

## 二、架构优化（新增5个模块）

### 1. config.py — 统一配置模块
- 消除 cli.py / web/app.py 各处硬编码默认值
- 支持 `load_config()` / `get()` / `set()` / `reload_config()`
- 新增配置项：`web_token`（Web认证）、`warn_bot_max`（多机器人硬上限）

### 2. logger.py — 统一日志模块
- 替换全项目 print()（cli.py 的状态/警告输出与 Web 面板日志已接入统一 logger；CLI 结果列表与进度条保留 print 保证交互体验）
- 支持控制台输出 + MemoryLogHandler（Web端实时推送日志）
- 提供 `info()` / `warning()` / `error()` / `debug()` 便捷函数

### 3. service/ — 业务编排层
- `service/scan_service.py`：扫描业务（完整扫描/端口扫描/随机扫描/masscan/导入/数据库查询）
- `service/warn_service.py`：警告业务（扫描警告/数据库警告/单服务器警告/多机器人警告/发送命令）
- cli.py 的 portscan / scan / warn / warn-db / masscan / import / query 七个命令已改为调用 service，消除重复逻辑
- web/app.py 因实时进度/状态强耦合仍走自身流程，但日志已接入 logger
- 多机器人警告有硬上限 `warn_bot_max`（默认20），防止滥用

### 4. scanner/base.py — 扫描器抽象基类
- `BaseScanner` 抽象基类，统一 `scan()` 接口
- 三个实现：`TCPPortScanner` / `MasscanScanner` / `RandomScanner`
- `get_scanner(type)` 工厂方法，由 `service.run_scanner()` 统一调用，上层不需要写多套 if 判断

### 5. web/app.py Token认证
- `@app.before_request` 中间件，所有 `/api/*` 请求需要 `X-API-Token` header 或 `?token=` 参数
- 配置 `web_token` 为空时不启用认证（向后兼容）
- 首页和静态文件不需要认证

---

## 三、性能优化

| 优化项 | 优化前 | 优化后 |
|---|---|---|
| 大网段扫描内存 | 一次性提交所有future，OOM | 分批提交，每批workers*4个，内存稳定 |
| 随机扫描SLP探测 | 串行，100个端口等5分钟 | 并发32线程，几秒完成 |
| 端口扫描 | 一次性提交 | 分批提交 |
| 数据库搜索 | %和_不转义 | 转义通配符，精确搜索 |

---

## 四、文件变更清单

### 新增文件（7个）
- `config.py` — 统一配置
- `logger.py` — 统一日志
- `service/__init__.py` — 业务层（扫描业务）
- `service/scan_service.py` — 扫描服务
- `service/warn_service.py` — 警告服务
- `scanner/base.py` — 扫描器抽象基类
- `OPTIMIZATION.md` — 本文档

### 修改文件（9个）
- `cli.py` — 修复scan崩溃、cmd_random并发、使用统一config
- `core/probe.py` — 修复VarInt解析索引
- `core/conn.py` — 修复socket泄漏、删除有符号转换
- `scanner/engine.py` — 分批提交修复OOM
- `scanner/portscan.py` — 分批提交+socket泄漏修复
- `scanner/targets.py` — count_targets支持@文件
- `scanner/random_scan.py` — check_port socket泄漏修复
- `storage/db.py` — search通配符转义
- `web/app.py` — Token认证、删除死代码/冗余字段

### 未修改
- `core/bot.py`、`core/buffer.py`、`core/packets.py`、`core/protocol.py` — 协议层无bug，保持原样
- `libs/` — vendor依赖，保持原样
- `web/index.html` — 前端，保持原样
- `tests/` — 测试全部通过，保持原样

---

## 五、测试验证

```
✅ 语法检查：所有自有Python文件通过
✅ test_probe.py：5/5 通过
✅ test_bot.py：3/3 通过
✅ test_e2e.py：3/3 通过
✅ test_integration.py：14/14 通过
✅ cli.py --help：正常
✅ cli.py scan --help：正常（不再崩溃）
✅ config.py：加载正常，23个配置项
✅ logger.py：输出正常
✅ service/：导入正常
✅ scanner/base.py：工厂正常
```

---

## 六、使用新功能

### 启用Web Token认证
在 `config.json` 中添加：
```json
{
  "web_token": "your-secret-token-here"
}
```
然后所有API请求需要带 header：
```
X-API-Token: your-secret-token-here
```
或URL参数：`?token=your-secret-token-here`

### 使用统一配置
```python
import config
cfg = config.load_config()
workers = config.get("workers", 32)
```

### 使用统一日志
```python
import logger
logger.info("扫描开始")
logger.error("连接失败")
```

### 使用扫描器工厂
```python
from scanner.base import get_scanner
scanner = get_scanner("masscan", rate=10000)
for ip, port in scanner.scan(["0.0.0.0/0"], ports=[25565]):
    print(ip, port)
```
### 使用统一扫描入口（service 层）
```python
from service import run_scanner
open_ports = run_scanner("tcp", targets=["1.2.3.0/24"], ports=[25565])
```

### 使用业务服务层
```python
from service.scan_service import run_full_scan
results = run_full_scan("1.2.3.0/24", workers=50)

from service.warn_service import warn_single
result = warn_single("1.2.3.4", 25565, messages=["你好"])
```
