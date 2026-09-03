# MC Scanner v3.2-Fusion 升级说明

融合 a4v3l1/minecraft-server-scanner 的优点，在 v3Pro 基础上升级。

## 新增功能

### 1. 核心类型细分识别
- 从原来的 modded/plugin/vanilla 三分类，升级为 12 种核心类型识别
- 支持：vanilla / paper / spigot / bukkit / purpur / forge / fabric / neoforge / quilt / catserver / arclight / unknown
- 通过版本名字符串 + Forge SLP modinfo/forgeData 双重判断
- 结果页和数据库页均显示核心类型标签，支持按核心类型筛选

### 2. 模组列表与 Forge 频道提取
- 老版本 Forge 服务器自动提取 modinfo.mods 列表（modid + version）
- 1.13+ Forge 服务器提取 forgeData.channels 插件频道列表
- 存入数据库（JSON 字段），可通过 API 查询

### 3. 收藏管理系统（融合 a4v3l1 核心体验）
- **收藏/取消收藏**：结果页点击 ☆ 按钮一键收藏
- **标签管理**：每个收藏可设置多个标签，按标签筛选
- **备注**：可添加文字备注
- **全部重查**：一键重新探测所有收藏服务器，更新在线状态/版本/玩家数
- **单个重查**：单独刷新某个收藏
- **导入**：从 txt 文件批量导入（每行 ip:port）
- **导出**：JSON 格式导出
- **自动记录**：收藏时间、最后检查时间、最后探测信息

### 4. Web 面板新增"收藏"标签页
- 标签筛选 + 关键词搜索
- 显示版本/核心/玩家/认证/标签/备注/最后检查时间
- 行内操作：重查 / 标签 / 备注 / 删除

### 5. CLI 新增 fav 子命令
```bash
python3 cli.py fav list                    # 列出收藏
python3 cli.py fav list --tag survival     # 按标签筛选
python3 cli.py fav add 1.2.3.4:25565 --tags "生存,中文" --note "我的服"
python3 cli.py fav remove 1.2.3.4:25565
python3 cli.py fav rescan                  # 重查所有收藏
python3 cli.py fav rescan 1.2.3.4:25565    # 重查单个
python3 cli.py fav tags 1.2.3.4:25565 --tags "新标签"
python3 cli.py fav import servers.txt      # 从文件导入
python3 cli.py fav tags-list               # 列出所有标签
```

## 数据库升级
- 新增 3 个字段：core_type / mods / forge_channels
- **自动迁移**：旧版本数据库启动时自动 ALTER TABLE 添加字段，无需手动操作
- 旧数据的新字段为 NULL，重新扫描后自动填充

## 修改的文件
| 文件 | 改动 |
|------|------|
| core/probe.py | 新增 detect_core_type / extract_mods / extract_forge_channels，slp_probe 返回新字段 |
| scanner/engine.py | probe_one 传递 core_type/mods/forge_channels，改进模组/插件识别逻辑 |
| storage/db.py | 新增 3 字段 + 自动迁移 + core_type 查询 + by_core 统计 |
| storage/favorites.py | **新增** 收藏管理模块（增删改查/标签/重查/导入导出） |
| storage/__init__.py | 导出 favorites 模块 |
| web/app.py | 新增 8 个收藏 API + 结果筛选支持 core_type |
| web/index.html | 新增收藏标签页 + 核心类型列 + 收藏按钮 + 核心类型筛选 |
| cli.py | 新增 fav 子命令（7 种操作） |

## 保留的 v3Pro 原有功能
- 自研完整 MC 协议栈（零依赖 mcstatus）
- 六态认证检测（离线/正版/白名单/拒绝/未知/不可达）
- 自动安全警告机器人 + AuthMe 注册
- masscan 全网高速扫描
- 随机 IP 暴力扫描
- CIDR/主机名/文件目标
- SQLite 数据库 + JSON/CSV 导出
- Flask Web 控制面板
- 10 个 CLI 子命令
- Mock 服务器测试体系

## 快速开始
```bash
cd mc-v3
python3 run.py 8090
# 浏览器打开 http://127.0.0.1:8090
# 扫描后在结果页点击 ☆ 收藏服务器
# 切换到"收藏"标签页管理收藏
```
