# -*- coding: utf-8 -*-
"""
主动挑衅全服 - 进17365
两个bot进去后主动骂全服，逼真人说话
"""
import sys
import time
import random
import threading
from datetime import datetime
from collections import deque

sys.path.insert(0, '.')
from core.bot import MCBot

SERVER_IP = "103.85.86.51"
SERVER_PORT = 16963

chat_log = deque(maxlen=2000)
chat_lock = threading.Lock()

# 挑衅全服的话
PROVOKE_ALL = [
    "这服务器的人都是菜鸡吗？怎么没人敢说话？",
    "不是吧不是吧，这服务器一个能打的都没有？",
    "笑死，全服都是哑巴吗？出来一个能打的啊",
    "我不是针对谁，我是说在座的各位都是垃圾",
    "有人敢跟我对线吗？不会全服都是怂货吧？",
    "这服务器的人呢？都死了吗？出来说句话啊",
    "不是吧阿sir，这服务器连个敢说话的都没有？",
    "我就站这了，有本事来打我啊，一群菜鸡",
    "笑死，这服务器的人也就会偷偷摸摸的了",
    "有没有活人？出来吱一声啊，全服都是死人？",
    "不是吧不是吧，不会真有人连话都不敢说吧？",
    "我看这服务器也就这样了，一个能打的都没有",
    "出来啊，别躲着了，我知道你们在看",
    "就这？这服务器的人就这水平？话都不敢说？",
    "笑死，全服都是缩头乌龟吗？",
    "有人吗？有人吗？不会全服就我一个活人吧？",
    "不是吧阿sir，这服务器连个敢回嘴的都没有？",
    "我要是你们，我早就退服了，太丢人了",
    "这服务器的人是不是都把智商拿去充QQ会员了？",
    "出来一个能打的，别让我看不起你们",
    "笑死，全服都是哑巴吗？连个屁都不敢放",
    "不是吧不是吧，不会真有人这么怂吧？",
    "我就在这了，有本事来ban我啊，一群废物",
    "这服务器的腐竹呢？出来管管啊，不管我就继续骂了",
    "有人吗有人吗？不会全服都在挂机吧？",
    "不是吧阿sir，这服务器连个活人都没有？",
    "我看这服务器的人也就只会玩泥巴了",
    "出来说话啊，别像个缩头乌龟一样",
    "笑死，全服都是懦夫吗？连话都不敢说",
    "有没有活人？出来跟我对线啊",
]

# 针对特定玩家的挑衅（如果知道名字）
PROVOKE_PLAYER = [
    "{name}，你是不是哑巴了？出来说话啊",
    "{name}，就你这水平也敢玩这个游戏？",
    "{name}，你是不是怕我怕到连话都不敢说了？",
    "笑死，{name}你也配在这服务器待着？",
    "{name}，你是不是觉得自己特别厉害？其实就是个傻逼",
    "不是吧不是吧，{name}你连话都不敢说？",
    "{name}，你妈妈知道你在游戏里这么菜吗？",
    "{name}，出来对线啊，别躲着了",
    "{name}，就你这水平，给我提鞋都不配",
    "{name}，你是不是出生的时候把脑子落产房了？",
]

# 对骂台词
INSULTS = [
    "就你这水平也敢出来说话？笑死爹了",
    "不是吧不是吧，真有人觉得自己很厉害啊？",
    "你这操作我奶奶看了都摇头",
    "你是不是把智商都拿去充QQ会员了？",
    "就这？就这？我还以为多厉害呢",
    "你妈妈知道你在游戏里这么菜吗？",
    "我要是你我早就退服了",
    "你这技术是跟智障学的吗？",
    "不是我说你，你这操作放出去都没人信是人类玩的",
    "你是不是觉得自己特别幽默？其实特别傻逼",
    "笑死，你也配跟我说话？",
    "就你这脑子，建议回炉重造",
    "你是不是出生的时候把脑子落在产房了？",
    "我从来没见过这么菜的人，今天算是开眼了",
    "你玩游戏的样子像极了我家鱼缸里的鱼，只会瞎撞",
    "不是吧阿sir，这都不会？你是怎么活到现在的？",
    "你这智商，建议去医院挂个号看看",
    "我要是你，我都不好意思在这服务器待着",
    "就你这水平，去新手村都被人虐",
    "你是不是对自己有什么误解？觉得自己很强？",
    "笑死，你也配玩这个游戏？",
    "你这操作，我用脚都比你强",
    "不是吧不是吧，不会真有人这么菜吧？",
    "你是不是把脑子当零食吃了？",
    "就你这水平，还敢出来丢人？",
    "我要是你，我早就找个地缝钻进去了",
    "你这技术，菜得我都不忍心看了",
    "你是不是觉得自己特别牛？其实特别傻逼",
    "就这？我还以为多厉害呢，就这水平？",
    "你这操作，是用脚玩的吧？",
]

REBUTTALS = [
    "就这？我还以为你能说出什么花来呢",
    "笑死，你也就这点水平了",
    "不是吧不是吧，就这？",
    "你能不能说点新鲜的？翻来覆去就这几句",
    "就这也配跟我吵？回去再练几年吧",
    "笑死爹了，你这嘴炮水平也不行啊",
    "不是吧阿sir，就这？",
    "你能不能别像个复读机一样？",
    "就这？我还以为多厉害呢",
    "笑死，你这水平也敢出来吵架？",
]


def run_bot(name, stop_event, ready_event, is_leader):
    """运行一个bot"""
    try:
        bot = MCBot(host=SERVER_IP, port=SERVER_PORT, username=name, timeout=15)

        def on_chat(sender, text):
            ts = datetime.now().strftime("%H:%M:%S")
            with chat_lock:
                chat_log.append((ts, sender, text))

        bot.chat_callback = on_chat
        bot.connect()
        time.sleep(2)

        if bot.state != "play":
            print(f"[{name}] 连接失败，状态={bot.state}")
            ready_event.set()
            return

        print(f"[{name}] 已进入服务器")

        try:
            bot.authme_login("Provoke123", auto_register=True)
            time.sleep(2)
        except Exception:
            pass

        ready_event.set()
        time.sleep(3)

        # 开场挑衅
        bot.send_chat(f"大家好，我是{name}，今天来看看这服务器有没有能打的")
        time.sleep(2)

        round_count = 0
        while not stop_event.is_set() and round_count < 40:
            # 70%概率挑衅全服，30%概率对骂
            if random.random() < 0.7:
                msg = random.choice(PROVOKE_ALL)
            else:
                msg = random.choice(INSULTS)
            try:
                bot.send_chat(msg)
                print(f"[{name}] {msg}")
            except Exception as e:
                print(f"[{name}] 发送失败: {e}")
                break
            round_count += 1
            time.sleep(random.uniform(2, 4))

        # 结尾
        try:
            bot.send_chat("行了，这服务器也就这样了，一个能打的都没有，走了走了")
        except Exception:
            pass

        time.sleep(1)
        bot.close()
        print(f"[{name}] 退出，共发了 {round_count} 条")

    except Exception as e:
        print(f"[{name}] 错误: {e}")
        ready_event.set()


def main():
    print("=" * 60)
    print(f"主动挑衅全服 - {SERVER_IP}:{SERVER_PORT}")
    print("=" * 60)

    stop_event = threading.Event()
    ready_a = threading.Event()
    ready_b = threading.Event()

    t_a = threading.Thread(target=run_bot, args=(
        "TrollMaster", stop_event, ready_a, True))
    t_b = threading.Thread(target=run_bot, args=(
        "TrollKing", stop_event, ready_b, False))

    t_a.start()
    t_b.start()

    ready_a.wait(timeout=30)
    ready_b.wait(timeout=30)

    print("\n[系统] 两个挑衅者已就位，开始搞事！\n")

    t_a.join()
    t_b.join()

    print("\n" + "=" * 60)
    print("挑衅结束！")
    print("=" * 60)

    # 导出聊天记录
    if chat_log:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_file = f"provoke_chat_{ts}.txt"
        html_file = f"provoke_chat_{ts}.html"

        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(f"主动挑衅全服聊天记录\n")
            f.write(f"服务器: {SERVER_IP}:{SERVER_PORT}\n")
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"消息数: {len(chat_log)}\n")
            f.write("=" * 50 + "\n\n")
            for t, sender, text in chat_log:
                f.write(f"[{t}] {sender}: {text}\n")
        print(f"\n聊天记录已导出: {txt_file}")

        rows = ""
        for t, sender, text in chat_log:
            if "Troll" in sender:
                color = "#e94560"
            elif sender == "系统":
                color = "#888"
            else:
                color = "#00d992"
            rows += f'<div class="msg"><span class="time">{t}</span><span class="sender" style="color:{color}">{sender}</span><span class="text">{text}</span></div>\n'
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>主动挑衅全服聊天记录</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
.container{{max-width:900px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{color:#e94560;font-size:22px;margin-bottom:10px}}
.header .info{{color:#888;font-size:13px}}.header .info span{{color:#00d992}}
.chat{{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
.msg{{padding:8px 16px;border-bottom:1px solid #1a1a1a;display:flex;gap:12px;font-size:13px}}
.msg:hover{{background:#161616}}
.msg .time{{color:#555;min-width:60px}}.msg .sender{{font-weight:bold;min-width:120px}}.msg .text{{color:#ccc;flex:1;word-break:break-all}}
.footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
</head><body><div class="container">
<div class="header"><h1>主动挑衅全服聊天记录</h1>
<div class="info">服务器: <span>{SERVER_IP}:{SERVER_PORT}</span> | 消息数: <span>{len(chat_log)}</span></div>
</div><div class="chat">{rows}</div>
<div class="footer">Generated by mc-scanner-v3</div>
</div></body></html>"""
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"聊天记录已导出: {html_file}")


if __name__ == "__main__":
    main()
