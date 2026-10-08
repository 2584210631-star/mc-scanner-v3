# -*- coding: utf-8 -*-
"""
masscan 集成：自动检测、调用、结果导入。
有 masscan 就用（快10倍），没有回退 Python 端口扫描。
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional

# run_masscan 自建的临时 NDJSON 输出：调用方需要立即读取返回路径，
# 所以不能当场删除，改为进程退出时统一清理，避免临时文件无限堆积。
_TEMP_OUTPUTS = []

# targets 允许的字符：IPv4/IPv6/CIDR/范围 + 主机名，逗号已在拆分时处理。
# targets 会被插到 argv[1]，"--rate=100000" 这类以 - 开头或带 = 的串会被 masscan 当选项解析。
_TARGET_RE = re.compile(r'^[0-9A-Za-z_.:\-\[\]/]+$')
_PORT_RE = re.compile(r'^[0-9,\-]+$')


def _cleanup_temp_outputs():
    for path in list(_TEMP_OUTPUTS):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        try:
            _TEMP_OUTPUTS.remove(path)
        except ValueError:
            pass


atexit.register(_cleanup_temp_outputs)


def _validate_targets(targets: str):
    """校验 targets 串，拒绝会被 masscan 当作选项的参数注入"""
    if not targets or not targets.strip():
        raise ValueError("masscan 目标为空")
    for token in targets.split(','):
        token = token.strip()
        if not token:
            continue
        if token.startswith('-') or not _TARGET_RE.match(token):
            raise ValueError(f"非法的 masscan 目标: {token!r}")


def _validate_ports(ports: str):
    """校验端口串（只允许数字、逗号和范围连接符）"""
    if not ports or not _PORT_RE.match(ports.strip()):
        raise ValueError(f"非法的 masscan 端口串: {ports!r}")


def _terminate(proc):
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:
        pass


def _run_masscan_process(cmd, timeout: Optional[float] = None, stop_event=None) -> Optional[int]:
    """运行 masscan 子进程，返回退出码；被停止/超时/中断时返回 None。

    旧实现用 subprocess.run(cmd, check=True)：没有 timeout、没有停止通道，
    而且 Ctrl+C 只打断父进程的 wait，masscan 子进程会继续在后台扫描。
    """
    proc = subprocess.Popen(cmd)
    deadline = (time.monotonic() + timeout) if timeout and timeout > 0 else None
    try:
        while True:
            try:
                proc.wait(timeout=1.0)
                return proc.returncode
            except subprocess.TimeoutExpired:
                if stop_event is not None and stop_event.is_set():
                    print("[!] 收到停止信号，终止 masscan")
                    _terminate(proc)
                    return None
                if deadline is not None and time.monotonic() >= deadline:
                    print(f"[!] masscan 运行超过 {timeout:.0f}s，已终止")
                    _terminate(proc)
                    return None
    except KeyboardInterrupt:
        print("\n[!] 已中断，正在终止 masscan...")
        _terminate(proc)
        return None


def has_masscan() -> bool:
    """检测系统是否安装了 masscan"""
    return shutil.which("masscan") is not None


def get_masscan_version() -> Optional[str]:
    """获取 masscan 版本"""
    try:
        result = subprocess.run(["masscan", "--version"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or result.stderr.strip()
    except Exception:
        return None


def run_masscan(targets: str, ports: str = "25565", rate: int = None,
                exclude_file: Optional[str] = None, output_file: Optional[str] = None,
                mode: str = None, timeout: Optional[float] = None,
                stop_event=None) -> str:
    """
    运行 masscan 扫描，输出 NDJSON 格式结果文件路径。
    targets: CIDR 网段，如 "0.0.0.0/0" 或 "1.2.3.0/24,5.6.7.0/24"
    ports: 端口，如 "25565" 或 "25565-25575"
    rate: 每秒包数（None 时按 mode 取默认）
    mode: safe / balanced / aggressive（None=balanced）
        - safe: 默认 100 pps，适合公网全端口，降低触发检测概率
        - balanced: 默认 1000 pps（v3 现状）
        - aggressive: 默认 5000 pps，仅内网/信任网络
    timeout: 子进程最长运行秒数（None=不限，仅靠 stop_event/中断终止）
    stop_event: threading.Event，置位后终止 masscan
    """
    from scanner.safe import get_profile
    profile = get_profile(mode)
    _validate_targets(targets)
    _validate_ports(ports)
    if rate is None:
        rate = {"safe": 100, "balanced": 1000, "aggressive": 5000}.get(profile.mode, 1000)
    # aggressive 模式在函数内不强制，但保持安全提示
    if profile.mode == "safe":
        print(f"[!] safe 模式：masscan 限速 {rate} pps，全端口扫描请配合 --wait 等待收尾")
    if rate > 1000:
        print(f"[!] 警告：masscan 速率 {rate} pps 较高，公网扫描极易触发目标限流/封禁，"
              f"建议使用 --mode safe（100 pps）")

    if not has_masscan():
        raise RuntimeError("masscan 未安装，请先安装: sudo apt install masscan")

    if output_file is None:
        fd, output_file = tempfile.mkstemp(suffix=".ndjson", prefix="masscan_")
        os.close(fd)
        _TEMP_OUTPUTS.append(output_file)

    target_file = None
    try:
        cmd = [
            "masscan",
            "-p", ports,
            "--rate", str(rate),
            "-oJ", output_file,
            "--wait", "5" if profile.mode == "safe" else "3",
        ]
        # Windows命令行长度限制8191字符，目标列表过长时用-iL文件传入
        if len(targets) > 500 or "," in targets:
            fd, target_file = tempfile.mkstemp(suffix=".txt", prefix="masscan_targets_")
            with os.fdopen(fd, "w") as f:
                # masscan -iL 支持每行一个CIDR或IP
                for t in targets.split(","):
                    f.write(t.strip() + "\n")
            cmd.extend(["-iL", target_file])
            print(f"[*] 目标列表过长({len(targets)}字符)，使用临时文件 {target_file}")
        else:
            # targets 已通过白名单校验，不会被 masscan 当成选项
            cmd.insert(1, targets)
        if exclude_file and os.path.exists(exclude_file):
            cmd.extend(["--excludefile", exclude_file])

        print(f"[*] 运行 masscan: {' '.join(cmd)}")
        print(f"[*] 按 Ctrl+C 停止，结果会保存到 {output_file}")

        rc = _run_masscan_process(cmd, timeout=timeout, stop_event=stop_event)
        if rc not in (0, None):
            print(f"[!] masscan 退出码 {rc}（可能被中断）")
        if not os.path.exists(output_file):
            print(f"[!] masscan 未生成结果文件: {output_file}")
    finally:
        # -iL 临时目标文件只在本次调用内使用，必须立即清理
        if target_file:
            try:
                os.remove(target_file)
            except OSError:
                pass

    return output_file


def _emit_records(item):
    """把一条 masscan 记录展开成 (ip, port, banner)"""
    if not isinstance(item, dict):
        return
    ip = item.get("ip")
    ports = item.get("ports", [])
    if not isinstance(ports, list):
        return
    for p in ports:
        if not isinstance(p, dict):
            continue
        port = p.get("port")
        # masscan -oJ 的 schema 是 ports[].service.banner；
        # 旧实现读 ports[].banner.service.banner（不存在的路径），banner 恒为空。
        service = p.get("service")
        if not isinstance(service, dict):
            legacy = p.get("banner")
            service = legacy.get("service", {}) if isinstance(legacy, dict) else {}
        banner = service.get("banner", "") if isinstance(service, dict) else ""
        if not isinstance(banner, str):
            banner = str(banner)   # banner 可能是对象，避免下游按字符串处理时报错
        if ip and port:
            yield (ip, port, banner)


def parse_masscan_json(filepath: str):
    """
    解析 masscan 的 JSON 输出文件，返回 (ip, port, banner) 生成器。
    支持 masscan 的 -oJ 格式（JSON 数组）和 NDJSON 格式。

    用 JSONDecoder.raw_decode 增量解析：旧实现逐行 json.loads，
    跨行/美化输出的记录会被整条静默丢弃。流式处理，不会全量读入内存。
    """
    decoder = json.JSONDecoder()
    buf = ""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for chunk in f:
                buf += chunk
                while True:
                    s = buf.lstrip(" \t\r\n,")
                    if not s:
                        buf = ""
                        break
                    if s[0] in "[]":
                        # JSON 数组的边界符号，直接跳过
                        buf = s[1:]
                        continue
                    try:
                        item, end = decoder.raw_decode(s)
                    except json.JSONDecodeError:
                        # 数据还不完整，等下一行；缓冲异常膨胀说明是坏数据，丢弃防内存泄漏
                        if len(buf) > 4 * 1024 * 1024:
                            print("[!] masscan JSON 解析缓冲过大，丢弃异常数据")
                            buf = ""
                        else:
                            buf = s
                        break
                    buf = s[end:]
                    yield from _emit_records(item)
    except FileNotFoundError:
        print(f"[!] 文件不存在: {filepath}")
