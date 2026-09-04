#!/usr/bin/env python3
"""15个Him轮番警告13524，每个发5条中文安全警告"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))
from core.bot import MCBot
from core.probe import slp_probe

HOST, PORT = '103.85.86.51', 13524
COUNT = 15

MESSAGES = [
    "【安全警告】本服务器为离线模式，任何人可使用任意用户名登录，无需正版验证",
    "【安全警告】攻击者可冒充管理员或其他玩家身份进行欺诈和破坏",
    "【安全警告】离线模式下无法确认玩家真实身份，账号安全无法保障",
    "【安全警告】建议管理员开启正版验证或白名单，保护服务器和玩家安全",
    "【安全警告】请重视服务器安全，及时采取防护措施，避免遭受损失",
]

info = slp_probe(HOST, PORT, timeout=5)
proto = info.get('protocol', 767) if info else 767
print(f'[启动] {HOST}:{PORT} 协议={proto}', flush=True)

success = 0
for i in range(1, COUNT + 1):
    name = f'Herobrine_{i:02d}'
    try:
        bot = MCBot(HOST, PORT, protocol_version=proto, username=name, timeout=8)
        bot.connect()
        time.sleep(2)
        for msg in MESSAGES:
            bot.send_chat(msg)
            time.sleep(0.8)
        time.sleep(1)
        bot.close()
        success += 1
        print(f'[{i}/{COUNT}] {name} 发送5条警告完成', flush=True)
    except Exception as e:
        print(f'[{i}/{COUNT}] {name} 失败: {str(e)[:60]}', flush=True)
        time.sleep(3)
    time.sleep(2)

print(f'[完成] 成功 {success}/{COUNT}', flush=True)
