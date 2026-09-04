#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MC Scanner v3.3 - 综合 Minecraft 服务器扫描器
整合 V1 功能完整性与 V2 架构优势的超越版。

子命令:
  portscan  只扫描端口
  scan      扫描 + SLP 探测 + 认证检测
  warn      扫描 + 离线检测 + 自动发警告
  warn-db   从数据库已扫描结果直接发警告（不重新扫描）
  masscan   masscan 全网端口发现
  import    导入 masscan 结果
  query     查询 SQLite 数据库
  bot       单独对一台服务器登录发消息
  web       启动 Web 控制面板

用法:
  python cli.py scan 1.2.3.0/24
  python cli.py warn 1.2.3.0/24 -u SecurityBot -m "警告消息"
  python cli.py web --port 8080
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import logger

from scanner.targets import parse_port_spec
from scanner.portscan import get_open_ports
from scanner.masscan import has_masscan
from scanner.engine import ScanEngine
from scanner.random_scan import random_scan, async_random_scan, parse_port_ranges
from core.bot import MCBot


def load_config(path: str = None) -> dict:
    """加载配置（委托给统一config模块，保持向后兼容）"""
    cfg = config.load_config(path)
    if isinstance(cfg.get('ports'), str):
        cfg['ports'] = parse_port_spec(cfg['ports'])
    return cfg


def save_results(results, output_file: str, fmt: str = "json"):
    if not output_file:
        return
    rows = []
    for r in results:
        if isinstance(r, dict):
            rows.append(r)
        elif hasattr(r, '__dataclass_fields__'):
            rows.append({k: getattr(r, k) for k in r.__dataclass_fields__})
        else:
            rows.append({'data': str(r)})
    if fmt == 'csv' or output_file.endswith('.csv'):
        import csv
        if rows:
            keys = list(rows[0].keys())
            with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(rows)
        logger.info(f"[*] 结果已保存: {output_file} (CSV)")
    else:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"[*] 结果已保存: {output_file} (JSON)")


def cmd_portscan(args, cfg):
    from service import run_portscan_only
    if args.workers:
        config.set('scan_threads', args.workers)
    if args.timeout:
        config.set('scan_timeout', args.timeout)
    if not getattr(args, 'sync_mode', False):
        from scanner.async_portscan import scan_ports_async, get_open_ports_async, has_uvloop
        from scanner.targets import parse_targets
        print(f"[*] 异步端口扫描（uvloop: {'启用' if has_uvloop() else '未安装'}）")
        targets = list(parse_targets([args.targets], default_ports=cfg.get('ports', [25565])))
        results = scan_ports_async(
            targets,
            concurrency=args.workers or 2000,
            timeout=args.timeout or cfg['scan_timeout'],
            rate_limit=args.rate or cfg['rate'],
        )
        open_ports = get_open_ports_async(results)
        print(f"\n[*] 开放端口 ({len(open_ports)} 个):")
        for ip, port in open_ports:
            print(f"  {ip}:{port}")
        if args.output:
            save_results([{'ip': r.ip, 'port': r.port, 'open': r.is_open,
                           'latency_ms': round(r.latency_ms, 1)} for r in results],
                         args.output, cfg['output_format'])
        return
    results = run_portscan_only(
        args.targets,
        scan_threads=args.workers or cfg['scan_threads'],
        scan_timeout=args.timeout or cfg['scan_timeout'],
        rate=args.rate or cfg['rate'],
        exclude_file=args.exclude or cfg['exclude_file'],
    )
    open_ports = get_open_ports(results)
    print(f"\n[*] 开放端口 ({len(open_ports)} 个):")
    for ip, port in open_ports:
        print(f"  {ip}:{port}")
    if args.output:
        save_results([{'ip': r.ip, 'port': r.port, 'open': r.is_open,
                       'latency_ms': round(r.latency_ms, 1)} for r in results],
                     args.output, cfg['output_format'])
def cmd_scan(args, cfg):
    from service import run_full_scan
    if args.workers:
        config.set('scan_threads', args.workers)
    if args.timeout:
        config.set('scan_timeout', args.timeout)
    if not getattr(args, 'sync_mode', False):
        from scanner.async_engine import AsyncScanEngine
        from scanner.async_portscan import has_uvloop
        from scanner.async_probe import has_simdjson
        from scanner.targets import parse_targets
        print(f"[*] 异步流水线扫描（uvloop: {'启用' if has_uvloop() else '未安装'}, "
              f"simdjson: {'启用' if has_simdjson() else '未安装'}）")
        targets = parse_targets([args.targets], default_ports=cfg.get('ports', [25565]))
        engine = AsyncScanEngine(
            db_path=args.db or cfg['db_path'],
            concurrency=args.workers or 2000,
            slp_concurrency=400,
            timeout=args.timeout or cfg['timeout'],
            auth_check=not args.no_auth,
            rate_limit=args.rate or cfg['rate'],
        )
        results = engine.scan_with_portscan(targets)
        up_results = [r for r in results if r.get('state') == 'up']
        print(f"\n[*] 发现 {len(up_results)} 个 Minecraft 服务器:")
        for s in sorted(up_results, key=lambda x: x.get('proto', 0)):
            print(f"  {s['ip']}:{s['port']} | {s.get('version','?')}(协议{s.get('proto','?')}) "
                  f"| {s.get('players_online',0)}/{s.get('players_max',0)}人 | {s.get('auth','?')} | {s.get('core_type','?')}")
        if args.output:
            save_results(results, args.output, cfg['output_format'])
        if args.web:
            from web.app import run
            run(args.db or cfg['db_path'], port=args.web)
        return results
    results = run_full_scan(
        args.targets,
        workers=args.workers or cfg['workers'],
        timeout=args.timeout or cfg['timeout'],
        auth_check=not args.no_auth,
        rate=args.rate or cfg['rate'],
        exclude_file=args.exclude or cfg['exclude_file'],
        db_path=args.db or cfg['db_path'],
    )
    print(f"\n[*] 发现 {len(results)} 个 Minecraft 服务器:")
    for s in sorted(results, key=lambda x: x.get('proto', 0)):
        print(f"  {s['ip']}:{s['port']} | {s.get('version','?')}(协议{s.get('proto','?')}) "
              f"| {s.get('players_online',0)}/{s.get('players_max',0)}人 | {s.get('auth','?')}")
    if args.output:
        save_results(results, args.output, cfg['output_format'])
    if args.web:
        from web.app import run
        run(args.db or cfg['db_path'], port=args.web)
    return results
def cmd_warn(args, cfg):
    from service.warn_service import warn_targets
    if args.workers:
        config.set('scan_threads', args.workers)
    if args.bot_workers:
        config.set('bot_threads', args.bot_workers)
    messages = None
    if args.message:
        messages = args.message if isinstance(args.message, list) else [args.message]
    elif args.message_file:
        with open(args.message_file, 'r', encoding='utf-8') as f:
            messages = [l.strip() for l in f if l.strip()]
    results = warn_targets(
        args.targets,
        username=args.username or cfg['username'],
        messages=messages,
        message_file=args.message_file,
        workers=args.workers or cfg['workers'],
        bot_workers=args.bot_workers or cfg['bot_threads'],
        timeout=args.timeout or cfg['timeout'],
        message_delay=cfg['message_delay'],
        authme_password=args.authme or cfg['authme_password'] or None,
        rate=args.rate or cfg['rate'],
        exclude_file=args.exclude or cfg['exclude_file'],
        db_path=args.db or cfg['db_path'],
    )
    success = sum(1 for r in results if r.success)
    offline = sum(1 for r in results if r.is_offline)
    msg_sent = sum(r.messages_sent for r in results)
    print(f"\n{'='*50}")
    print(f"  警告完成")
    print(f"  总目标: {len(results)}")
    print(f"  离线模式服务器: {offline}")
    print(f"  成功登录: {success}")
    print(f"  发送消息总数: {msg_sent}")
    print(f"{'='*50}")
    if args.output:
        save_results(results, args.output, cfg['output_format'])
def cmd_warn_db(args, cfg):
    """从数据库读取已扫描结果，直接发警告，不重新扫描"""
    from service.warn_service import warn_from_db
    db_path = args.db or cfg.get('db_path', 'mcscanner.db')
    auth = args.auth or "cracked"
    messages = None
    if args.message:
        messages = args.message if isinstance(args.message, list) else [args.message]
    elif args.message_file:
        with open(args.message_file, 'r', encoding='utf-8') as f:
            messages = [l.strip() for l in f if l.strip()]
    try:
        results = warn_from_db(
            auth=auth, modded=args.modded, search=args.search,
            limit=args.limit,
            username=args.username or cfg.get('username', 'SecurityBot'),
            messages=messages, message_file=args.message_file,
            workers=args.workers or cfg.get('bot_threads', 5),
            message_delay=cfg.get('message_delay', 0.8),
            authme_password=args.authme or cfg.get('authme_password') or None,
            db_path=db_path,
        )
    except FileNotFoundError as e:
        logger.error(f"[!] {e}")
        logger.error("[!] 请先运行 scan 命令扫描并保存结果到数据库")
        return
    success = sum(1 for r in results if r.success)
    msg_sent = sum(r.messages_sent for r in results)
    print(f"\n{'='*50}")
    print(f"  警告完成（从数据库，未重新扫描）")
    print(f"  总目标: {len(results)}")
    print(f"  成功登录: {success}")
    print(f"  发送消息总数: {msg_sent}")
    print(f"{'='*50}")
def cmd_masscan(args, cfg):
    from service import run_masscan_scan
    if not has_masscan():
        logger.warning("[!] masscan 未安装，请先安装: sudo apt install masscan")
        return
    result_path = run_masscan_scan(
        targets=args.targets or "0.0.0.0/0",
        port=args.port or "25565",
        rate=args.rate or 1000,
        exclude_file=args.exclude or cfg['exclude_file'],
        output_file=args.output or "scan_results.ndjson",
        auto_import=args.auto_import,
        workers=args.workers or 32,
        auth_check=not args.no_auth,
        db_path=args.db or cfg['db_path'],
    )
    logger.info(f"[*] masscan 结果: {result_path}")
def cmd_import(args, cfg):
    from service import import_masscan_results
    try:
        results = import_masscan_results(
            args.ndjson,
            workers=args.workers or 32,
            auth_check=not args.no_auth,
            db_path=args.db or cfg['db_path'],
        )
    except FileNotFoundError as e:
        logger.error(f"[!] {e}")
        return
    logger.info(f"[*] 导入完成，共 {len(results)} 条记录")
def cmd_query(args, cfg):
    from service import query_database, get_db_stats
    db_path = args.db or cfg['db_path']
    if not os.path.exists(db_path):
        logger.error(f"[!] 数据库不存在: {db_path}")
        return
    if args.stats:
        s = get_db_stats(db_path)
        print(f"\n数据库统计:")
        print(f"  总记录: {s['total']}")
        print(f"  有人在线: {s['online_servers']}")
        print(f"  认证模式分布:")
        for auth, count in s['by_auth'].items():
            print(f"    {auth}: {count}")
        return
    rows = query_database(db_path, auth=args.auth, modded=args.modded,
                          search=args.search, limit=args.limit)
    print(f"{len(rows)} 条结果:")
    for r in rows:
        print(f"  {r['ip']}:{r['port']} [{r['auth']}] {r['version']} "
              f"在线 {r['players_online']}/{r['players_max']} · {r['motd'][:40]}")
def cmd_bot(args, cfg):
    host, port = args.target.rsplit(":", 1)
    bot = MCBot(host, int(port), protocol_version=args.proto,
                username=args.username or cfg['username'], timeout=args.timeout or 15.0)
    try:
        bot.connect()
        print(f"[+] 登录成功 (proto {bot.protocol_version})")
        if args.authme:
            print(f"[+] AuthMe: {'/register' if args.register else '/login'}")
            bot.authme_login(args.authme, register=args.register)
        if args.message:
            messages = args.message if isinstance(args.message, list) else [args.message]
            for msg in messages:
                bot.send_chat(msg)
                print(f"[+] 已发送: {msg}")
        bot.keep_alive(args.hold or 4.0)
        print("[+] 保持连接结束")
    except Exception as e:
        logger.error(f"[!] 失败: {e}")
    finally:
        bot.close()


def cmd_web(args, cfg):
    from web.app import run
    run(args.db or cfg['db_path'], port=args.port, host=args.host)


def cmd_random(args, cfg=None):
    """随机IP随机端口暴力扫描"""
    port_ranges = parse_port_ranges(args.ports)
    exclude_file = None if args.no_exclude else (args.exclude or "exclude.conf")
    logger.info("[*] 随机暴力扫描模式")
    mode = "异步高速" if not getattr(args, 'sync_mode', False) else "线程池"
    logger.info(f"[*] 目标数: {args.count} | 模式: {mode} | 超时: {args.timeout}s")
    logger.info(f"[*] 端口范围: {args.ports}")
    if exclude_file:
        logger.info(f"[*] 排除列表: {exclude_file}（含中国IP段，专扫国外）")
    else:
        logger.info("[*] 不使用排除列表")
    print()

    def progress(done, total, found):
        pct = done / total * 100
        print(f"\r[*] 进度: {done}/{total} ({pct:.1f}%) | 发现: {found} 个开放端口", end="", flush=True)

    import time
    start = time.time()
    if not getattr(args, 'sync_mode', False):
        import asyncio
        from scanner.async_portscan import has_uvloop
        if has_uvloop():
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        open_ports = asyncio.run(async_random_scan(
            target_count=args.count,
            concurrency=max(args.workers, 500),
            timeout=args.timeout,
            port_ranges=port_ranges,
            progress_callback=progress,
            exclude_file=exclude_file,
        ))
    else:
        open_ports = random_scan(
            target_count=args.count,
            max_workers=args.workers,
            timeout=args.timeout,
            port_ranges=port_ranges,
            progress_callback=progress,
            exclude_file=exclude_file,
        )
    elapsed = time.time() - start
    print()
    logger.info(f"[*] 扫描完成! 耗时: {elapsed:.1f}s ({args.count/elapsed:.0f} 目标/秒)")
    logger.info(f"[*] 发现 {len(open_ports)} 个开放端口")
    print()

    if not open_ports:
        logger.warning("[!] 没有发现开放端口，试试增加目标数量或扩大端口范围")
        return

    # SLP 探测（并发，不再串行）
    if args.probe:
        logger.info("[*] SLP 探测...")
        engine = ScanEngine(db_path=cfg["db_path"], workers=min(32, args.workers or 200), timeout=3.0)
        results = engine.probe_list(open_ports)
        servers = []
        for i, info in enumerate(results):
            if info.get("state") == "up":
                servers.append({
                    "ip": info["ip"], "port": info["port"],
                    "version": info.get("version"),
                    "players": f"{info.get('players_online', 0)}/{info.get('players_max', 0)}",
                    "motd": str(info.get("motd", ""))[:60],
                })
                print(f"  [{i+1}/{len(results)}] {info['ip']}:{info['port']} | {info.get('version','?')} | {info.get('players_online',0)}/{info.get('players_max',0)}")
        logger.info(f"[*] 发现 {len(servers)} 个 Minecraft 服务器")
        if args.output:
            import json
            with open(args.output, 'w') as f:
                json.dump(servers, f, indent=2, ensure_ascii=False)
            logger.info(f"[*] 结果已保存到 {args.output}")
    else:
        for ip, port in open_ports:
            print(f"  {ip}:{port}")
        if args.output:
            import json
            with open(args.output, 'w') as f:
                json.dump([{"ip": ip, "port": port} for ip, port in open_ports], f, indent=2)
            logger.info(f"[*] 结果已保存到 {args.output}")


def cmd_fav(args, cfg):
    """收藏管理：list/add/remove/rescan/tags/import"""
    from storage import favorites
    action = args.action
    if action == "list":
        tag = getattr(args, 'tag', None)
        search = getattr(args, 'search', None)
        favs = favorites.filter_favorites(tag=tag, search=search)
        if not favs:
            print("暂无收藏")
            return
        print(f"\n收藏列表 ({len(favs)} 个):")
        print(f"{'地址':<22} {'版本':<20} {'核心':<10} {'玩家':<10} {'标签':<20} {'最后检查'}")
        print("-" * 90)
        for f in favs:
            info = f.get("last_info") or {}
            state = info.get("state", "unknown")
            players = f"{info.get('online', 0)}/{info.get('max', 0)}" if state == "up" else state
            tags = ",".join(f.get("tags", []))[:18]
            last = f.get("last_check", "-")[:19] if f.get("last_check") else "-"
            print(f"{f['ip']}:{f['port']:<17} {info.get('version','-'):<20} {info.get('core_type','-'):<10} {players:<10} {tags:<20} {last}")
    elif action == "add":
        ip, port = args.target.rsplit(":", 1) if ":" in args.target else (args.target, 25565)
        tags = args.tags.split(",") if args.tags else []
        fav = favorites.add_favorite(ip, int(port), tags=tags, note=args.note or "")
        print(f"[+] 已收藏: {fav['ip']}:{fav['port']}")
    elif action == "remove":
        ip, port = args.target.rsplit(":", 1) if ":" in args.target else (args.target, 25565)
        ok = favorites.remove_favorite(ip, int(port))
        print(f"[{'+' if ok else '!'}] {'已移除' if ok else '未找到'}: {ip}:{port}")
    elif action == "rescan":
        if args.target:
            ip, port = args.target.rsplit(":", 1) if ":" in args.target else (args.target, 25565)
            info = favorites.rescan_one(ip, int(port), timeout=args.timeout)
            if info and info.get("state") == "up":
                print(f"[+] {ip}:{port} | {info.get('version','?')} | {info.get('online',0)}/{info.get('max',0)}人 | {info.get('core_type','?')}")
            else:
                print(f"[-] {ip}:{port} 离线或不可达")
        else:
            print(f"[*] 重新探测所有收藏...")
            def _progress(done, total):
                print(f"\r[*] 进度: {done}/{total}", end="", flush=True)
            favs = favorites.rescan_all(timeout=args.timeout, workers=args.workers, progress_callback=_progress)
            print(f"\n[+] 完成，共 {len(favs)} 个收藏")
            up = sum(1 for f in favs if (f.get("last_info") or {}).get("state") == "up")
            print(f"    在线: {up}, 离线: {len(favs) - up}")
    elif action == "tags":
        ip, port = args.target.rsplit(":", 1) if ":" in args.target else (args.target, 25565)
        tags = args.tags.split(",") if args.tags else []
        fav = favorites.update_tags(ip, int(port), tags)
        if fav:
            print(f"[+] 标签已更新: {fav['tags']}")
        else:
            print(f"[!] 未找到收藏: {ip}:{port}")
    elif action == "import":
        count = favorites.import_from_file(args.file)
        print(f"[+] 从 {args.file} 导入 {count} 个收藏")
    elif action == "tags-list":
        tags = favorites.get_all_tags()
        print(f"所有标签 ({len(tags)}): {', '.join(tags) if tags else '无'}")


def cmd_rescan(args, cfg):
    """智能重扫管理（v3.3 新增）"""
    from storage import rescan as rescan_db
    from scanner.rescanner import RescanScheduler
    db_path = args.db or cfg["db_path"]
    scheduler = RescanScheduler(db_path, enabled=True)

    if args.list:
        stats = scheduler.stats()
        print(f"\n重扫队列统计:")
        print(f"  总数: {stats['total']}")
        print(f"  到期待扫: {stats['due_now']}")
        print(f"  按策略分布:")
        for strategy, count in stats["by_strategy"].items():
            print(f"    {strategy}: {count}")
        all_items = scheduler.get_all(limit=args.limit)
        if all_items:
            print(f"\n前 {len(all_items)} 个重扫计划:")
            for item in all_items:
                next_scan = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item["next_scan"]))
                print(f"  {item['ip']}:{item['port']} | strategy={item['strategy']} | "
                      f"scan_count={item['scan_count']} | next={next_scan}")
        return

    if args.run:
        due = scheduler.get_due(limit=args.limit)
        if not due:
            print("[*] 没有到期的重扫任务")
            return
        print(f"[*] 执行 {len(due)} 个到期重扫...")
        engine = ScanEngine(db_path=db_path, workers=min(16, cfg["workers"]),
                            timeout=cfg["timeout"], rescan_enabled=True)
        results = []
        for i, item in enumerate(due):
            print(f"\r  [{i+1}/{len(due)}] {item['ip']}:{item['port']}...", end="", flush=True)
            try:
                r = engine.probe_one(item["ip"], item["port"])
                results.append(r)
            except Exception:
                continue
        up = sum(1 for r in results if r.get("state") == "up")
        print(f"\n[+] 重扫完成: {len(results)} 个目标, {up} 个在线")
        return

    if args.clear:
        scheduler.clear()
        print("[*] 重扫队列已清空")
        return

    if args.remove:
        ip, port = args.remove.rsplit(":", 1)
        scheduler.remove(ip, int(port))
        print(f"[*] 已移除: {ip}:{port}")
        return

    print("用法: python cli.py rescan --list / --run / --clear / --remove ip:port")


def cmd_distributed(args, cfg):
    """分布式任务分片（v3.3 新增）"""
    from distributed.shard import ShardManager, shard_cidr

    if args.create:
        shards = shard_cidr(args.create, num_shards=args.shards, ports=cfg["ports"])
        print(f"[*] 已生成 {len(shards)} 个分片:")
        for s in shards:
            print(f"  分片 {s['shard_id']}: {s['targets']} (~{s['estimated_hosts']} 主机)")
        # 保存分片信息
        manager = ShardManager()
        manager.create_job(args.job or "default", args.create, args.shards, cfg["ports"])
        print(f"[*] 任务已保存，使用 'python cli.py distributed --worker <id> --job {args.job or 'default'}' 领取分片")
        return

    if args.worker:
        manager = ShardManager()
        job_id = args.job or "default"
        shard = manager.claim_shard(job_id, args.worker)
        if not shard:
            print("[-] 没有可用分片")
            return
        print(f"[*] Worker {args.worker} 领取分片 {shard['shard_id']}: {shard['targets']}")
        # 执行扫描
        engine = ScanEngine(db_path=args.db or cfg["db_path"], workers=cfg["workers"],
                            timeout=cfg["timeout"], rescan_enabled=cfg.get("rescan_enabled", False))
        from service import run_full_scan
        results = run_full_scan(shard["targets"], workers=cfg["workers"],
                                 timeout=cfg["timeout"], db_path=args.db or cfg["db_path"])
        manager.complete_shard(job_id, shard["shard_id"], {"found": len(results)})
        print(f"[+] 分片 {shard['shard_id']} 完成: 发现 {len(results)} 台服务器")
        return

    if args.status:
        manager = ShardManager()
        status = manager.get_job_status(args.status)
        if not status:
            print(f"[-] 任务不存在: {args.status}")
            return
        print(f"\n任务 {args.status} 状态:")
        print(f"  总分片: {status['total_shards']}")
        print(f"  已完成: {status['completed_shards']}")
        print(f"  进度: {status['progress']}%")
        for sid, info in status["shards"].items():
            print(f"  分片 {sid}: {info['status']} (worker={info.get('worker') or '-'})")
        return

    print("用法: python cli.py distributed --create CIDR --shards N / --worker ID / --status JOB")


def cmd_proxy(args, cfg):
    """代理管理（v3.3 新增）"""
    from core.proxy import ProxyManager, get_proxy_manager
    manager = get_proxy_manager(proxy_file=args.file or "proxies.txt", auto_fetch=False)
    if args.fetch:
        count = manager.fetch_from_api(fetch_socks5=args.socks5)
        print(f"[+] 从 ProxyScrape 获取 {count} 个代理")
        return
    if args.check:
        alive = manager.health_check(test_host=args.test_host or "mc.hypixel.net",
                                      test_port=args.test_port or 25565,
                                      timeout=args.timeout or 5.0)
        print(f"[+] 健康检查完成: {alive}/{len(manager)} 个可用")
        return
    if args.add:
        manager.add_proxy(args.add)
        print(f"[+] 已添加代理: {args.add}")
        return
    # 默认列出代理
    proxies = manager.load_from_file()
    print(f"\n代理列表 ({len(manager)} 个):")
    for p in manager.proxies if hasattr(manager, 'proxies') else []:
        print(f"  {p.proto}://{p.host}:{p.port} (失败={p.fail_count})")
    if not manager.proxies:
        print("  (空，使用 --fetch 获取)")


def cmd_rcon(args, cfg):
    """RCON 客户端（v3.3 新增）"""
    from core.rcon import RCONClient, rcon_execute
    if not args.host:
        print("用法: python cli.py rcon <host:port> -p <password> -c <command>")
        return
    if ":" in args.host:
        host, port = args.host.rsplit(":", 1)
        port = int(port)
    else:
        host, port = args.host, 25575
    password = args.password or ""
    if args.command:
        result = rcon_execute(host, port, password, args.command, timeout=args.timeout or 10.0)
        print(f"[RCON] {host}:{port}")
        print(f"命令: {args.command}")
        print(f"响应:\n{result}")
        return
    if args.commands_file:
        try:
            with open(args.commands_file, 'r', encoding='utf-8') as f:
                commands = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except FileNotFoundError:
            print(f"[!] 文件不存在: {args.commands_file}")
            return
        client = RCONClient(host, port, password, timeout=args.timeout or 10.0)
        if not client.connect():
            print("[!] RCON 连接失败或认证失败")
            return
        results = client.execute_many(commands, delay=args.delay or 0.3)
        client.close()
        print(f"[RCON] 执行 {len(results)} 条命令:")
        for cmd, resp in results.items():
            print(f"  > {cmd}")
            print(f"    {resp[:200]}")
        return
    print("用法: python cli.py rcon <host:port> -p <password> -c <命令>")
    print("  或: python cli.py rcon <host:port> -p <password> -f <命令文件>")


def cmd_commands(args, cfg):
    """登录后自动执行命令（v3.3 新增）"""
    from core.command_runner import run_commands_on_server, CommandScript
    if not args.target:
        print("用法: python cli.py commands <host:port> -u <用户名> [选项]")
        return
    if ":" in args.target:
        host, port = args.target.rsplit(":", 1)
        port = int(port)
    else:
        host, port = args.target, 25565
    username = args.username or "CommandBot"
    if args.script:
        script = CommandScript.from_file(args.script, delay=args.delay or 1.0)
    elif args.commands:
        script = CommandScript(delay=args.delay or 1.0)
        for cmd in args.commands.split(';'):
            script.add(cmd.strip())
    else:
        # 默认 info 脚本
        script = CommandScript(delay=args.delay or 1.0)
        script.add("/plugins")
        script.add("/version")
        script.add("/help")
    print(f"[*] 登录 {host}:{port} 作为 {username}，执行 {len(script.commands)} 条命令...")
    try:
        results = run_commands_on_server(host, port, username, script.commands,
                                          timeout=args.timeout or 15.0,
                                          authme_password=args.authme)
        print(f"\n[+] 执行完成:")
        for r in results:
            status = "✅" if r.success else "❌"
            print(f"  {status} {r.command}")
            if r.response:
                print(f"     {r.response[:150]}")
    except Exception as e:
        print(f"[!] 执行失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="MC Scanner v3.3 - 综合 Minecraft 服务器扫描器")
    parser.add_argument("-c", "--config", help="配置文件路径")
    parser.add_argument("--db", help="数据库路径")
    sub = parser.add_subparsers(dest="cmd")

    # portscan
    p = sub.add_parser("portscan", help="只扫描端口")
    p.add_argument("targets")
    p.add_argument("--workers", type=int)
    p.add_argument("--timeout", type=float)
    p.add_argument("--rate", type=int, default=0)
    p.add_argument("--exclude")
    p.add_argument("-o", "--output")
    p.add_argument("--sync", dest="sync_mode", action="store_true",
                   help="使用同步线程引擎（默认异步，更快）")
    p.set_defaults(func=cmd_portscan)

    # scan
    s = sub.add_parser("scan", help="扫描 + SLP探测 + 认证检测")
    s.add_argument("targets")
    s.add_argument("--workers", type=int)
    s.add_argument("--timeout", type=float)
    s.add_argument("--no-auth", action="store_true")
    s.add_argument("--rate", type=int, default=0)
    s.add_argument("--exclude")
    s.add_argument("-o", "--output")
    s.add_argument("--web", type=int, default=0, help="扫描后启动Web面板端口")
    s.add_argument("--sync", dest="sync_mode", action="store_true",
                   help="使用同步线程引擎（默认异步流水线，更快）")
    s.set_defaults(func=cmd_scan)

    # warn
    w = sub.add_parser("warn", help="扫描 + 离线检测 + 自动发警告")
    w.add_argument("targets")
    w.add_argument("--workers", type=int)
    w.add_argument("--bot-workers", type=int)
    w.add_argument("--timeout", type=float)
    w.add_argument("--no-auth", action="store_true")
    w.add_argument("--rate", type=int, default=0)
    w.add_argument("--exclude")
    w.add_argument("-u", "--username")
    w.add_argument("-m", "--message", action="append", help="警告消息（可多次）")
    w.add_argument("-f", "--message-file", help="从文件读取消息")
    w.add_argument("--authme", help="AuthMe密码")
    w.add_argument("-o", "--output")
    w.set_defaults(func=cmd_warn)

    # warn-db
    wd = sub.add_parser("warn-db", help="从数据库已扫描结果直接发警告（不重新扫描）")
    wd.add_argument("--auth", default="cracked", help="认证模式过滤（默认 cracked）")
    wd.add_argument("--modded", type=int, help="模组服过滤（1=模组，0=原版）")
    wd.add_argument("--search", help="关键词搜索（IP/MOTD/版本）")
    wd.add_argument("--limit", type=int, default=0, help="限制数量（0=全部）")
    wd.add_argument("--workers", type=int, default=5, help="并发数")
    wd.add_argument("-u", "--username", help="机器人用户名")
    wd.add_argument("-m", "--message", action="append", help="警告消息（可多次）")
    wd.add_argument("-f", "--message-file", help="从文件读取消息")
    wd.add_argument("--authme", help="AuthMe密码")
    wd.add_argument("--db", help="数据库路径")
    wd.set_defaults(func=cmd_warn_db)

    # masscan
    m = sub.add_parser("masscan", help="masscan 全网端口发现")
    m.add_argument("--targets", default="0.0.0.0/0")
    m.add_argument("--rate", type=int, default=1000)
    m.add_argument("--port", default="25565")
    m.add_argument("--output", default="scan_results.ndjson")
    m.add_argument("--exclude")
    m.add_argument("--auto-import", action="store_true")
    m.add_argument("--workers", type=int, default=32)
    m.add_argument("--no-auth", action="store_true")
    m.set_defaults(func=cmd_masscan)

    # import
    i = sub.add_parser("import", help="导入 masscan 结果")
    i.add_argument("ndjson")
    i.add_argument("--workers", type=int, default=32)
    i.add_argument("--timeout", type=float, default=4.0)
    i.add_argument("--no-auth", action="store_true")
    i.add_argument("--rate", type=int, default=0)
    i.set_defaults(func=cmd_import)

    # query
    q = sub.add_parser("query", help="查询数据库")
    q.add_argument("--auth")
    q.add_argument("--modded", type=int)
    q.add_argument("--search")
    q.add_argument("--limit", type=int, default=50)
    q.add_argument("--stats", action="store_true")
    q.set_defaults(func=cmd_query)

    # bot
    b = sub.add_parser("bot", help="单独对一台服务器登录发消息")
    b.add_argument("target", help="host:port")
    b.add_argument("--proto", type=int, default=None)
    b.add_argument("-u", "--username")
    b.add_argument("-m", "--message", action="append", help="警告消息（可多次）")
    b.add_argument("--authme")
    b.add_argument("--register", action="store_true")
    b.add_argument("--timeout", type=float, default=15.0)
    b.add_argument("--hold", type=float, default=4.0)
    b.set_defaults(func=cmd_bot)

    # web
    web = sub.add_parser("web", help="启动 Web 控制面板")
    web.add_argument("--port", type=int, default=8080)
    web.add_argument("--host", default="127.0.0.1")
    web.set_defaults(func=cmd_web)

    rnd = sub.add_parser("random", help="随机IP随机端口暴力扫描")
    rnd.add_argument("-n", "--count", type=int, default=1000, help="随机目标数量 (默认: 1000)")
    rnd.add_argument("-p", "--ports", default="25565-25575", help="端口范围 (默认: 25565-25575)")
    rnd.add_argument("-w", "--workers", type=int, default=200, help="线程数 (默认: 200)")
    rnd.add_argument("-t", "--timeout", type=float, default=2.0, help="超时秒数 (默认: 2.0)")
    rnd.add_argument("--probe", action="store_true", help="扫描后自动SLP探测")
    rnd.add_argument("--sync", dest="sync_mode", action="store_true", help="使用同步线程模式（默认异步高速）")
    rnd.add_argument("--exclude", default="exclude.conf", help="排除列表文件（默认: exclude.conf）")
    rnd.add_argument("--no-exclude", action="store_true", help="不使用排除列表")
    rnd.add_argument("-o", "--output", help="结果输出文件")
    rnd.set_defaults(func=cmd_random)
    # fav - 收藏管理
    fav = sub.add_parser("fav", help="收藏管理（list/add/remove/rescan/tags/import）")
    fav.add_argument("action", choices=["list", "add", "remove", "rescan", "tags", "import", "tags-list"],
                     help="操作: list=列表, add=添加, remove=移除, rescan=重查, tags=设置标签, import=导入, tags-list=所有标签")
    fav.add_argument("target", nargs="?", help="目标 host:port（add/remove/rescan/tags 需要）")
    fav.add_argument("--tags", help="标签，逗号分隔（add/tags）")
    fav.add_argument("--note", help="备注（add）")
    fav.add_argument("--tag", help="按标签筛选（list）")
    fav.add_argument("--search", help="关键词搜索（list）")
    fav.add_argument("--file", help="导入文件路径（import），每行 ip:port")
    fav.add_argument("--timeout", type=float, default=5.0, help="重查超时秒数（rescan）")
    fav.add_argument("--workers", type=int, default=10, help="重查并发数（rescan全部）")
    fav.set_defaults(func=cmd_fav)
    # rescan - 智能重扫管理（v3.3 新增）
    rs = sub.add_parser("rescan", help="智能重扫管理（v3.3新增）")
    rs.add_argument("--list", action="store_true", help="列出重扫队列")
    rs.add_argument("--run", action="store_true", help="执行到期重扫")
    rs.add_argument("--clear", action="store_true", help="清空重扫队列")
    rs.add_argument("--remove", help="移除指定目标 (ip:port)")
    rs.add_argument("--limit", type=int, default=50, help="限制数量")
    rs.add_argument("--db", help="数据库路径")
    rs.set_defaults(func=cmd_rescan)
    # distributed - 分布式任务分片（v3.3 新增）
    dist = sub.add_parser("distributed", help="分布式任务分片（v3.3新增）")
    dist.add_argument("--create", help="创建分片 (CIDR)")
    dist.add_argument("--shards", type=int, default=4, help="分片数量")
    dist.add_argument("--worker", help="Worker ID（领取并执行分片）")
    dist.add_argument("--job", help="任务 ID")
    dist.add_argument("--status", help="查看任务状态")
    dist.add_argument("--db", help="数据库路径")
    dist.set_defaults(func=cmd_distributed)

    # proxy - 代理管理（v3.3 新增）
    px = sub.add_parser("proxy", help="代理管理（获取/测试/列出）")
    px.add_argument("--fetch", action="store_true", help="从 ProxyScrape 获取代理")
    px.add_argument("--socks5", action="store_true", help="同时获取 SOCKS5 代理")
    px.add_argument("--check", action="store_true", help="健康检查所有代理")
    px.add_argument("--add", help="添加代理 (host:port 或 socks5://host:port)")
    px.add_argument("--file", help="代理文件路径")
    px.add_argument("--test-host", help="健康检查测试主机")
    px.add_argument("--test-port", type=int, help="健康检查测试端口")
    px.add_argument("--timeout", type=float, help="超时秒数")
    px.set_defaults(func=cmd_proxy)
    # rcon - RCON 客户端（v3.3 新增）
    rc = sub.add_parser("rcon", help="RCON 连接和命令执行")
    rc.add_argument("host", nargs="?", help="主机:端口")
    rc.add_argument("-p", "--password", help="RCON 密码")
    rc.add_argument("-c", "--command", help="执行单条命令")
    rc.add_argument("-f", "--commands-file", help="从文件加载命令列表")
    rc.add_argument("--delay", type=float, help="命令间延迟(秒)")
    rc.add_argument("--timeout", type=float, help="超时秒数")
    rc.set_defaults(func=cmd_rcon)
    # commands - 登录后自动执行命令（v3.3 新增）
    cm = sub.add_parser("commands", help="登录服务器后自动执行命令列表")
    cm.add_argument("target", nargs="?", help="主机:端口")
    cm.add_argument("-u", "--username", help="机器人用户名")
    cm.add_argument("-c", "--commands", help="命令列表，分号分隔")
    cm.add_argument("-s", "--script", help="命令脚本文件")
    cm.add_argument("--delay", type=float, help="命令间延迟(秒)")
    cm.add_argument("--timeout", type=float, help="超时秒数")
    cm.add_argument("--authme", help="AuthMe 密码")
    cm.set_defaults(func=cmd_commands)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1

    cfg = load_config(args.config if hasattr(args, 'config') else None)
    logger.setup_logger(cfg.get('log_level', 'INFO'))
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main() or 0)
