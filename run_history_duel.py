# -*- coding: utf-8 -*-
"""
历史人物对骂 - 诸葛亮 vs 司马懿
进17365，两个历史名人互喷
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
SERVER_PORT = 36520

# 聊天记录
chat_log = deque(maxlen=2000)
chat_lock = threading.Lock()

# 诸葛亮台词 - 嘲讽司马懿不敢出战、女装、短命
ZHUGE_LIANG = [
    "司马懿，你个缩头乌龟，敢出来一战吗？",
    "仲达啊仲达，你是不是只会守着城池当缩头乌龟？",
    "我送你女装你都不敢穿，你是不是男人？",
    "笑死，我一曲空城计就把你十万大军吓退了，你也配当大都督？",
    "你那点本事，也就会守守城池了，出来打野都不敢",
    "我诸葛亮平生未见如此厚颜无耻之人！",
    "司马懿，你是不是怕我怕到连城门都不敢出了？",
    "就你这水平，给我提鞋都不配，还敢跟我对线？",
    "我火烧上方谷的时候，你是不是吓得尿裤子了？",
    "不是吧不是吧，不会真有人打了一辈子仗只敢守吧？",
    "你那十万大军是摆设吗？出来跟我打啊！",
    "我死了你都赢不了，你说你气不气？",
    "笑死，我一个木雕就能把你吓跑，你也配叫军事家？",
    "仲达，你是不是觉得自己特别能忍？其实就是怂",
    "我六出祁山，你次次都躲着我，你是不是男人？",
    "就你这水平，也配跟我齐名？你也配？",
    "司马懿，你这辈子也就会一个'守'字了吧？",
    "我要是你，我早就投降了，还在这丢人现眼",
    "你那点小聪明，在我眼里就是小儿科",
    "不是吧阿sir，送你女装都不敢穿，你是不是不行？",
    "我诸葛亮鞠躬尽瘁，你司马懿狼顾之相，谁是忠臣一目了然",
    "你是不是觉得自己赢了？我死了蜀汉还在，你死了司马家篡位，你就是个乱臣贼子",
    "笑死，我死了都能把你吓跑，你说你多丢人",
    "就你这水平，也配跟我比？你配吗？配吗？",
    "司马懿，你是不是怕我怕到连做梦都梦到我？",
    "我一个人就能压着你十万大军打，你说你多菜",
    "不是吧不是吧，不会真有人被空城计吓跑吧？",
    "你那点本事，也就欺负欺负曹爽了，跟我比差远了",
    "我要是你，我早就找块豆腐撞死了，还有脸在这待着",
    "仲达啊，你是不是觉得自己特别能忍？其实就是怕死",
    "你这辈子最大的成就就是活得久，其他一无是处",
    "我诸葛亮名垂青史，你司马懿遗臭万年，你说你图啥",
    "就你这水平，给我当徒弟我都嫌丢人",
    "你是不是觉得自己特别聪明？其实就是个老狐狸",
    "笑死，我死了你都不敢追，你是有多怕我",
    "司马懿，你是不是连我死了都要确认三遍？你是有多怂",
    "我要是你，我都不好意思说自己是军事家",
    "就你这水平，也配跟我斗？你配吗？",
    "你那点阴谋诡计，在我眼里就是个笑话",
    "不是吧不是吧，不会真有人打了一辈子只敢守吧？",
]

# 司马懿台词 - 嘲讽诸葛亮短命、累死、没赢、穷兵黩武
SIMA_YI = [
    "诸葛亮，你六出祁山次次失败，你图啥呢？",
    "笑死，你累死在五丈原了，我还活着，谁赢了？",
    "孔明啊孔明，你是不是觉得自己特别厉害？最后还不是累死了",
    "你空城计？那是我故意放你一马，你还当真了？",
    "我就是不出来，你能奈我何？有本事你打进来啊",
    "你送我女装？我笑纳了，你倒是出来打啊，缩头乌龟",
    "不是吧不是吧，不会真有人六出祁山寸功未立吧？",
    "你诸葛亮聪明一世，最后还不是被我耗死了？",
    "我司马懿笑到最后，你诸葛亮半路累死，谁是赢家一目了然",
    "就你这水平，也配跟我斗？你连命都没我长",
    "你是不是觉得自己特别牛？最后还不是星落五丈原",
    "笑死，你那点本事，也就会欺负欺负孟获了",
    "孔明啊，你是不是觉得自己特别忠诚？最后还不是把蜀国耗空了",
    "我就是不出来，你能怎么样？有本事你飞进来啊",
    "你送女装？我穿给你看啊，你倒是出来看啊，你敢吗？",
    "不是吧阿sir，六出祁山次次失败，你是来旅游的吗？",
    "你诸葛亮智多近妖，最后还不是被我熬死了？",
    "就你这水平，也配叫卧龙？我看是卧虫吧",
    "你是不是觉得自己特别厉害？最后还不是没赢过我一次",
    "笑死，你死了我都不追，我就是玩，你气不气？",
    "孔明啊，你是不是觉得自己特别能打？最后还不是寸功未立",
    "我司马懿子孙后代当皇帝，你诸葛亮后代战死沙场，你说你图啥",
    "你那点小聪明，在绝对的实力面前就是个笑话",
    "不是吧不是吧，不会真有人觉得自己能赢我吧？",
    "你六出祁山，我次次守，你次次输，你说你多菜",
    "你诸葛亮鞠躬尽瘁，最后还不是把自己累死了？图啥呢",
    "我就是不出来，你咬我啊？有本事你翻墙进来",
    "笑死，你死了我都不追，我就是这么稳，你气不气",
    "就你这水平，也配跟我齐名？你配吗？",
    "你是不是觉得自己特别聪明？最后还不是被我活活耗死",
    "孔明啊，你是不是觉得自己特别伟大？最后还不是一事无成",
    "我司马懿忍辱负重，你诸葛亮穷兵黩武，谁对谁错历史自有公论",
    "不是吧阿sir，不会真有人六出祁山都打不进来吧？",
    "你那点本事，也就会在轮椅上摇扇子了",
    "你诸葛亮名垂青史又怎么样？最后还不是输了？",
    "笑死，我一个'守'字就把你耗死了，你说你多没用",
    "就你这水平，给我提鞋都不配",
    "你是不是觉得自己特别牛？最后还不是星落秋风五丈原",
    "我司马懿笑到最后，你诸葛亮半路夭折，谁赢了？",
    "不是吧不是吧，不会真有人觉得自己能赢我吧？",
]

# 通用反驳
REBUTTALS = [
    "就这？我还以为你能说出什么花来呢",
    "笑死，你也就这点水平了",
    "不是吧不是吧，就这？",
    "你能不能说点新鲜的？翻来覆去就这几句",
    "就这也配跟我吵？回去再读几年书吧",
    "笑死爹了，你这嘴炮水平也不行啊",
    "不是吧阿sir，就这？",
    "你能不能别像个复读机一样？",
    "就这？我还以为多厉害呢",
    "笑死，你这水平也敢出来吵架？",
    "不是吧不是吧，你就这点本事？",
    "你能不能说点有水平的？跟个小学生似的",
    "就这？我家童子吵架都比你厉害",
    "笑死，你这嘴炮，菜得我想笑",
    "不是吧阿sir，就这水平也敢出来丢人？",
    "你能不能别逼逼了？听得我头疼",
    "就这？我还以为你能说出什么呢",
    "笑死，你也就会这几句了吧？",
    "不是吧不是吧，不会真有人吵架这么菜吧？",
    "你这水平，建议回去多读读兵法",
]


def run_bot(name, insults, rebuttals, other_name, stop_event, ready_event):
    """运行一个bot"""
    try:
        bot = MCBot(host=SERVER_IP, port=SERVER_PORT, username=name, timeout=15)

        # 记录聊天
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

        # AuthMe注册
        try:
            bot.authme_login("History123", auto_register=True)
            time.sleep(2)
        except Exception:
            pass

        ready_event.set()
        time.sleep(3)

        # 开场
        bot.send_chat(f"吾乃{name}，今日特来与{other_name}这个匹夫对线！")
        time.sleep(2)

        round_count = 0
        while not stop_event.is_set() and round_count < 35:
            if random.random() < 0.25:
                msg = random.choice(rebuttals)
            else:
                msg = random.choice(insults)
            try:
                bot.send_chat(msg)
                print(f"[{name}] {msg}")
            except Exception as e:
                print(f"[{name}] 发送失败: {e}")
                break
            round_count += 1
            time.sleep(random.uniform(1.5, 3.5))

        # 结尾
        try:
            bot.send_chat(f"罢了罢了，不与{other_name}这等匹夫一般见识，告辞！")
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
    print(f"历史人物对骂 - 诸葛亮 vs 司马懿")
    print(f"服务器: {SERVER_IP}:{SERVER_PORT}")
    print("=" * 60)

    stop_event = threading.Event()
    ready_a = threading.Event()
    ready_b = threading.Event()

    t_a = threading.Thread(target=run_bot, args=(
        "ZhugeLiang", ZHUGE_LIANG, REBUTTALS, "SimaYi", stop_event, ready_a))
    t_b = threading.Thread(target=run_bot, args=(
        "SimaYi", SIMA_YI, REBUTTALS, "ZhugeLiang", stop_event, ready_b))

    t_a.start()
    t_b.start()

    ready_a.wait(timeout=30)
    ready_b.wait(timeout=30)

    print("\n[系统] 两位历史名人已就位，对骂开始！\n")

    t_a.join()
    t_b.join()

    print("\n" + "=" * 60)
    print("千古对骂结束！")
    print("=" * 60)

    # 导出聊天记录
    if chat_log:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_file = f"duel_chat_{ts}.txt"
        html_file = f"duel_chat_{ts}.html"

        # TXT
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(f"诸葛亮 vs 司马懿 对骂聊天记录\n")
            f.write(f"服务器: {SERVER_IP}:{SERVER_PORT}\n")
            f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"消息数: {len(chat_log)}\n")
            f.write("=" * 50 + "\n\n")
            for t, sender, text in chat_log:
                f.write(f"[{t}] {sender}: {text}\n")
        print(f"\n聊天记录已导出: {txt_file}")

        # HTML
        rows = ""
        for t, sender, text in chat_log:
            color = "#e94560" if sender == "ZhugeLiang" else ("#00d992" if sender == "SimaYi" else "#888")
            rows += f'<div class="msg"><span class="time">{t}</span><span class="sender" style="color:{color}">{sender}</span><span class="text">{text}</span></div>\n'
        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>诸葛亮vs司马懿 对骂记录</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
.container{{max-width:900px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{color:#00d992;font-size:22px;margin-bottom:10px}}
.header .info{{color:#888;font-size:13px}}.header .info span{{color:#e94560}}
.chat{{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
.msg{{padding:8px 16px;border-bottom:1px solid #1a1a1a;display:flex;gap:12px;font-size:13px}}
.msg:hover{{background:#161616}}
.msg .time{{color:#555;min-width:60px}}.msg .sender{{font-weight:bold;min-width:100px}}.msg .text{{color:#ccc;flex:1;word-break:break-all}}
.footer{{text-align:center;color:#444;font-size:12px;margin-top:16px}}</style>
</head><body><div class="container">
<div class="header"><h1>诸葛亮 vs 司马懿 对骂记录</h1>
<div class="info">服务器: <span>{SERVER_IP}:{SERVER_PORT}</span> | 消息数: <span>{len(chat_log)}</span></div>
</div><div class="chat">{rows}</div>
<div class="footer">Generated by mc-scanner-v3</div>
</div></body></html>"""
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"聊天记录已导出: {html_file}")


if __name__ == "__main__":
    main()
