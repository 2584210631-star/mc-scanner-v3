# -*- coding: utf-8 -*-
"""
端口扫描：多线程 TCP 全连接扫描，支持限速、进度回调、停止。
"""
import socket
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ScanResult:
    """端口扫描结果"""
    ip: str
    port: int
    is_open: bool
    latency_ms: float = 0.0
    error: str = ""


def check_port(ip: str, port: int, timeout: float = 3.0) -> ScanResult:
    """检查单个端口是否开放"""
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        latency = (time.time() - start) * 1000
        sock.close()
        if result == 0:
            return ScanResult(ip=ip, port=port, is_open=True, latency_ms=latency)
        return ScanResult(ip=ip, port=port, is_open=False, latency_ms=latency,
                          error=f"connect_ex={result}")
    except socket.timeout:
        return ScanResult(ip=ip, port=port, is_open=False, error="timeout")
    except Exception as e:
        return ScanResult(ip=ip, port=port, is_open=False, error=str(e)[:100])


def scan_ports(targets, max_workers: int = 200, timeout: float = 3.0,
               show_progress: bool = True, rate: int = 0,
               stop_event: Optional[threading.Event] = None) -> list:
    """
    多线程扫描端口。
    rate: 每秒最大连接数，0=不限速
    """
    targets = list(targets)
    total = len(targets)
    results = []
    done = 0
    open_count = 0
    lock = threading.Lock()

    if show_progress:
        print(f"[*] 开始扫描 {total} 个目标，并发数 {max_workers}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        last_submit = time.time()
        submitted = 0
        for ip, port in targets:
            if stop_event and stop_event.is_set():
                break
            if rate > 0:
                submitted += 1
                if submitted % rate == 0:
                    elapsed = time.time() - last_submit
                    if elapsed < 1.0:
                        time.sleep(1.0 - elapsed)
                    last_submit = time.time()
            futures[executor.submit(check_port, ip, port, timeout)] = (ip, port)

        for future in as_completed(futures):
            if stop_event and stop_event.is_set():
                for f in futures:
                    f.cancel()
                break
            try:
                result = future.result()
            except Exception:
                continue
            results.append(result)
            with lock:
                done += 1
                if result.is_open:
                    open_count += 1
                if show_progress and (done % 500 == 0 or done == total):
                    print(f"[*] 进度: {done}/{total} ({done*100//total}%) 开放: {open_count}")

    if show_progress:
        print(f"[*] 扫描完成，共 {total} 个目标，开放 {open_count} 个")
    return results


def get_open_ports(results: list) -> list:
    """从扫描结果中提取开放的 (ip, port)"""
    return [(r.ip, r.port) for r in results if r.is_open]
