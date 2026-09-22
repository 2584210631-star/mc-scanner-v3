# -*- coding: utf-8 -*-
"""
防封禁扫描策略（v3.6.0 新增）

解决痛点：全端口扫描时，顺序扫描 + 高并发 + 无限速导致出口 IP 被
目标网络限流/封禁（触发 IDS / fail2ban / 运营商限流），连其他设备都连不上。

提供：
1. 扫描模式分级（stealth / balanced / aggressive）
2. 端口随机化（打乱扫描顺序，去掉"顺序递增"特征）
3. 批次 + 冷却（每批扫完暂停，降低突发）
4. 自适应速率（按失败率动态降速/恢复，检测疑似封禁）
5. 断点续扫（中断后从上次位置继续，避免重扫触发二次封禁）

所有功能默认关闭/保守开启，向后兼容 v3 行为。
"""
import json
import os
import random
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Optional


# ---------------------------------------------------------------- 模式配置

@dataclass
class ScanProfile:
    """扫描模式参数"""
    mode: str
    concurrency: int          # 并发连接数
    rate: int                 # 每秒最大连接数（0=不限制）
    batch_size: int           # 每批任务数，达到后进入冷却
    batch_cooldown: float     # 批间冷却秒数
    shuffle: bool             # 是否打乱任务顺序
    adaptive: bool            # 是否启用失败率自适应降速
    max_rate: int = 0         # 自适应允许的最大速率（0=用 rate）

    def effective_max_rate(self) -> int:
        return self.max_rate if self.max_rate > 0 else self.rate


SCAN_MODES = {
    # 隐蔽模式：低并发、低速率、小批次 + 冷却、随机化、自适应
    "stealth": ScanProfile(
        mode="stealth", concurrency=150, rate=20,
        batch_size=400, batch_cooldown=1.5,
        shuffle=True, adaptive=True, max_rate=40,
    ),
    # 平衡模式（默认）：保守默认，接近 stealth 但保留一定速度
    "balanced": ScanProfile(
        mode="balanced", concurrency=400, rate=25,
        batch_size=2000, batch_cooldown=0.5,
        shuffle=True, adaptive=True, max_rate=50,
    ),
    # 激进模式：仅内网/信任网络，关闭保护
    "aggressive": ScanProfile(
        mode="aggressive", concurrency=5000, rate=0,
        batch_size=20000, batch_cooldown=0.0,
        shuffle=False, adaptive=False, max_rate=0,
    ),
}


def get_profile(mode: Optional[str]) -> ScanProfile:
    """按名称获取扫描模式，未知/None 回退 balanced"""
    if mode and mode in SCAN_MODES:
        return SCAN_MODES[mode]
    return SCAN_MODES["balanced"]


# ---------------------------------------------------------------- 随机化

def shuffle_targets(targets, seed: Optional[int] = None, max_items: int = 500_000):
    """
    打乱 (ip, port) 任务顺序，去掉"顺序递增"扫描特征。
    - 仅对可物化的列表生效（≤ max_items），避免大网段 OOM
    - 超过上限时原样返回并提示
    """
    try:
        lst = list(targets)
    except Exception:
        return list(targets)
    if len(lst) > max_items:
        print(f"[!] 任务数 {len(lst)} 超过随机化上限 {max_items}，跳过打乱（建议分批扫描）")
        return lst
    if seed is not None:
        random.Random(seed).shuffle(lst)
    else:
        random.shuffle(lst)
    return lst


# ---------------------------------------------------------------- 自适应速率 / 封禁检测

class AdaptiveRateController:
    """
    失败率自适应速率控制 + 疑似封禁检测。

    原理：正常扫描中，关闭端口返回 ConnectionRefused（秒回）；当网络被
    限流/封禁时，表现为大量超时（包被丢弃）。因此用"超时占比"作为信号：
    - 超时占比低 → 网络通畅，可尝试加速（不超过 max_rate）
    - 超时占比高 → 疑似限流，自动降速
    - 连续多窗口高 → 疑似封禁，触发 pause 事件

    事件通过回调上报（可用来暂停/停止/记录日志）。
    """

    def __init__(self, profile: ScanProfile,
                 window_size: int = 100,
                 event_cb=None):
        self.profile = profile
        self.window_size = window_size
        self.event_cb = event_cb or (lambda evt: None)
        # 固定容量窗口：自动淘汰最旧结果，防止长时间扫描内存无限增长
        self._results = deque(maxlen=window_size)
        self._current_rate = profile.rate
        self._consecutive_bad_windows = 0
        self.events = []            # 检测到的事件记录

    @property
    def rate(self) -> int:
        """当前建议速率"""
        return self._current_rate

    def record(self, kind: str):
        """记录一次连接结果（timeout/refused/error/open）"""
        self._results.append(kind)
        if len(self._results) < self.window_size:
            return
        # 窗口满：评估一次（deque 自动保持最近 window_size 个）
        timeouts = self._results.count("timeout")
        ratio = timeouts / len(self._results)
        # refused 是正常关闭，不计入异常
        if ratio >= 0.8:
            self._consecutive_bad_windows += 1
            new_rate = max(int(self._current_rate * 0.3), 1)
            if new_rate < self._current_rate:
                self._add_event("slowdown",
                                f"超时占比 {ratio:.0%}，疑似限流，速率 {self._current_rate}→{new_rate}")
                self._current_rate = new_rate
            if self._consecutive_bad_windows >= 3:
                self._add_event("ban_suspect",
                                f"连续 {self._consecutive_bad_windows} 个窗口高超时，疑似出口 IP 被封禁，"
                                f"建议暂停扫描或更换网络出口")
        elif ratio <= 0.2:
            self._consecutive_bad_windows = 0
            max_rate = self.profile.effective_max_rate()
            if self._current_rate < max_rate:
                new_rate = min(int(self._current_rate * 1.5) + 1, max_rate)
                self._add_event("speedup", f"网络通畅，速率 {self._current_rate}→{new_rate}")
                self._current_rate = new_rate
        else:
            self._consecutive_bad_windows = 0

    @property
    def ban_suspected(self) -> bool:
        return self._consecutive_bad_windows >= 3

    def _add_event(self, evt_type: str, msg: str):
        event = {"type": evt_type, "msg": msg, "ts": time.strftime("%H:%M:%S")}
        self.events.append(event)
        # 事件记录有界（portscan.py 用 [-10:] 取最近），防长扫描无界增长
        if len(self.events) > 100:
            del self.events[: len(self.events) - 100]
        self.event_cb(event)


# ---------------------------------------------------------------- 断点续扫

class ScanProgressStore:
    """
    断点续扫：把"剩余任务"持久化到 JSON 文件。
    中断/暂停后可 --resume 继续，避免重扫触发二次封禁。
    """

    def __init__(self, progress_file: Optional[str] = None):
        self.progress_file = progress_file
        self._remaining = None
        self._dirty = False
        self._last_save = time.time()
        self._save_interval = 5.0   # 距上次保存至少间隔秒数
        self.MAX_MATERIALIZE = 500_000  # 新任务物化上限，超限不启用续扫（防大网段 OOM）

    @property
    def enabled(self) -> bool:
        return bool(self.progress_file)

    def begin(self, targets):
        """扫描开始时物化目标并写入剩余列表。返回 (remaining_list, is_resume)"""
        remaining = list(targets)
        resume = False
        if self.progress_file and os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved = data.get("remaining", [])
                if saved:
                    remaining = [tuple(item) for item in saved]
                    resume = True
                    print(f"[*] 续扫模式：读取 {len(remaining)} 个剩余目标 ({self.progress_file})")
            except Exception as e:
                print(f"[!] 读取续扫文件失败: {e}，重新开始")
        # 新任务物化上限保护：超限则本次不启用断点续扫（进度文件也会过大）
        if not resume and len(remaining) > self.MAX_MATERIALIZE:
            print(f"[!] 任务数 {len(remaining)} 超过断点续扫上限 {self.MAX_MATERIALIZE}，"
                  f"本次不启用断点续扫（可分批扫描）")
            self.progress_file = None
            return remaining, False
        if self.progress_file:
            self._remaining = set(remaining)
            self._save()
        return remaining, resume

    def done(self, item):
        """标记一个目标完成（从剩余集合移除，间隔保存）"""
        if self._remaining is None:
            return
        self._remaining.discard(item)
        self._dirty = True
        now = time.time()
        if self._dirty and (now - self._last_save) >= self._save_interval:
            self._save()

    def finish(self):
        """扫描结束/中断时保存最终状态"""
        if self._remaining is not None:
            self._save()

    def _save(self):
        if not self.progress_file:
            return
        try:
            tmp = self.progress_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "remaining_count": len(self._remaining),
                    "remaining": [list(item) for item in self._remaining],
                }, f, ensure_ascii=False)
            os.replace(tmp, self.progress_file)
            self._dirty = False
            self._last_save = time.time()
        except Exception as e:
            print(f"[!] 保存续扫进度失败: {e}")
