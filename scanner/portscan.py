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
from dataclasses import dataclass, replace
from typing import Optional

from scanner.safe import (get_profile, shuffle_targets,
                             AdaptiveRateController, ScanProgressStore)


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


def scan_ports(targets, max_workers: int = None, timeout: float = 3.0,
               show_progress: bool = True, rate: int = None,
               stop_event: Optional[threading.Event] = None,
               progress_callback=None,
               mode: str = None, shuffle: bool = None,
               batch_cooldown: float = None, adaptive: bool = True,
               progress_file: str = None, seed: int = None,
               event_cb=None) -> list:
    """
    多线程扫描端口（分批提交，大网段不OOM）。
    rate: 每秒最大连接数，0=不限速
    progress_callback: 回调函数(done, total, open_count)，每500个或完成时调用
    mode: 扫描模式 safe / balanced / aggressive（None=balanced）
    shuffle: 是否打乱任务顺序（None 时按 mode 默认）
    batch_cooldown: 批间冷却秒数（None 时按 mode 默认，0=关闭）
    adaptive: 是否启用失败率自适应降速（默认 True）
    progress_file: 断点续扫进度文件路径（默认 None=不启用）
    """
    profile = get_profile(mode)
    # 副本方式修改参数，绝不改动 SCAN_MODES 全局配置（防跨调用污染）
    if batch_cooldown is not None:
        profile = replace(profile, batch_cooldown=batch_cooldown)
    max_workers = max_workers if max_workers is not None else profile.concurrency
    rate = rate if rate is not None else profile.rate
    do_shuffle = profile.shuffle if shuffle is None else shuffle
    BATCH_SIZE = max(max_workers * 4, 200)

    # 物化 + 随机化 + 断点续扫
    progress_store = ScanProgressStore(progress_file) if progress_file else None
    if progress_store is not None and progress_store.enabled:
        target_list, _resumed = progress_store.begin(targets)
    else:
        target_list = list(targets)
    if do_shuffle:
        target_list = shuffle_targets(target_list, seed=seed)

    total = len(target_list)
    results = []
    done = 0
    open_count = 0
    lock = threading.Lock()

    controller = None
    if adaptive and profile.adaptive and rate > 0:
        controller = AdaptiveRateController(profile, event_cb=event_cb)

    if show_progress:
        print(f"[*] 开始扫描 {total} 个目标，并发数 {max_workers}，"
              f"模式 {profile.mode}"
              + (f"，限速 {rate}/s" if rate > 0 else ""))
        if do_shuffle:
            print(f"[*] 已随机化扫描顺序（防顺序扫描特征）")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        target_iter = iter(target_list)
        last_submit = time.time()

        def _submit_one(ip, port):
            nonlocal last_submit
            # 疑似封禁时自动暂停（每提交一个检查一次）
            if controller is not None and controller.ban_suspected:
                import config as _cfg
                on_ban = _cfg.get("on_ban_suspect", "pause")
                if on_ban == "abort":
                    if stop_event:
                        stop_event.set()
                    return
                # pause: 睡 30 秒再继续，给封禁恢复时间
                time.sleep(30)
            cur_rate = controller.rate if controller is not None else rate
            if cur_rate > 0:
                # 令牌桶限速：每次提交间隔至少 1/rate 秒
                min_interval = 1.0 / cur_rate
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
                    # 自适应控制
                    if controller is not None:
                        if result.is_open:
                            controller.record("open")
                        elif "timeout" in (result.error or "").lower():
                            controller.record("timeout")
                        elif "refused" in (result.error or "").lower():
                            controller.record("refused")
                        else:
                            controller.record("error")
                    # 断点续扫
                    if progress_store is not None:
                        progress_store.done((result.ip, result.port))
                    if show_progress and (done % 500 == 0 or done == total):
                        pct = done * 100 // total if total else 0
                        print(f"[*] 进度: {done}/{total} ({pct}%) 开放: {open_count}")
                    if progress_callback and (done % 500 == 0 or done == total):
                        try:
                            progress_callback(done, total, open_count)
                        except Exception:
                            pass
            # 批次冷却：每完成 batch_size 个暂停（防突发连接风暴）
            if profile.batch_cooldown > 0 and done > 0 and done % profile.batch_size == 0:
                if not (stop_event and stop_event.is_set()):
                    print(f"[*] 批次冷却 {profile.batch_cooldown:.1f}s（已扫 {done}）...")
                    time.sleep(profile.batch_cooldown)
            # 补充新任务
            for ip, port in target_iter:
                if stop_event and stop_event.is_set():
                    break
                _submit_one(ip, port)
                if len(futures) >= BATCH_SIZE:
                    break

    if progress_store is not None:
        progress_store.finish()
    if show_progress:
        print(f"[*] 扫描完成，共 {total} 个目标，开放 {open_count} 个")
        if controller is not None and controller.events:
            print("[*] 防封禁事件：")
            for evt in controller.events[-10:]:
                print(f"    [{evt['ts']}] {evt['type']}: {evt['msg']}")
    return results


def get_open_ports(results: list) -> list:
    """从扫描结果中提取开放的 (ip, port)"""
    return [(r.ip, r.port) for r in results if r.is_open]
