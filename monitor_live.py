# -*- coding: utf-8 -*-
"""
持续监控 - 每3分钟重扫所有已知服务器+随机新IP
找到有人能进的真人服就停
"""
import sys, time, socket, concurrent.futures, asyncio, random
from datetime import datetime
sys.path.insert(0, '.')
from scanner.async_probe import async_slp_probe
from core.bot import MCBot

# 所有已知目标 (host, port)
KNOWN = [
    ('103.85.86.51', 16554), ('103.85.86.51', 16963), ('103.85.86.51', 17365),
    ('103.85.86.51', 20674), ('103.85.86.51', 10411), ('103.85.86.51', 18874),
    ('103.85.86.51', 36520), ('103.85.86.51', 21689), ('103.85.86.51', 25390),
    ('103.85.86.51', 20496), ('103.85.86.51', 18717), ('103.85.86.51', 15253),
    ('103.85.86.51', 17367), ('103.85.86.51', 11926), ('103.85.86.51', 17939),
    ('103.85.86.51', 25564), ('101.43.0.218', 25565),
    ('218.93.206.192', 58254), ('218.93.206.192', 28513), ('218.93.206.192', 11581),
    ('hub.enderblade.com', 25565), ('top.extremecraft.net', 25565),
    ('top.twenture.net', 25565), ('pixel-mc.net', 25565),
]
# 雨云全部38个能进的端口
for p in [10113,10457,10704,11113,11581,12754,12851,14317,14760,14829,17155,19973,20662,21081,23337,24222,28513,30350,30925,31092,31279,32693,34330,44844,47140,47701,48815,50222,50946,52713,53577,54375,57057,57638,58254,58519,59720,59818]:
    KNOWN.append(('218.93.206.192', p))

MC_PORTS = [25565, 25566, 25570, 25575, 25585]

def is_real(name):
    fakes = ['bot','test','finder','npc','security','citizens','plugin']
    return len(name) >= 3 and not any(f in name.lower() for f in fakes)

def test_login(host, port):
    try:
        bot = MCBot(host=host, port=port, username=f'Finder_{random.randint(100,999)}', timeout=8)
        bot.connect()
        time.sleep(2.5)
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

print(f'[{datetime.now().strftime("%H:%M:%S")}] 持续监控启动，共{len(KNOWN)}个已知目标，每3分钟一轮')

found = False
round_num = 0
while not found:
    round_num += 1
    print(f'\n=== 第{round_num}轮 {datetime.now().strftime("%H:%M:%S")} ===')

    # SLP探测所有已知
    async def check_known():
        sem = asyncio.Semaphore(30)
        async def probe(host, port):
            async with sem:
                try:
                    r = await async_slp_probe(host, port, timeout=3)
                    if r and r.get('players_online', 0) > 0:
                        return (host, port, r)
                except: pass
            return None
        return await asyncio.gather(*[probe(h,p) for h,p in KNOWN])

    alive = [r for r in asyncio.run(check_known()) if r]
    print(f'  已知服有人: {len(alive)} 个')
    for host, port, info in sorted(alive, key=lambda x: x[2].get('players_online',0), reverse=True):
        p = info.get('players_online',0)
        print(f'  测试 {host}:{port} ({p}人)...')
        bot, players = test_login(host, port)
        if bot is None:
            print(f'    进不去')
            continue
        real = [x for x in players if is_real(x)]
        print(f'    进去了! 玩家({len(players)}): {players[:10]} 真人: {real}')
        if real:
            print(f'\n{"="*60}')
            print(f'找到! {host}:{port}')
            print(f'版本: {info.get("version","")} | 在线: {p}人')
            print(f'MOTD: {info.get("motd","")[:60]}')
            print(f'真人玩家: {real}')
            print(f'{"="*60}')
            try:
                bot.send_chat('有人吗')
                time.sleep(3)
            except: pass
            bot.close()
            found = True
            break
        bot.close()
        time.sleep(1)

    if found:
        break

    # 随机扫50个新IP
    print(f'  随机扫50个新IP...')
    random_ips = [f'{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}' for _ in range(50)]
    def scan(ip, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            r = s.connect_ex((ip, port))
            s.close()
            return r == 0
        except: return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=200) as ex:
        futures = []
        for ip in random_ips:
            for port in MC_PORTS:
                futures.append(ex.submit(scan, ip, port))
        open_targets = []
        for i, fut in enumerate(futures):
            if fut.result():
                open_targets.append((random_ips[i//len(MC_PORTS)], MC_PORTS[i%len(MC_PORTS)]))
    if open_targets:
        print(f'  随机发现 {len(open_targets)} 个开放端口')
        async def probe_random():
            sem = asyncio.Semaphore(20)
            async def probe(ip, port):
                async with sem:
                    try:
                        r = await async_slp_probe(ip, port, timeout=3)
                        if r and r.get('players_online',0) > 0:
                            return (ip, port, r)
                    except: pass
                return None
            return await asyncio.gather(*[probe(ip,p) for ip,p in open_targets])
        rand_alive = [r for r in asyncio.run(probe_random()) if r]
        for ip, port, info in rand_alive:
            p = info.get('players_online',0)
            print(f'  随机发现有人! {ip}:{port} ({p}人)')
            bot, players = test_login(ip, port)
            if bot:
                real = [x for x in players if is_real(x)]
                if real:
                    print(f'\n{"="*60}')
                    print(f'找到! {ip}:{port}')
                    print(f'真人: {real}')
                    print(f'{"="*60}')
                    bot.close()
                    found = True
                    break
                bot.close()
    else:
        print(f'  随机无收获')

    if not found:
        print(f'  本轮没找到，等3分钟...')
        time.sleep(180)

print(f'\n[{datetime.now().strftime("%H:%M:%S")}] 完成!')
