#!/usr/bin/env python3
"""50个Herobrine轮番警告13534"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libs'))
from core.bot import MCBot
from core.probe import slp_probe

HOST, PORT = '136.243.0.33', 25565
COUNT = 50

WARN_MSG = "【安全警告】本服务器存在安全风险，建议管理员开启白名单或正版验证，防止未授权访问。"

# 探测协议
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
        bot.send_chat(WARN_MSG)
        time.sleep(1)
        bot.close()
        success += 1
        print(f'[{i}/{COUNT}] {name} 警告已发送', flush=True)
    except Exception as e:
        print(f'[{i}/{COUNT}] {name} 失败: {str(e)[:60]}', flush=True)
        time.sleep(3)  # 失败后多等一会
    time.sleep(2.5)

print(f'[完成] 成功发送 {success}/{COUNT} 次警告', flush=True)
