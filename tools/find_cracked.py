#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持续公网扫描：找 cracked/offline 服务器
后台运行，结果追加到 cracked_servers.json
"""
import json
import random
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ipaddress import ip_address

sys.path.insert(0, '.')
sys.path.insert(0, './libs')
from core.probe import slp_probe, auth_probe
from core.bot import MCBot

OUTPUT_FILE = "cracked_servers.json"
STATS_FILE = "scan_stats.json"

# 排除私有/保留/特殊地址
def is_public_ip(ip_str):
    try:
        ip = ip_address(ip_str)
        return not (ip.is_private or ip.is_reserved or ip.is_loopback or
                    ip.is_link_local or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        return False

def random_public_ip():
    while True:
        ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
        if is_public_ip(ip):
            return ip

def port_check(ip, port=25565, timeout=1.5):
    """快速端口检测"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception:
        return False

def probe_server(ip, port=25565):
    """SLP + 认证检测"""
    try:
        slp = slp_probe(ip, port, timeout=4)
        if slp.get("state") != "up":
            return None
        proto = slp.get("proto", 0)
        auth = auth_probe(ip, port, proto, timeout=4)
        return {
            "ip": ip, "port": port,
            "version": slp.get("version"),
            "proto": proto,
            "core_type": slp.get("core_type"),
            "players_online": slp.get("online", 0),
            "players_max": slp.get("max", 0),
            "player_list": [p.get("name","") for p in slp.get("sample",[])],
            "motd": slp.get("motd","")[:100],
            "auth": auth.get("state"),
            "auth_detail": auth.get("detail","")[:80],
            "ping_ms": slp.get("ping_ms"),
            "fingerprint": slp.get("fingerprint", {}).get("likely_software"),
        }
    except Exception:
        return None

def load_results():
    try:
        with open(OUTPUT_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_results(results):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"scanned": 0, "open_ports": 0, "mc_servers": 0, "cracked": 0, "start_time": time.time()}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def try_join_as_notch(ip, port, proto=0):
    """用 notch 身份尝试登录，返回 (success, detail)"""
    bot = MCBot(ip, port, username="notch", timeout=8, protocol_version=proto or None)
    try:
        bot.connect()
        # 等3秒看会不会被踢
        time.sleep(3)
        if not bot.conn:
            return False, "登录后被踢"
        # 尝试 AuthMe 注册（随机6位密码）
        import random, string
        password = ''.join(random.choices(string.digits, k=6))
        try:
            bot.authme_login(password, register=False)
            time.sleep(1)
        except Exception:
            pass
        if not bot.conn:
            # 登录失败，试注册
            bot2 = MCBot(ip, port, username="notch", timeout=8, protocol_version=proto or None)
            try:
                bot2.connect()
                time.sleep(2)
                bot2.authme_login(password, register=True)
                time.sleep(2)
                if bot2.conn:
                    bot2.close()
                    return True, f"AuthMe注册成功(密码{password})"
                bot2.close()
            except Exception:
                pass
            return False, "AuthMe登录失败"
        # 再等2秒确认稳定
        time.sleep(2)
        if bot.conn:
            players = list(bot.player_list.values())
            return True, f"直接进入, 在线玩家{players[:5]}"
        return False, "登录后超时被踢"
    except Exception as e:
        return False, str(e)[:60]
    finally:
        try:
            bot.close()
        except Exception:
            pass


def main():
    print(f"持续公网扫描启动，结果保存到 {OUTPUT_FILE}")
    results = load_results()
    known_ips = {r["ip"] for r in results}
    stats = load_stats()

    batch_size = 500  # 每批扫描 IP 数
    port_workers = 200
    probe_workers = 20

    while True:
        # 生成一批随机 IP
        ips = [random_public_ip() for _ in range(batch_size)]
        stats["scanned"] += batch_size

        # 阶段1: 快速端口扫描
        open_ips = []
        with ThreadPoolExecutor(max_workers=port_workers) as pool:
            futures = {pool.submit(port_check, ip): ip for ip in ips}
            for f in as_completed(futures):
                if f.result():
                    open_ips.append(futures[f])
        stats["open_ports"] += len(open_ips)

        # 阶段2: SLP + 认证检测
        if open_ips:
            with ThreadPoolExecutor(max_workers=probe_workers) as pool:
                futures = {pool.submit(probe_server, ip): ip for ip in open_ips}
                for f in as_completed(futures):
                    result = f.result()
                    if result:
                        stats["mc_servers"] += 1
                        if result["auth"] == "cracked" and result["ip"] not in known_ips:
                            # 用 notch 身份实际登录验证
                            join_ok, join_detail = try_join_as_notch(result["ip"], result["port"], result["proto"])
                            result["notch_join"] = join_ok
                            result["notch_detail"] = join_detail
                            if join_ok:
                                results.append(result)
                                known_ips.add(result["ip"])
                                stats["cracked"] += 1
                                print(f"[JOINABLE] {result['ip']}:{result['port']} | {result['version']} | {result['players_online']}/{result['players_max']}人 | notch: {join_detail} | {result['motd'][:40]}")
                            else:
                                print(f"[NO-JOIN] {result['ip']}:{result['port']} | notch进不去: {join_detail}")

        # 定期保存
        save_results(results)
        save_stats(stats)

        elapsed = time.time() - stats["start_time"]
        rate = stats["scanned"] / elapsed if elapsed > 0 else 0
        print(f"[STATS] 已扫{stats['scanned']} IP, 开放{stats['open_ports']}, MC服{stats['mc_servers']}, 离线服{stats['cracked']} | {rate:.0f} IP/s | 已运行{elapsed/60:.0f}分钟")

if __name__ == "__main__":
    main()
