# -*- coding: utf-8 -*-
"""
业务编排层：扫描相关业务。
cli.py 和 web/app.py 都调用这里，消除重复逻辑。
"""
import os
from typing import Optional

import config
import logger
from scanner.engine import ScanEngine
from scanner.portscan import scan_ports, get_open_ports
from scanner.masscan import has_masscan, run_masscan
from scanner.random_scan import random_scan, parse_port_ranges
from scanner.targets import parse_targets, count_targets
from scanner.exclude import Excluder
from storage import db


def _build_engine(db_path=None, workers=None, timeout=None, auth_check=True,
                  rate_limit=0, stop_event=None) -> ScanEngine:
    cfg = config.load_config()
    return ScanEngine(
        db_path=db_path or cfg["db_path"],
        workers=workers or cfg["workers"],
        timeout=timeout or cfg["timeout"],
        auth_check=auth_check,
        rate_limit=rate_limit,
        stop_event=stop_event,
        # v3.2.1 新增特性
        rescan_enabled=cfg.get("rescan_enabled", False),
        duplicate_detection=cfg.get("duplicate_detection", False),
        discord_webhook=cfg.get("discord_webhook", ""),
    )


def parse_and_filter_targets(targets_str: str, ports=None, exclude_file=None):
    """解析目标字符串 + 排除过滤，返回 (targets列表, 目标数)"""
    cfg = config.load_config()
    ports = ports or cfg["ports"]
    exclude_file = exclude_file or cfg["exclude_file"]
    targets_list = [t.strip() for t in targets_str.split(',') if t.strip()]
    parsed = list(parse_targets(targets_list, ports))
    ex = Excluder(exclude_file)
    filtered = list(ex.filter_targets(iter(parsed)))
    return filtered, len(filtered)


def run_full_scan(targets_str: str, workers=None, timeout=None, auth_check=True,
                  rate=0, exclude_file=None, db_path=None, stop_event=None) -> list:
    """完整扫描：端口扫描 + SLP探测 + 认证检测"""
    cfg = config.load_config()
    targets, total = parse_and_filter_targets(targets_str, exclude_file=exclude_file)
    if not targets:
        logger.warning("没有有效目标")
        return []
    logger.info(f"开始扫描 {total} 个目标")
    engine = _build_engine(db_path, workers, timeout, auth_check, rate, stop_event)
    results = engine.scan_with_portscan(
        iter(targets),
        scan_threads=cfg["scan_threads"],
        scan_timeout=cfg["scan_timeout"],
    )
    logger.info(f"扫描完成，发现 {len(results)} 个 Minecraft 服务器")
    return results


def run_portscan_only(targets_str: str, scan_threads=None, scan_timeout=None,
                      rate=0, exclude_file=None) -> list:
    """只扫描端口，不做SLP探测"""
    cfg = config.load_config()
    targets, total = parse_and_filter_targets(targets_str, exclude_file=exclude_file)
    if not targets:
        logger.warning("没有有效目标")
        return []
    logger.info(f"开始端口扫描 {total} 个目标")
    results = scan_ports(
        targets,
        max_workers=scan_threads or cfg["scan_threads"],
        timeout=scan_timeout or cfg["scan_timeout"],
        rate=rate,
    )
    open_ports = get_open_ports(results)
    logger.info(f"端口扫描完成，开放 {len(open_ports)} 个端口")
    return results


def run_random_scan(count=1000, ports="25565-25575", workers=200, timeout=2.0,
                    do_probe=True, stop_event=None) -> list:
    """随机IP随机端口暴力扫描"""
    logger.info(f"随机扫描开始: {count} 个目标, 端口 {ports}")
    port_ranges = parse_port_ranges(ports)
    open_ports = random_scan(count, workers, timeout, port_ranges)
    logger.info(f"随机扫描完成: 发现 {len(open_ports)} 个开放端口")
    if do_probe and open_ports:
        logger.info(f"开始 SLP 探测 {len(open_ports)} 个目标")
        engine = _build_engine(workers=min(32, workers), timeout=3.0, stop_event=stop_event)
        results = engine.probe_list(open_ports)
        logger.info(f"SLP 探测完成: 发现 {len([r for r in results if r.get('state')=='up'])} 个 MC 服务器")
        return results
    return [{"ip": ip, "port": port, "state": "unknown", "auth": "unknown"}
            for ip, port in open_ports]


def run_masscan_scan(targets="0.0.0.0/0", port="25565", rate=1000,
                     exclude_file=None, output_file=None, auto_import=False,
                     workers=None, auth_check=True, db_path=None, stop_event=None) -> str:
    """masscan高速端口扫描，返回结果文件路径"""
    cfg = config.load_config()
    if not has_masscan():
        raise RuntimeError("masscan 未安装")
    exclude_file = exclude_file or cfg["exclude_file"]
    output_file = output_file or "scan_results.ndjson"
    logger.info(f"masscan 扫描开始: {targets}:{port}, 速率 {rate}/s")
    result_path = run_masscan(
        targets=targets, ports=port, rate=rate,
        exclude_file=exclude_file, output_file=output_file,
    )
    logger.info(f"masscan 扫描完成: {result_path}")
    if auto_import:
        import_masscan_results(result_path, workers=workers, auth_check=auth_check,
                               db_path=db_path, stop_event=stop_event)
    return result_path


def import_masscan_results(ndjson_path: str, workers=None, auth_check=True,
                           db_path=None, stop_event=None) -> list:
    """导入masscan结果，做SLP+认证检测"""
    if not os.path.exists(ndjson_path):
        raise FileNotFoundError(f"文件不存在: {ndjson_path}")
    engine = _build_engine(db_path, workers, auth_check=auth_check, stop_event=stop_event)
    results = engine.import_masscan(ndjson_path, then_auth=auth_check)
    logger.info(f"导入完成，共 {len(results)} 条记录")
    return results


def query_database(db_path=None, auth=None, modded=None, search=None,
                   limit=50, offset=0) -> list:
    """查询SQLite数据库"""
    cfg = config.load_config()
    db_path = db_path or cfg["db_path"]
    if not os.path.exists(db_path):
        return []
    return db.query(db_path, auth=auth, modded=modded, search=search,
                    limit=limit, offset=offset)


def get_db_stats(db_path=None) -> dict:
    """获取数据库统计信息"""
    cfg = config.load_config()
    db_path = db_path or cfg["db_path"]
    if not os.path.exists(db_path):
        return {"total": 0, "by_auth": {}, "online_servers": 0, "by_version": {}}
    return db.stats(db_path)


def run_scanner(scan_type: str = "tcp", targets=None, ports=None, workers=None,
                timeout=None, rate=0, stop_event=None) -> list:
    """通过扫描器工厂（scanner.base.get_scanner）统一执行端口扫描。

    返回开放的 (ip, port) 列表，上层无需关心具体扫描器类型。
    scan_type: tcp / masscan / random
    """
    from scanner.base import get_scanner
    cfg = config.load_config()
    # 按扫描器类型传入构造参数，避免 tcp 等无参扫描器收到多余 kwargs
    kwargs = {}
    if scan_type == "masscan":
        kwargs["rate"] = rate or 1000
    elif scan_type == "random":
        kwargs["target_count"] = workers or 1000
    scanner = get_scanner(scan_type, **kwargs)
    return scanner.scan_list(
        targets or ["127.0.0.1"],
        ports=ports or cfg["ports"],
        max_workers=workers or cfg["scan_threads"],
        timeout=timeout or cfg["scan_timeout"],
        rate=rate,
        stop_event=stop_event,
    )
