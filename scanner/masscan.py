# -*- coding: utf-8 -*-
"""
masscan 集成：自动检测、调用、结果导入。
有 masscan 就用（快10倍），没有回退 Python 端口扫描。
"""
import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional


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


def run_masscan(targets: str, ports: str = "25565", rate: int = 1000,
                exclude_file: Optional[str] = None, output_file: Optional[str] = None) -> str:
    """
    运行 masscan 扫描，输出 NDJSON 格式结果文件路径。
    targets: CIDR 网段，如 "0.0.0.0/0" 或 "1.2.3.0/24,5.6.7.0/24"
    ports: 端口，如 "25565" 或 "25565-25575"
    rate: 每秒包数
    """
    if not has_masscan():
        raise RuntimeError("masscan 未安装，请先安装: sudo apt install masscan")

    if output_file is None:
        fd, output_file = tempfile.mkstemp(suffix=".ndjson", prefix="masscan_")
        os.close(fd)

    cmd = [
        "masscan",
        "-p", ports,
        "--rate", str(rate),
        "-oJ", output_file,
        "--wait", "3",
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
        cmd.insert(1, targets)
    if exclude_file and os.path.exists(exclude_file):
        cmd.extend(["--excludefile", exclude_file])

    print(f"[*] 运行 masscan: {' '.join(cmd)}")
    print(f"[*] 按 Ctrl+C 停止，结果会保存到 {output_file}")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[!] masscan 退出码 {e.returncode}（可能被中断），已保存部分结果")
    except KeyboardInterrupt:
        print("\n[!] 已中断，已保存部分结果")

    return output_file


def parse_masscan_json(filepath: str) -> list:
    """
    解析 masscan 的 JSON 输出文件，返回 [(ip, port, banner), ...] 列表。
    支持 masscan 的 -oJ 格式（JSON 数组）和 NDJSON 格式。
    流式逐行读取，避免大文件整读内存。
    """
    results = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if not first_line:
                return results
            # 判断格式：以 '[' 开头是 JSON 数组，否则是 NDJSON
            is_json_array = first_line.startswith('[')
            lines_to_process = [first_line] if not is_json_array else []

            def _parse_item(line):
                line = line.strip().rstrip(',')
                if not line or line in ('[', ']') or line.startswith('#'):
                    return
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    return
                ip = item.get("ip")
                ports = item.get("ports", [])
                for p in ports:
                    port = p.get("port")
                    banner = p.get("banner", {}).get("service", {}).get("banner", "")
                    if ip and port:
                        results.append((ip, port, banner))

            # 处理第一行（NDJSON格式）
            for line in lines_to_process:
                _parse_item(line)
            # 流式逐行处理剩余内容
            for line in f:
                _parse_item(line)
    except FileNotFoundError:
        print(f"[!] 文件不存在: {filepath}")
    return results
