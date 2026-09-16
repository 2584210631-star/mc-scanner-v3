# -*- coding: utf-8 -*-
"""
持续扫描 - 国外IP段（时差优势）+ 随机IP
找到有人能进的真人服就停
"""
import sys, time, socket, concurrent.futures, asyncio, random
from datetime import datetime
sys.path.insert(0, '.')
from scanner.async_probe import async_slp_probe
from core.bot import MCBot

# 国外常见MC托管商IP段（美国/欧洲，现在是白天）
FOREIGN_RANGES = [
    '172.65.0.0/16',      # Cloudflare MC (Hypixel等)
    '40.223.0.0/16',      # Azure (DonutSMP等)
    '170.23.0.0/16',      # 美国
    '45.143.19.0/24',     # 欧洲
    '185.255.92.0/24',    # 欧洲
    '51.81.0.0/16',       # OVH
    '142.44.0.0/16',      # OVH
    '192.99.0.0/16',      # OVH
    '5.196.0.0/16',       # OVH
    '108.61.0.0/16',      # 美国
]

MC_PORTS = [25565, 25566, 25570, 25575, 25585, 25595, 25600]

def cidr_to_ips(cidr, limit=256):
    ip, mask = cidr.split('/')
    mask = int(mask)
    parts = list(map(int, ip.split('.')))
    base = (parts[0]<<24) | (parts[1]<<16) | (parts[2]<<8) | parts[3]
    count = min(2**(32-mask), limit)
    # 随机选count个IP
    if 2**(32-mask) > limit:
        offsets = random.sample(range(2**(32-mask)), limit)
    else:
        offsets = range(count)
    return [f'{(base+i)>>24&0xff}.{(base+i)>>16&0xff}.{(base+i)>>8&0xff}.{base+i&0xff}' for i in offsets]

def scan_port(ip, port, timeout=1.2):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        r = s.connect_ex((ip, port))
        s.close()
        return r == 0
    except: return False

def test_login(ip, port):
    try:
        bot = MCBot(host=ip, port=port, username=f'Finder_{random.randint(100,999)}', timeout=8)
        bot.connect()
        time.sleep(2)
        if bot.state != 'play':
            bot.close()
            return None, []
        try:
            bot.authme_login('Finder123456', auto_register=True)
            time.sleep(1.5)
        except: pass
        players = list(bot.players.keys()) if hasattr(bot, 'players') and bot.players else []
        return bot, players
    except:
        return None, []

def is_real(name):
    fakes = ['bot','test','finder','npc','security','citizens','plugin']
    return len(name) >= 3 and not any(f in name.lower() for f in fakes)

print(f'[{datetime.now().strftime("%H:%M:%S")}] 持续扫描国外IP段，找到有人真人服就停')

found = False
round_num = 0
while not found:
    round_num += 1
    print(f'\n--- 第{round_num}轮 ---')

    # 每轮随机选3个段
    ranges = random.sample(FOREIGN_RANGES, min(3, len(FOREIGN_RANGES)))
    all_ips = []
    for cidr in ranges:
        ips = cidr_to_ips(cidr, limit=128)
        all_ips.extend(ips)
    random.shuffle(all_ips)
    all_ips = all_ips[:300]

    print(f'扫描 {len(all_ips)} 个IP x {len(MC_PORTS)} 端口...')

    # 端口扫描
    open_targets = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=400) as ex:
        futures = []
        for ip in all_ips:
            for port in MC_PORTS:
                futures.append(ex.submit(scan_port, ip, port))
        for i, fut in enumerate(futures):
            if fut.result():
                ip_idx = i // len(MC_PORTS)
                port_idx = i % len(MC_PORTS)
                open_targets.append((all_ips[ip_idx], MC_PORTS[port_idx]))
    print(f'  开放: {len(open_targets)}')

    if not open_targets:
        continue

    # SLP
    async def probe_all():
        sem = asyncio.Semaphore(30)
        async def probe(ip, port):
            async with sem:
                try:
                    r = await async_slp_probe(ip, port, timeout=3)
                    if r and r.get('version'): return (ip, port, r)
                except: pass
            return None
        return await asyncio.gather(*[probe(ip,p) for ip,p in open_targets])

    results = asyncio.run(probe_all())
    mc = [r for r in results if r]
    with_p = [(ip,port,info) for ip,port,info in mc if info.get('players_online',0) > 0]
    print(f'  MC服: {len(mc)}, 有人: {len(with_p)}')

    for ip, port, info in sorted(with_p, key=lambda x: x[2].get('players_online',0), reverse=True):
        p = info.get('players_online',0)
        print(f'  测试 {ip}:{port} ({p}人) {info.get("version","")}')
        bot, players = test_login(ip, port)
        if bot is None:
            print(f'    进不去')
            continue
        real = [x for x in players if is_real(x)]
        print(f'    进去了! 玩家: {players[:8]} 真人: {real}')
        if real:
            print(f'\n{"="*60}')
            print(f'找到! {ip}:{port}')
            print(f'版本: {info.get("version","")} | 在线: {p}人')
            print(f'MOTD: {info.get("motd","")[:60]}')
            print(f'真人玩家: {real}')
            print(f'{"="*60}')
            try:
                bot.send_chat('hello')
                time.sleep(3)
            except: pass
            bot.close()
            found = True
            break
        bot.close()
        time.sleep(1)

    if not found:
        print(f'  本轮没找到，继续...')
        time.sleep(2)

print(f'\n[{datetime.now().strftime("%H:%M:%S")}] 完成!')
