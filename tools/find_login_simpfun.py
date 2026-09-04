#!/usr/bin/env python3
"""
对 play.simpfun.cn (103.85.86.51) 全端口扫描，用 notch 身份实际登录测试。
只有成功进入 PLAY 状态的服务器才记录。
"""
import sys
import os
import json
import time
import socket
import asyncio
import concurrent.futures
import threading
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'libs'))

from core.bot import MCBot as MinecraftBot
from core.probe import slp_probe

TARGET_IP = "103.85.86.51"
PORTS = list(range(1, 65536))
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "simpfun_loginable.json")
STATS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "simpfun_scan_stats.json")
LOG_FILE = "/tmp/simpfun_login_scan.log"

# 已知常见 MC 端口优先扫描
MC_PORTS = [25565, 25566, 25567, 25568, 25569, 25570, 25571, 25572, 25573, 25574, 25575,
            25510, 25511, 25512, 25513, 25514, 25515, 25516, 25517, 25518, 25519, 25520,
            25521, 25522, 25523, 25524, 25525, 25530, 25540, 25550, 25555, 25580, 25590, 25595,
            19132, 19133, 19134]

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def check_port(port):
    """检查端口是否开放"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        result = s.connect_ex((TARGET_IP, port))
        s.close()
        return result == 0
    except:
        return False

def slp_check(port):
    """对端口做 SLP 探测，返回服务器信息或 None"""
    try:
        info = slp_probe(TARGET_IP, port, timeout=3.0)
        if info and info.get("version"):
            info["_port"] = port
            return info
    except:
        pass
    return None

def try_login(port, protocol=None, slp_info=None):
    """用 notch 身份尝试登录，返回 (success, info_dict)"""
    bot = MinecraftBot(TARGET_IP, port, username="Notch", timeout=10.0)
    if protocol:
        bot.protocol_version = protocol
    try:
        ok = bot.connect()
        if ok:
            # 成功进入 PLAY 状态
            info = {
                "ip": TARGET_IP,
                "port": port,
                "username": "Notch",
                "protocol": bot.protocol_version,
                "auth_mode": getattr(bot, "auth_mode", "offline"),
                "version": (slp_info or {}).get("version", ""),
                "motd": (slp_info or {}).get("motd", ""),
                "players_online": (slp_info or {}).get("players_online", 0),
                "players_max": (slp_info or {}).get("players_max", 0),
                "login_time": datetime.now().isoformat(),
            }
            return True, info
    except Exception as e:
        err = str(e)[:80]
        return False, {"port": port, "error": err}
    finally:
        try:
            bot.close()
        except Exception:
            pass
    return False, {"port": port, "error": "unknown"}

def save_results(results):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def main():
    log(f"=== 开始扫描 {TARGET_IP} 全端口 ===")
    
    # 阶段1: 全端口扫描
    log("阶段1: 全端口扫描 (1-65535)...")
    open_ports = []
    
    # 先扫常见 MC 端口
    log("先扫常见 MC 端口...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(check_port, p): p for p in MC_PORTS}
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            if fut.result():
                open_ports.append(p)
                log(f"  开放(常见): {p}")
    
    # 再扫剩余端口
    remaining = [p for p in PORTS if p not in MC_PORTS]
    log(f"扫剩余 {len(remaining)} 个端口 (500并发)...")
    
    batch_size = 2000
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i+batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=500) as executor:
            futures = {executor.submit(check_port, p): p for p in batch}
            for fut in concurrent.futures.as_completed(futures):
                p = futures[fut]
                if fut.result():
                    open_ports.append(p)
        progress = min(i + batch_size, len(remaining))
        log(f"  端口扫描进度: {progress}/{len(remaining)}, 已发现 {len(open_ports)} 开放端口")
    
    open_ports.sort()
    log(f"端口扫描完成: {len(open_ports)} 个开放端口")
    
    # 阶段2: SLP 探测
    log(f"阶段2: 对 {len(open_ports)} 个开放端口做 SLP 探测...")
    mc_servers = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(slp_check, p): p for p in open_ports}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            result = fut.result()
            if result:
                mc_servers.append(result)
            if done % 100 == 0:
                log(f"  SLP进度: {done}/{len(open_ports)}, 发现 {len(mc_servers)} 个MC服")
    
    log(f"SLP探测完成: {len(mc_servers)} 个 MC 服务器")
    
    # 保存 SLP 结果
    slp_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "simpfun_mc_servers.json")
    with open(slp_file, "w") as f:
        json.dump(mc_servers, f, indent=2, ensure_ascii=False)
    log(f"SLP结果已保存到 {slp_file}")
    
    # 阶段3: 用 notch 并发登录测试
    log(f"阶段3: 对 {len(mc_servers)} 个 MC 服用 notch 身份并发登录测试 (20并发)...")
    loginable = []
    failed = 0
    tested = 0
    lock = threading.Lock()
    
    def login_worker(srv):
        nonlocal failed, tested
        port = srv["_port"]
        proto = srv.get("proto")
        ver = srv.get("version", "")
        motd = srv.get("motd", "")[:40]
        ok, info = try_login(port, protocol=proto, slp_info=srv)
        with lock:
            tested += 1
            if ok:
                loginable.append(info)
                save_results(loginable)
                log(f"  [{tested}/{len(mc_servers)}] ✅ 端口 {port} 登录成功! {ver} {info.get('players_online',0)}/{info.get('players_max',0)}人 | {motd}")
            else:
                failed += 1
                if tested % 50 == 0 or ok:
                    err = info.get("error", "")[:40]
                    log(f"  [{tested}/{len(mc_servers)}] 进度: 可登录{len(loginable)} 失败{failed} | 最近: {port} {err}")
            stats = {
                "total_ports_scanned": 65535,
                "open_ports": len(open_ports),
                "mc_servers_found": len(mc_servers),
                "login_tested": tested,
                "loginable": len(loginable),
                "failed": failed,
                "last_update": datetime.now().isoformat(),
            }
            save_stats(stats)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(login_worker, srv) for srv in mc_servers]
        concurrent.futures.wait(futures)
    
    log(f"=== 扫描完成 ===")
    log(f"开放端口: {len(open_ports)}")
    log(f"MC服务器: {len(mc_servers)}")
    log(f"可登录: {len(loginable)}")
    for s in loginable:
        log(f"  ✅ {s['ip']}:{s['port']} | {s['version']} | {s['players_online']}/{s['players_max']} | {s['motd'][:50]}")

if __name__ == "__main__":
    main()
