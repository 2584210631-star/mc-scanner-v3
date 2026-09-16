# -*- coding: utf-8 -*-
"""
双AI对骂脚本 - 进17365
两个bot轮流阴阳怪气，内置台词不花API钱
"""
import sys
import time
import random
import threading

sys.path.insert(0, '.')
from core.bot import MCBot

SERVER_IP = "103.85.86.51"
SERVER_PORT = 17365

# 两个bot的名字
BOT_A_NAME = "Duelist_A"
BOT_B_NAME = "Duelist_B"

# 对骂台词库 - 阴阳怪气风格
INSULTS_A = [
    "就你这水平也敢来服务器？我家狗玩得都比你溜",
    "不是吧不是吧，真有人觉得自己很厉害啊？",
    "笑死，你那操作我奶奶看了都摇头",
    "你是不是把智商都拿去充QQ会员了？",
    "就这？就这？我还以为多厉害呢，就这？",
    "你妈妈知道你在游戏里这么菜吗？",
    "我要是你我早就退服了，还在这丢人现眼",
    "你这技术是跟谁学的？跟智障学的吗？",
    "不是我说你，你这操作放出去都没人信是人类玩的",
    "你是不是觉得自己特别幽默？其实特别傻逼",
    "笑死爹了，你也配跟我说话？",
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
    "不是我说你，你这水平真的太菜了",
    "你是不是对这个游戏有什么误解？",
    "笑死，你也配跟我对线？",
    "你这脑子，怕是连加法都算不明白吧",
    "就你这水平，建议卸载游戏",
    "你是不是出生的时候被门夹了？",
    "我从来没见过这么傻逼的人",
    "你这操作，菜得我想笑",
    "不是吧不是吧，真有人这么菜啊？",
    "你这智商，怕是连自己名字都写不明白",
]

INSULTS_B = [
    "哟，这不是那个菜鸡吗？怎么还在这玩呢？",
    "就你也配说我？你先照照镜子看看自己什么样",
    "笑死，你这种菜鸡也敢出来说话？",
    "不是吧不是吧，不会真有人觉得自己比我强吧？",
    "你这水平，给我提鞋都不配",
    "我要是你，我早就闭嘴了，还在这逼逼赖赖",
    "就你这脑子，也配跟我吵架？",
    "你是不是觉得自己特别厉害？其实就是个傻逼",
    "笑死爹了，你也配跟我说话？",
    "你这操作，菜得我都不想说你了",
    "不是吧阿sir，这都不会？你是弱智吗？",
    "你这智商，建议去医院看看脑子",
    "就你这水平，去扫大街都没人要",
    "你是不是把脑子落家里了？出门忘带了？",
    "我从来没见过这么傻逼的人，今天算是见识了",
    "你这操作，是用屁股玩的吧？",
    "不是吧不是吧，不会真有人这么菜吧？",
    "你这水平，连我家猫都不如",
    "就你也配玩这个游戏？赶紧卸载吧",
    "你是不是对自己有什么误解？觉得自己很强？",
    "笑死，你这种菜鸡也敢出来丢人？",
    "你这脑子，怕是连1+1都算不明白吧",
    "就你这水平，建议回娘胎重造",
    "你是不是出生的时候脑子被挤了？",
    "我要是你，我都不好意思活着",
    "你这操作，菜得我想报警",
    "不是吧不是吧，真有人这么傻逼啊？",
    "你这智商，怕是连自己名字都不会写",
    "就你这水平，给我当徒弟我都嫌丢人",
    "你是不是觉得自己特别幽默？其实特别傻逼",
    "笑死，你也配跟我对线？你配吗？",
    "你这操作，菜得我都不忍心看了",
    "不是吧阿sir，这都能输？你是智障吗？",
    "你这脑子，建议捐给需要的人",
    "就你这水平，去新手村都被人虐哭",
    "你是不是把智商都拿去买皮肤了？",
    "我从来没见过这么菜的人，今天算是开眼了",
    "你这操作，是用脚玩的吧？不对，脚都比你强",
    "不是吧不是吧，不会真有人这么傻逼吧？",
    "你这智商，怕是连呼吸都费劲吧",
]

# 接话/反驳台词
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
    "不是吧不是吧，你就这点本事？",
    "你能不能说点有水平的？跟个小学生似的",
    "就这？我奶奶吵架都比你厉害",
    "笑死，你这嘴炮，菜得我想笑",
    "不是吧阿sir，就这水平也敢出来丢人？",
    "你能不能别逼逼了？听得我头疼",
    "就这？我还以为你能说出什么呢",
    "笑死，你也就会这几句了吧？",
    "不是吧不是吧，不会真有人吵架这么菜吧？",
    "你这水平，建议回去多练练",
]


def run_bot(name, insults, rebuttals, other_name, stop_event, ready_event):
    """运行一个bot"""
    try:
        bot = MCBot(host=SERVER_IP, port=SERVER_PORT, username=name, timeout=15)
        bot.connect()
        time.sleep(2)

        if bot.state != "play":
            print(f"[{name}] 连接失败，状态={bot.state}")
            ready_event.set()
            return

        print(f"[{name}] 已进入服务器")

        # AuthMe注册
        try:
            bot.authme_login("Duel123456", auto_register=True)
            time.sleep(2)
        except Exception:
            pass

        ready_event.set()

        # 等另一个bot也准备好
        time.sleep(3)

        # 开场
        bot.send_chat(f"大家好，我是{name}，今天来跟{other_name}这个菜鸡对线")
        time.sleep(2)

        round_count = 0
        while not stop_event.is_set() and round_count < 30:
            # 随机选一句骂人的话
            if random.random() < 0.3:
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
            # 随机等待1-3秒
            time.sleep(random.uniform(1.5, 3.5))

        # 结尾
        try:
            bot.send_chat(f"行了，不跟{other_name}这个菜鸡一般见识，散了散了")
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
    print(f"双AI对骂脚本 - {SERVER_IP}:{SERVER_PORT}")
    print(f"Bot A: {BOT_A_NAME}")
    print(f"Bot B: {BOT_B_NAME}")
    print("=" * 60)

    stop_event = threading.Event()
    ready_a = threading.Event()
    ready_b = threading.Event()

    # 启动两个bot
    t_a = threading.Thread(target=run_bot, args=(
        BOT_A_NAME, INSULTS_A, REBUTTALS, BOT_B_NAME, stop_event, ready_a))
    t_b = threading.Thread(target=run_bot, args=(
        BOT_B_NAME, INSULTS_B, REBUTTALS, BOT_A_NAME, stop_event, ready_b))

    t_a.start()
    t_b.start()

    # 等两个都连接好
    ready_a.wait(timeout=30)
    ready_b.wait(timeout=30)

    print("\n[系统] 两个bot都已连接，对骂开始！\n")

    # 等两个线程结束
    t_a.join()
    t_b.join()

    print("\n" + "=" * 60)
    print("对骂结束！")
    print("=" * 60)


if __name__ == "__main__":
    main()
