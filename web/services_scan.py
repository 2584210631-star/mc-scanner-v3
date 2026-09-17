# -*- coding: utf-8 -*-
"""Scan background worker."""
import time
from datetime import datetime
import config, logger
try:
    from web import state
except ImportError:
    import state  # type: ignore

scan_state = state.scan_state
scan_lock = state.scan_lock
scan_stop_event = state.scan_stop_event

def _log(msg):
    state.log_scan(msg)

def _scan_worker(targets_list, config):
    pass
    try:
        state.task_counter += 1
        scan_stop_event.clear()
        with scan_lock:
            scan_state["task_id"] = state.task_counter
            scan_state["running"] = True
            scan_state["results"] = []
            scan_state["logs"] = []
            scan_state["progress"] = 0
            scan_state["scanned"] = 0
            scan_state["open_count"] = 0
            scan_state["start_time"] = time.time()
        _log(f"任务 #{state.task_counter} 开始，目标数: {len(targets_list)}")

        # 进度回调：实时更新扫描状态
        total_targets = len(targets_list)
        def _on_progress(done, total, open_count):
            with scan_lock:
                scan_state["scanned"] = done
                scan_state["total"] = total
                scan_state["progress"] = int(done * 100 / total) if total else 0
                scan_state["open_count"] = open_count

        # 连续扫描模式：大网段拆成 /24 逐个扫描
        if config.get("continuous"):
            import ipaddress
            subnets = []
            for t in targets_list:
                # targets_list 是 (ip, port) tuple 列表，连续扫描只需要 IP 部分
                if isinstance(t, (tuple, list)):
                    t = str(t[0]).strip()
                else:
                    t = str(t).strip()
                if not t:
                    continue
                try:
                    net = ipaddress.ip_network(t, strict=False)
                    if net.prefixlen < 24:
                        for subnet in net.subnets(new_prefix=24):
                            subnets.append(str(subnet))
                    else:
                        subnets.append(t)
                except:
                    subnets.append(t)
            _log(f"连续扫描模式: 拆分为 {len(subnets)} 个 /24 网段")
            from scanner.async_engine import AsyncScanEngine
            all_results = []
            for i, subnet in enumerate(subnets):
                _log(f"连续扫描 [{i+1}/{len(subnets)}]: {subnet}")
                try:
                    sub_targets = list(parse_targets([subnet], config.get("ports", [25565])))
                    if not sub_targets:
                        continue
                    engine = AsyncScanEngine(stop_event=scan_stop_event, 
                        db_path=config.get("db_path", "mcscanner.db"),
                        concurrency=config.get("scan_threads", 200),
                        slp_concurrency=min(400, config.get("workers", 32) * 10),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                    )
                    sub_results = engine.scan_with_portscan(
                        iter(sub_targets),
                        scan_concurrency=config.get("scan_threads", 200),
                        scan_timeout=config.get("scan_timeout", 2.5),
                        progress_callback=_on_progress,
                    )
                    # 只保留up结果，避免大范围连续扫描时offline结果占满内存
                    up_results = [r for r in sub_results if r.get("state") == "up"]
                    all_results.extend(up_results)
                    with scan_lock:
                        scan_state["results"] = all_results
                        scan_state["progress"] = int((i + 1) * 100 / len(subnets)) if subnets else 100
                    _log(f"  网段 {subnet} 完成，累计 {len(all_results)} 个在线服务器")
                except Exception as e:
                    _log(f"  网段 {subnet} 出错: {e}")
            with scan_lock:
                scan_state["results"] = all_results
                scan_state["progress"] = len(all_results)
                scan_state["total"] = len(all_results)
            _log(f"连续扫描完成，共 {len(all_results)} 个服务器")
            # 邮件通知
            try:
                from core.notifier import notify_scan_complete
                duration = time.time() - scan_state.get("start_time", time.time())
                ok, err = notify_scan_complete(all_results, len(targets_list), duration, state.task_counter)
                if ok:
                    _log("扫描完成邮件已发送")
                elif err and "未启用" not in err:
                    _log(f"邮件通知失败: {err}")
            except Exception as e:
                _log(f"邮件通知异常: {e}")
            history_entry = {
                "id": state.task_counter,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "targets": len(targets_list),
                "found": len(all_results),
                "mode": "continuous",
                "config": {k: v for k, v in config.items() if k != "db_path"},
            }
            with scan_lock:
                scan_state["history"].insert(0, history_entry)
                if len(scan_state["history"]) > 20:
                    scan_state["history"] = scan_state["history"][:20]
            return

        use_masscan = config.get("use_masscan", False)
        portscan_only = config.get("portscan_only", False)
        results = []

        if use_masscan:
            if not has_masscan():
                _log("masscan 未找到，回退到 Python 扫描")
                use_masscan = False
            else:
                _log(f"使用 masscan 高速扫描，速率: {config.get('masscan_rate', 5000)}/s")
                # targets_list 是 (ip, port) tuple，masscan 只需要 IP（去重）
                unique_ips = list(dict.fromkeys(t[0] if isinstance(t, (tuple, list)) else str(t) for t in targets_list))
                targets_str = ",".join(unique_ips)
                ports_str = ",".join(str(p) for p in config.get("ports", [25565]))
                try:
                    ndjson_path = run_masscan(
                        targets=targets_str,
                        ports=ports_str,
                        rate=config.get("masscan_rate", 5000),
                        exclude_file=config.get("exclude_file", "exclude.conf"),
                    )
                    _log(f"masscan 扫描完成: {ndjson_path}")
                    if portscan_only:
                        raw = parse_masscan_json(ndjson_path)
                        results = [{"ip": ip, "port": port, "auth": "unknown",
                                    "version": None, "motd": None,
                                    "players_online": 0, "players_max": 0,
                                    "ping_ms": None, "proto": None}
                                   for ip, port, _ in raw]
                    else:
                        engine = ScanEngine(stop_event=scan_stop_event, 
                            db_path=config.get("db_path", "mcscanner.db"),
                            workers=config.get("workers", 32),
                            timeout=config.get("timeout", 4.0),
                            auth_check=config.get("auth_check", True),
                            rate_limit=config.get("rate", 0),
                        )
                        results = engine.import_masscan(ndjson_path, then_auth=config.get("auth_check", True))
                        _log(f"认证检测完成，共 {len(results)} 个服务器")
                except Exception as e:
                    _log(f"masscan 出错: {e}，回退 Python 扫描")
                    use_masscan = False

        if not use_masscan:
            if portscan_only:
                _log("只扫端口模式（不做 SLP 探测）")
                raw_results = scan_ports(
                    targets_list,
                    max_workers=config.get("scan_threads", 200),
                    timeout=config.get("scan_timeout", 2.5),
                    progress_callback=_on_progress,
                )
                open_ports = get_open_ports(raw_results)
                results = [{"ip": ip, "port": port, "auth": "unknown",
                            "version": None, "motd": None,
                            "players_online": 0, "players_max": 0,
                            "ping_ms": None, "proto": None}
                           for ip, port in open_ports]
                _log(f"端口扫描完成，开放: {len(results)} 个")
            else:
                if config.get("async_mode"):
                    from scanner.async_engine import AsyncScanEngine
                    from scanner.async_portscan import has_uvloop
                    from scanner.async_probe import has_simdjson
                    _log(f"异步流水线扫描（uvloop: {'启用' if has_uvloop() else '未安装'}, "
                         f"simdjson: {'启用' if has_simdjson() else '未安装'}）")
                    async_engine = AsyncScanEngine(
                        db_path=config.get("db_path", "mcscanner.db"),
                        concurrency=config.get("scan_threads", 1000),
                        slp_concurrency=config.get("workers", 200),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                        stop_event=scan_stop_event,
                    )
                    results = async_engine.scan_with_portscan(iter(targets_list))
                else:
                    engine = ScanEngine(stop_event=scan_stop_event, 
                        db_path=config.get("db_path", "mcscanner.db"),
                        workers=config.get("workers", 32),
                        timeout=config.get("timeout", 4.0),
                        auth_check=config.get("auth_check", True),
                        rate_limit=config.get("rate", 0),
                    )
                    results = engine.scan_with_portscan(
                        iter(targets_list),
                        scan_threads=config.get("scan_threads", 200),
                        scan_timeout=config.get("scan_timeout", 2.5),
                        progress_callback=_on_progress,
                    )

        with scan_lock:
            scan_state["results"] = results
            scan_state["progress"] = 100
            scan_state["total"] = len(results)
        _log(f"扫描完成，共发现 {len(results)} 个服务器")

        # 邮件通知
        try:
            from core.notifier import notify_scan_complete
            duration = time.time() - scan_state.get("start_time", time.time())
            ok, err = notify_scan_complete(results, len(targets_list), duration, state.task_counter)
            if ok:
                _log("扫描完成邮件已发送")
            elif err and "未启用" not in err:
                _log(f"邮件通知失败: {err}")
        except Exception as e:
            _log(f"邮件通知异常: {e}")

        with scan_lock:
            history_entry = {
                "id": state.task_counter,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "targets": len(targets_list),
                "found": len(results),
                "mode": "masscan" if use_masscan else ("portscan" if portscan_only else "full"),
                "config": {k: v for k, v in config.items() if k != "db_path"},
            }
            scan_state["history"].insert(0, history_entry)
            if len(scan_state["history"]) > 20:
                scan_state["history"] = scan_state["history"][:20]
    except Exception as e:
        import traceback
        _log(f"扫描出错: {e}")
        _log(f"错误详情: {traceback.format_exc()}")
        with scan_lock:
            scan_state["error"] = str(e)
            scan_state["traceback"] = traceback.format_exc()
    finally:
        scan_stop_event.clear()
        with scan_lock:
            scan_state["running"] = False

