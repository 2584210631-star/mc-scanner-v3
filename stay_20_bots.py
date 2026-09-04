#!/usr/bin/env python3
"""20个bot挂36534，保持在线"""
import sys, os, time, random, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))
from core.bot import MCBot
from core.probe import slp_probe

HOST, PORT = '103.85.86.51', 36534
COUNT = 20

# 生成20个用户名
names = [f'Player_{i:02d}' for i in range(1, COUNT + 1)]

# 探测协议
info = slp_probe(HOST, PORT, timeout=5)
proto = info.get('protocol', 767) if info else 767
print(f'[启动] 协议={proto}, 目标={HOST}:{PORT}', flush=True)

bots = []
lock = threading.Lock()

def connect_bot(name, index):
    for attempt in range(3):
        try:
            bot = MCBot(HOST, PORT, protocol_version=proto, username=name, timeout=8)
            bot.connect()
            with lock:
                bots.append((name, bot))
            print(f'[{index+1}/{COUNT}] {name} 已连接', flush=True)
            return True
        except Exception as e:
            print(f'[{index+1}/{COUNT}] {name} 连接失败(尝试{attempt+1}): {e}', flush=True)
            time.sleep(2)
    return False

# 逐个连接，间隔0.5秒避免同时连接被踢
threads = []
for i, name in enumerate(names):
    t = threading.Thread(target=connect_bot, args=(name, i))
    t.start()
    threads.append(t)
    time.sleep(0.5)

for t in threads:
    t.join()

connected = len(bots)
print(f'[完成] 成功连接 {connected}/{COUNT} 个bot', flush=True)

# 保持运行，定期检查连接
try:
    while True:
        time.sleep(60)
        # 检查存活
        alive = 0
        with lock:
            for name, bot in bots:
                if bot.conn and bot.conn.sock:
                    try:
                        bot.conn.sock.getpeername()
                        alive += 1
                    except:
                        pass
        print(f'[心跳] 存活 {alive}/{connected}', flush=True)
except KeyboardInterrupt:
    print('[停止] 正在断开...', flush=True)
    with lock:
        for name, bot in bots:
            try:
                bot.close()
            except:
                pass
    print('[停止] 完成', flush=True)
