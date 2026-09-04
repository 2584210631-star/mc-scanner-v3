#!/usr/bin/env python3
"""找高密度MC托管IP：随机扫25565→发现MC服后深挖10000-40000端口→统计MC服数量"""
import sys, os, random, socket, time, json, concurrent.futures
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'libs'))
from core.probe import slp_probe

RESULT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hosting_ips.json")
LOG_FILE = "/tmp/hosting_scan.log"

def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def random_ip():
    while True:
        ip = f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
        # 排除私有/保留地址
        first = int(ip.split('.')[0])
        if first in (10, 127, 169, 172, 192, 0, 255, 224, 240):
            continue
        return ip

def check_25565(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        r = s.connect_ex((ip, 25565))
        s.close()
        return r == 0
    except:
        return False

def deep_scan(ip):
    """对IP深挖10000-40000端口，统计MC服数量"""
    open_ports = []
    ports = list(range(10000, 30001))
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as ex:
        futures = {ex.submit(lambda p: (lambda s: (s.settimeout(0.8), s.connect_ex((ip,p)), s.close())[1])(socket.socket()), p): p for p in ports}
        for fut in concurrent.futures.as_completed(futures):
            if fut.result() == 0:
                open_ports.append(futures[fut])
    
    mc_count = 0
    for p in open_ports:
        try:
            info = slp_probe(ip, p, timeout=2)
            if info and info.get("version"):
                mc_count += 1
        except:
            pass
    return len(open_ports), mc_count

def main():
    log("=== 开始寻找高密度MC托管IP ===")
    results = []
    
    # 先扫5000个随机IP的25565
    log("阶段1: 扫5000个随机IP的25565...")
    mc_ips = []
    batch = 500
    for i in range(0, 1000, batch):
        ips = [random_ip() for _ in range(batch)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=200) as ex:
            futures = {ex.submit(check_25565, ip): ip for ip in ips}
            for fut in concurrent.futures.as_completed(futures):
                if fut.result():
                    mc_ips.append(futures[fut])
        log(f"  已扫 {i+batch}/5000, 发现 {len(mc_ips)} 个25565开放IP")
    
    log(f"阶段1完成: {len(mc_ips)} 个IP的25565开放")
    
    # 对每个MC IP深挖
    log(f"阶段2: 对 {len(mc_ips)} 个IP深挖10000-40000端口...")
    for idx, ip in enumerate(mc_ips):
        try:
            open_count, mc_count = deep_scan(ip)
            if mc_count >= 5:  # 高密度阈值
                results.append({"ip": ip, "open_ports": open_count, "mc_servers": mc_count})
                log(f"  [{idx+1}/{len(mc_ips)}] 🔥 {ip}: {open_count}开放端口, {mc_count}个MC服!")
                with open(RESULT_FILE, "w") as f:
                    json.dump(results, f, indent=2)
            elif mc_count > 0:
                log(f"  [{idx+1}/{len(mc_ips)}] {ip}: {mc_count}个MC服")
        except Exception as e:
            log(f"  [{idx+1}/{len(mc_ips)}] {ip}: 错误 {e}")
    
    log(f"=== 完成，发现 {len(results)} 个高密度托管IP ===")
    for r in sorted(results, key=lambda x: -x["mc_servers"]):
        log(f"  {r['ip']}: {r['mc_servers']}个MC服, {r['open_ports']}开放端口")

if __name__ == "__main__":
    main()
