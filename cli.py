#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MC Scanner v3Pro - 综合 Minecraft 服务器扫描器
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

from scanner.targets import parse_targets, count_targets, parse_port_spec
from scanner.exclude import Excluder
from scanner.portscan import scan_ports, get_open_ports
from scanner.masscan import has_masscan, run_masscan
from scanner.engine import ScanEngine
from storage import db
from core.bot import join_and_warn, DEFAULT_WARNING_MESSAGES, MCBot
from core.protocol import get_version_name


DEFAULT_CONFIG = {
    "username": "SecurityBot",
    "messages": None,
    "ports": [25565],
    "scan_threads": 200,
    "scan_timeout": 2.5,
    "bot_threads": 10,
    "bot_timeout": 12,
    "message_delay": 0.8,
    "retry_count": 1,
    "rate": 0,
    "authme_password": "",
    "exclude_file": "exclude.conf",
    "db_path": "mcscanner.db",
    "auto_save_db": True,
    "output_format": "json",
    "output_file": None,
}


def load_config(path: str = None) -> dict:
    cfg = DEFAULT_CONFIG.copy()
    config_path = path or "config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
        print(f"[*] 已加载配置: {config_path}")
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
        print(f"[*] 结果已保存: {output_file} (CSV)")
    else:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
        print(f"[*] 结果已保存: {output_file} (JSON)")


def cmd_portscan(args, cfg):
    targets = list(parse_targets(args.targets.split(','), cfg['ports']))
    ex = Excluder(args.exclude or cfg['exclude_file'])
    targets = list(ex.filter_targets(iter(targets)))
    if not targets:
        print("[!] 没有有效目标"); return
    print(f"[*] 目标数: {len(targets)} | 端口: {cfg['ports']} | 线程: {cfg['scan_threads']}")
    results = scan_ports(targets, max_workers=cfg['scan_threads'],
                         timeout=cfg['scan_timeout'], rate=args.rate or cfg['rate'])
    open_ports = get_open_ports(results)
    print(f"\n[*] 开放端口 ({len(open_ports)} 个):")
    for ip, port in open_ports:
        print(f"  {ip}:{port}")
    if args.output:
        save_results([{'ip': r.ip, 'port': r.port, 'open': r.is_open,
                       'latency_ms': round(r.latency_ms, 1)} for r in results],
                     args.output, cfg['output_format'])


def cmd_scan(args, cfg):
    if args.workers: cfg['scan_threads'] = args.workers
    if args.timeout: cfg['scan_timeout'] = args.timeout
    targets = list(parse_targets(args.targets.split(','), cfg['ports']))
    ex = Excluder(args.exclude or cfg['exclude_file'])
    targets = list(ex.filter_targets(iter(targets)))
    if not targets:
        print("[!] 没有有效目标"); return

    engine = ScanEngine(
        db_path=args.db or cfg['db_path'],
        workers=args.workers or 32,
        timeout=args.timeout or 4.0,
        auth_check=not args.no_auth,
        rate_limit=args.rate or cfg['rate'],
    )
    results = engine.scan_with_portscan(iter(targets),
                                          scan_threads=cfg['scan_threads'],
                                          scan_timeout=cfg['scan_timeout'])
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
    if args.workers: cfg['scan_threads'] = args.workers
    if args.bot_workers: cfg['bot_threads'] = args.bot_workers
    targets = list(parse_targets(args.targets.split(','), cfg['ports']))
    ex = Excluder(args.exclude or cfg['exclude_file'])
    targets = list(ex.filter_targets(iter(targets)))
    if not targets:
        print("[!] 没有有效目标"); return

    messages = None
    if args.message:
        messages = args.message if isinstance(args.message, list) else [args.message]
    elif args.message_file:
        with open(args.message_file, 'r', encoding='utf-8') as f:
            messages = [l.strip() for l in f if l.strip()]
    messages = messages or cfg['messages'] or DEFAULT_WARNING_MESSAGES

    engine = ScanEngine(
        db_path=args.db or cfg['db_path'],
        workers=args.workers or 32,
        timeout=args.timeout or 4.0,
        auth_check=not args.no_auth,
        rate_limit=args.rate or cfg['rate'],
        bot_workers=cfg['bot_threads'],
        bot_timeout=cfg['bot_timeout'],
    )
    results = engine.warn_targets(
        iter(targets),
        username=args.username or cfg['username'],
        messages=messages,
        message_delay=cfg['message_delay'],
        authme_password=args.authme or cfg['authme_password'] or None,
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
    db_path = args.db or cfg.get('db_path', 'mcscanner.db')
    if not os.path.exists(db_path):
        print(f"[!] 数据库不存在: {db_path}")
        print("[!] 请先运行 scan 命令扫描并保存结果到数据库")
        return
    auth = args.auth or "cracked"
    print(f"[*] 从数据库读取认证模式为 '{auth}' 的服务器...")
    rows = db.query(db_path, auth=auth, modded=args.modded,
                     search=args.search, limit=args.limit or 100000, offset=0)
    if not rows:
        print("[!] 数据库中没有符合条件的服务器")
        return
    print(f"[*] 找到 {len(rows)} 个服务器，开始发送警告（不重新扫描）...")
    messages = None
    if args.message:
        messages = args.message if isinstance(args.message, list) else [args.message]
    elif args.message_file:
        with open(args.message_file, 'r', encoding='utf-8') as f:
            messages = [l.strip() for l in f if l.strip()]
    messages = messages or cfg.get('messages') or DEFAULT_WARNING_MESSAGES
    from concurrent.futures import ThreadPoolExecutor, as_completed
    workers = args.workers or cfg.get('bot_threads', 5)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for row in rows:
            ip = row.get('ip')
            port = row.get('port', 25565)
            if not ip:
                continue
            fut = ex.submit(join_and_warn, ip, port,
                            args.username or cfg.get('username', 'SecurityBot'),
                            messages, 15.0, cfg.get('message_delay', 0.8),
                            args.authme or cfg.get('authme_password') or None, None)
            futures[fut] = (ip, port)
        for i, fut in enumerate(as_completed(futures), 1):
            ip, port = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                status = "OK" if r.success else "FAIL"
                print(f"  [{i}/{len(rows)}] {status} {ip}:{port} - 发{r.messages_sent}条 {r.error or ''}")
            except Exception as e:
                results.append(None)
                print(f"  [{i}/{len(rows)}] FAIL {ip}:{port} - {e}")
    success = sum(1 for r in results if r and r.success)
    msg_sent = sum(r.messages_sent for r in results if r)
    print(f"\n{'='*50}")
    print(f"  警告完成（从数据库，未重新扫描）")
    print(f"  总目标: {len(results)}")
    print(f"  成功登录: {success}")
    print(f"  发送消息总数: {msg_sent}")
    print(f"{'='*50}")


def cmd_masscan(args, cfg):
    if not has_masscan():
        print("[!] masscan 未安装，请先安装: sudo apt install masscan")
        return
    output_file = run_masscan(
        targets=args.targets or "0.0.0.0/0",
        ports=args.port or "25565",
        rate=args.rate or 1000,
        exclude_file=args.exclude or cfg['exclude_file'],
        output_file=args.output or "scan_results.ndjson",
    )
    print(f"[*] masscan 结果: {output_file}")
    if args.auto_import:
        engine = ScanEngine(db_path=args.db or cfg['db_path'],
                            workers=args.workers or 32,
                            auth_check=not args.no_auth)
        engine.import_masscan(output_file, then_auth=not args.no_auth)


def cmd_import(args, cfg):
    engine = ScanEngine(db_path=args.db or cfg['db_path'],
                        workers=args.workers or 32,
                        timeout=args.timeout or 4.0,
                        auth_check=not args.no_auth,
                        rate_limit=args.rate or 0)
    engine.import_masscan(args.ndjson, then_auth=not args.no_auth)
    print(f"[*] 导入完成。统计: {engine.counters}")


def cmd_query(args, cfg):
    db_path = args.db or cfg['db_path']
    if not os.path.exists(db_path):
        print(f"[!] 数据库不存在: {db_path}")
        return
    if args.stats:
        s = db.stats(db_path)
        print(f"\n数据库统计:")
        print(f"  总记录: {s['total']}")
        print(f"  有人在线: {s['online_servers']}")
        print(f"  认证模式分布:")
        for auth, count in s['by_auth'].items():
            print(f"    {auth}: {count}")
        return
    rows = db.query(db_path, auth=args.auth, modded=args.modded,
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
            bot.send_chat(args.message)
            print(f"[+] 已发送: {args.message}")
        bot.keep_alive(args.hold or 4.0)
        print("[+] 保持连接结束")
    except Exception as e:
        print(f"[!] 失败: {e}")
    finally:
        bot.close()


def cmd_web(args, cfg):
    from web.app import run
    run(args.db or cfg['db_path'], port=args.port, host=args.host)


def main():
    parser = argparse.ArgumentParser(description="MC Scanner v3Pro - 综合 Minecraft 服务器扫描器")
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
    b.add_argument("-m", "--message")
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

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1

    cfg = load_config(args.config if hasattr(args, 'config') else None)
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main() or 0)
