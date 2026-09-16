# -*- coding: utf-8 -*-
"""
批量测试雨云38个能进去的服
每个进去发消息+监控，汇总结果
"""
import sys, time, json
from datetime import datetime
from collections import deque
sys.path.insert(0, '.')
from core.bot import MCBot

IP = '218.93.206.192'
PORTS = [10113,10457,10704,11113,11581,12754,12851,14317,14760,14829,17155,19973,20662,21081,23337,24222,28513,30350,30925,31092,31279,32693,34330,44844,47140,47701,48815,50222,50946,52713,53577,54375,57057,57638,58254,58519,59720,59818]

results = []
all_logs = []

for i, port in enumerate(PORTS, 1):
    print(f"\n{'='*50}")
    print(f"[{i}/{len(PORTS)}] 测试 {IP}:{port}")
    chat_log = deque(maxlen=100)
    entry = {"port": port, "ok": False, "msgs_sent": 0, "msgs_recv": 0, "players": []}

    try:
        bot = MCBot(host=IP, port=port, username=f'Tester_{i%99:02d}', timeout=8)

        def on_chat(sender, text):
            ts = datetime.now().strftime('%H:%M:%S')
            chat_log.append((ts, sender, text))
            if sender != '系统' and '加入' not in text and '离开' not in text:
                print(f"  [聊天] {sender}: {text[:50]}")

        bot.chat_callback = on_chat
        bot.connect()
        time.sleep(1.5)

        if bot.state != 'play':
            print(f"  连接失败 state={bot.state}")
            bot.close()
            results.append(entry)
            continue

        entry["ok"] = True
        print(f"  已进入")

        # AuthMe
        try:
            bot.authme_login('Test123456', auto_register=True)
            time.sleep(1.5)
        except:
            pass

        # 发消息
        msgs = ['有人吗', '这服怎么样', 'hello']
        sent = 0
        for m in msgs:
            try:
                bot.send_chat(m)
                sent += 1
                time.sleep(1)
            except:
                break
        entry["msgs_sent"] = sent
        print(f"  发送了 {sent} 条消息")

        # 监控8秒
        time.sleep(8)

        # 收集玩家聊天（非系统）
        player_msgs = [(t, s, txt) for t, s, txt in chat_log if s != '系统']
        entry["msgs_recv"] = len(player_msgs)
        entry["players"] = list(set(s for t, s, txt in player_msgs))

        bot.close()
        print(f"  收到玩家消息 {len(player_msgs)} 条, 玩家: {entry['players']}")

        # 保存日志
        for t, s, txt in chat_log:
            all_logs.append((port, t, s, txt))

    except Exception as e:
        print(f"  错误: {str(e)[:60]}")

    results.append(entry)
    time.sleep(1)

# 汇总
print("\n" + "=" * 60)
print("汇总结果")
print("=" * 60)
ok_ports = [r['port'] for r in results if r['ok']]
with_players = [r for r in results if r['players']]
print(f"成功进入: {len(ok_ports)}/{len(PORTS)}")
print(f"有玩家说话: {len(with_players)}")
if with_players:
    print("\n有玩家的服:")
    for r in with_players:
        print(f"  {IP}:{r['port']} - 玩家: {r['players']}")

# 导出
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
with open(f'rainyun_batch_{ts}.txt', 'w', encoding='utf-8') as f:
    f.write(f"雨云批量测试 {IP}\n")
    f.write(f"时间: {datetime.now()}\n")
    f.write(f"成功: {len(ok_ports)}/{len(PORTS)}\n")
    f.write(f"有玩家: {len(with_players)}\n\n")
    for r in results:
        status = 'OK' if r['ok'] else 'FAIL'
        f.write(f"{status} {IP}:{r['port']} 发送{r['msgs_sent']} 收到{r['msgs_recv']} 玩家:{r['players']}\n")
    f.write("\n=== 聊天记录 ===\n")
    for port, t, s, txt in all_logs:
        f.write(f"[{port}][{t}] {s}: {txt}\n")

print(f"\n已导出: rainyun_batch_{ts}.txt")
print(f"\n能进去的端口: {','.join(str(p) for p in ok_ports)}")
