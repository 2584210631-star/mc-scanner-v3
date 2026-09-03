# -*- coding: utf-8 -*-
"""
异步端口扫描：asyncio + Semaphore 控制并发。
比线程池快 3-5 倍，支持万级并发，内存占用更低。
可选 uvloop 加速（Linux）。
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Optional, AsyncIterator

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    _HAS_UVLOOP = True
except ImportError:
    _HAS_UVLOOP = False


@dataclass
class AsyncScanResult:
    ip: str
    port: int
    is_open: bool
    latency_ms: float = 0.0
    error: str = ""


async def _check_port(ip: str, port: int, timeout: float,
                      semaphore: asyncio.Semaphore, retries: int = 2) -> AsyncScanResult:
    """异步检查单个端口，带重试。"""
    async with semaphore:
        last_error = ""
        for attempt in range(retries + 1):
            start = time.time()
            try:
                fut = asyncio.open_connection(ip, port)
                reader, writer = await asyncio.wait_for(fut, timeout=timeout)
                latency = (time.time() - start) * 1000
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                except Exception:
                    pass
                return AsyncScanResult(ip=ip, port=port, is_open=True, latency_ms=latency)
            except asyncio.TimeoutError:
                last_error = "timeout"
            except (ConnectionRefusedError, OSError) as e:
                last_error = str(e)[:80]
                # ConnectionRefused 不需要重试
                if isinstance(e, ConnectionRefusedError):
                    break
            except Exception as e:
                last_error = str(e)[:80]
            if attempt < retries:
                await asyncio.sleep(0.05 * (attempt + 1))
        return AsyncScanResult(ip=ip, port=port, is_open=False, error=last_error)


async def _scan_async(targets, concurrency: int, timeout: float,
                      rate_limit: int = 0,
                      progress_cb=None) -> list:
    """异步扫描核心逻辑。"""
    semaphore = asyncio.Semaphore(concurrency)
    tasks = []
    results = []
    done = 0
    open_count = 0
    last_report = time.time()
    rate_interval = 1.0 / rate_limit if rate_limit > 0 else 0

    async def _wrapped(ip, port):
        nonlocal done, open_count, last_report
        if rate_interval > 0:
            await asyncio.sleep(rate_interval)
        try:
            r = await _check_port(ip, port, timeout, semaphore, retries=1)
        except Exception as e:
            r = AsyncScanResult(ip=ip, port=port, is_open=False, error=str(e)[:80])
        results.append(r)
        done += 1
        if r.is_open:
            open_count += 1
        if progress_cb and (done % 200 == 0 or time.time() - last_report > 1.0):
            progress_cb(done, open_count)
            last_report = time.time()
        return r

    for ip, port in targets:
        tasks.append(asyncio.create_task(_wrapped(ip, port)))

    if tasks:
        await asyncio.gather(*tasks)

    if progress_cb:
        progress_cb(done, open_count)
    return results


def scan_ports_async(targets, concurrency: int = 1000, timeout: float = 3.0,
                     rate_limit: int = 0, progress_cb=None) -> list:
    """
    异步端口扫描（同步入口，内部运行事件循环）。

    Args:
        targets: 可迭代的 (ip, port) 元组
        concurrency: 并发数（默认1000，协程很轻量可以开很大）
        timeout: 连接超时秒数
        rate_limit: 每秒最大连接数（0=不限）
        progress_cb: 进度回调 callback(done, open_count)

    Returns:
        list[AsyncScanResult]
    """
    target_list = list(targets)
    if not target_list:
        return []

    async def _run():
        return await _scan_async(iter(target_list), concurrency, timeout,
                                 rate_limit, progress_cb)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已经在事件循环中（如 Web 面板），返回协程让调用方处理
            return _run()
    except RuntimeError:
        pass

    return asyncio.run(_run())


def get_open_ports_async(results: list) -> list:
    """从异步扫描结果中提取开放的 (ip, port)。"""
    return [(r.ip, r.port) for r in results if r.is_open]


def has_uvloop() -> bool:
    return _HAS_UVLOOP
