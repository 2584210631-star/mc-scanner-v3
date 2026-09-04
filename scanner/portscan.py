# -*- coding: utf-8 -*-
"""
端口扫描：多线程 TCP 全连接扫描，支持限速、进度回调、停止。
优化：分批提交任务，大网段不OOM；check_port用finally保证socket关闭。
"""
import socket
import time
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
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
    """检查单个端口是否开放（finally保证socket关闭）"""
    start = time.time()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        latency = (time.time() - start) * 1000
        if result == 0:
            return ScanResult(ip=ip, port=port, is_open=True, latency_ms=latency)
        return ScanResult(ip=ip, port=port, is_open=False, latency_ms=latency,
                          error=f"connect_ex={result}")
    except socket.timeout:
        return ScanResult(ip=ip, port=port, is_open=False, error="timeout")
    except Exception as e:
        return ScanResult(ip=ip, port=port, is_open=False, error=str(e)[:100])
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def scan_ports(targets, max_workers: int = 200, timeout: float = 3.0,
               show_progress: bool = True, rate: int = 0,
               stop_event: Optional[threading.Event] = None) -> list:
    """
    多线程扫描端口（分批提交，大网段不OOM）。
    rate: 每秒最大连接数，0=不限速
    """
    BATCH_SIZE = max(max_workers * 4, 200)
    target_list = list(targets)
    total = len(target_list)
    results = []
    done = 0
    open_count = 0
    lock = threading.Lock()

    if show_progress:
        print(f"[*] 开始扫描 {total} 个目标，并发数 {max_workers}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        target_iter = iter(target_list)
        last_submit = time.time()

        def _submit_one(ip, port):
            nonlocal last_submit
            if rate > 0:
                # 令牌桶限速：每次提交间隔至少 1/rate 秒
                min_interval = 1.0 / rate
                elapsed = time.time() - last_submit
                if elapsed < min_interval:
                    time.sleep(min_interval - elapsed)
                last_submit = time.time()
            futures[executor.submit(check_port, ip, port, timeout)] = (ip, port)

        # 初始填充一批
        for ip, port in target_iter:
            if stop_event and stop_event.is_set():
                break
            _submit_one(ip, port)
            if len(futures) >= BATCH_SIZE:
                break

        while futures:
            if stop_event and stop_event.is_set():
                for f in futures:
                    f.cancel()
                break
            done_set, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done_set:
                futures.pop(future)
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
                        pct = done * 100 // total if total else 0
                        print(f"[*] 进度: {done}/{total} ({pct}%) 开放: {open_count}")
            # 补充新任务
            for ip, port in target_iter:
                if stop_event and stop_event.is_set():
                    break
                _submit_one(ip, port)
                if len(futures) >= BATCH_SIZE:
                    break

    if show_progress:
        print(f"[*] 扫描完成，共 {total} 个目标，开放 {open_count} 个")
    return results


def get_open_ports(results: list) -> list:
    """从扫描结果中提取开放的 (ip, port)"""
    return [(r.ip, r.port) for r in results if r.is_open]
