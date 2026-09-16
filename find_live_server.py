# -*- coding: utf-8 -*-
"""
持续扫描找有人的、能进去的、有真人的MC服务器
找到就停
"""
import sys, time, socket, concurrent.futures, asyncio, random
from datetime import datetime
sys.path.insert(0, '.')
from scanner.async_probe import async_slp_probe
from core.bot import MCBot

# 候选IP段（按优先级）
IP_RANGES = [
    # 数据库里有人的段
    ('103.85.86.0/24', 'db_known'),
    ('103.85.85.0/24', 'db_known'),
    ('103.85.84.0/24', 'db_known'),
    # 新扫的托管IP
    ('218.93.206.192/32', 'rainyun'),
    ('115.191.74.209/32', 'kuaidian'),
    ('8.153.89.37/32', 'aliyun'),
    ('219.144.85.122/32', 'hellotree'),
    # 随机段
    ('43.248.116.0/24', 'random'),
    ('43.248.188.0/24', 'random'),
    ('101.43.39.0/24', 'random'),
]

MC_PORTS = [25565, 25566, 25570, 25575, 25585, 25595, 25600, 25610, 25620, 19132, 19133]

def cidr_to_ips(cidr):
    ip, mask = cidr.split('/')
    mask = int(mask)
    parts = list(map(int, ip.split('.')))
    base = (parts[0]<<24) | (parts[1]<<16) | (parts[2]<<8) | parts[3]
    count = 2**(32-mask)
    return [f'{(base+i)>>24&0xff}.{(base+i)>>16&0xff}.{(base+i)>>8&0xff}.{base+i&0xff}' for i in range(count)]

def scan_port(ip, port, timeout=1.5):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        r = s.connect_ex((ip, port))
        s.close()
        return r == 0
    except:
        return False

async def slp_probe(ip, port):
    try:
        return await async_slp_probe(ip, port, timeout=3)
    except:
        return None

def test_login(ip, port):
    """测试能否进去，返回(bot, 玩家列表)或None"""
    try:
        bot = MCBot(host=ip, port=port, username=f'Finder_{random.randint(1000,9999)}', timeout=8)
        bot.connect()
        time.sleep(2)
        if bot.state != 'play':
            bot.close()
            return None, []
        # AuthMe
        try:
            bot.authme_login('Finder123456', auto_register=True)
            time.sleep(1.5)
        except:
            pass
        # 获取tab列表（玩家）
        players = list(bot.players.keys()) if hasattr(bot, 'players') and bot.players else []
        return bot, players
    except Exception as e:
        return None, []

def is_real_player(name):
    """判断是否真人（排除bot/系统名）"""
    fake_names = ['TestPlayer', 'AIBot', 'SecurityBot', 'Finder', 'Tester_', 'Bot', 'NPC', 'Citizens']
    for f in fake_names:
        if f.lower() in name.lower():
            return False
    # 太短或纯数字可能是假人
    if len(name) < 3:
        return False
    return True

print(f'[{datetime.now().strftime("%H:%M:%S")}] 开始持续扫描，找到有人能进的真人服就停...')
print(f'扫描范围: {len(IP_RANGES)} 个IP段')

found = False
for cidr, tag in IP_RANGES:
    if found:
        break
    ips = cidr_to_ips(cidr)
    print(f'\n[{datetime.now().strftime("%H:%M:%S")}] 扫描段 {cidr} ({tag}, {len(ips)}个IP)...')

    # 端口扫描
    open_targets = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=300) as ex:
        futures = []
        for ip in ips:
            for port in MC_PORTS:
                futures.append(ex.submit(scan_port, ip, port))
        for i, fut in enumerate(futures):
            if fut.result():
                idx = i
                ip_idx = idx // len(MC_PORTS)
                port_idx = idx % len(MC_PORTS)
                open_targets.append((ips[ip_idx], MC_PORTS[port_idx]))
    print(f'  开放端口: {len(open_targets)} 个')

    if not open_targets:
        continue

    # SLP探测
    print(f'  SLP探测中...')
    async def probe_all():
        sem = asyncio.Semaphore(30)
        async def probe(ip, port):
            async with sem:
                return await slp_probe(ip, port)
        tasks = [probe(ip, p) for ip, p in open_targets]
        results = await asyncio.gather(*tasks)
        return [(open_targets[i][0], open_targets[i][1], r) for i, r in enumerate(results) if r and r.get('version')]

    mc_servers = asyncio.run(probe_all())
    with_players = [(ip, port, info) for ip, port, info in mc_servers if info.get('players_online', 0) > 0]
    print(f'  MC服: {len(mc_servers)} 个, 有人: {len(with_players)} 个')

    # 按人数排序，逐个测试登录
    for ip, port, info in sorted(with_players, key=lambda x: x[2].get('players_online', 0), reverse=True):
        pcount = info.get('players_online', 0)
        print(f'  测试 {ip}:{port} ({pcount}人) {info.get("version","")}...')
        bot, players = test_login(ip, port)
        if bot is None:
            print(f'    进不去')
            continue
        print(f'    进去了! Tab列表玩家: {players}')
        real_players = [p for p in players if is_real_player(p)]
        if real_players:
            print(f'\n{"="*60}')
            print(f'找到目标! {ip}:{port}')
            print(f'版本: {info.get("version","")}')
            print(f'在线: {pcount}人')
            print(f'MOTD: {info.get("motd","")[:60]}')
            print(f'真人玩家: {real_players}')
            print(f'{"="*60}')
            # 发消息测试
            try:
                bot.send_chat('有人吗')
                time.sleep(3)
                bot.send_chat('大家好')
                time.sleep(3)
            except:
                pass
            bot.close()
            found = True
            break
        else:
            print(f'    没有真人（可能是假人/空服）')
            bot.close()
        time.sleep(1)

if not found:
    print(f'\n[{datetime.now().strftime("%H:%M:%S")}] 所有预设段扫完，没找到符合条件的')
    print('需要扩大范围继续扫')
