#!/usr/bin/env python3
"""15个bot挂16554，不发消息"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))
from core.bot import MCBot
from core.probe import slp_probe

HOST, PORT = '103.85.86.51', 16554
COUNT = 15

names = [f'Visitor_{i:02d}' for i in range(1, COUNT + 1)]

info = slp_probe(HOST, PORT, timeout=5)
proto = info.get('protocol', 767) if info else 767
print(f'[启动] {HOST}:{PORT} 协议={proto}', flush=True)

bots = []
lock = threading.Lock()

def connect_bot(name, index):
    for attempt in range(2):
        try:
            bot = MCBot(HOST, PORT, protocol_version=proto, username=name, timeout=8)
            bot.connect()
            with lock:
                bots.append((name, bot))
            print(f'[{index+1}/{COUNT}] {name} 已连接', flush=True)
            return True
        except Exception as e:
            print(f'[{index+1}/{COUNT}] {name} 失败(尝试{attempt+1}): {str(e)[:50]}', flush=True)
            time.sleep(3)
    return False

threads = []
for i, name in enumerate(names):
    t = threading.Thread(target=connect_bot, args=(name, i))
    t.start()
    threads.append(t)
    time.sleep(1.0)  # 间隔1秒，避免触发反bot

for t in threads:
    t.join()

connected = len(bots)
print(f'[完成] 成功连接 {connected}/{COUNT}', flush=True)

try:
    while True:
        time.sleep(60)
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
    with lock:
        for name, bot in bots:
            try: bot.close()
            except: pass
    print('[停止]', flush=True)
