#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI bot 进入服务器聊天 + 5分钟监控 + 聊天记录导出（DeepSeek驱动）"""
import sys, os, time, json, re, random
from datetime import datetime
sys.path.insert(0, '/home/user/mc-v3')

from core.bot import MCBot
from core.ai_generator import generate_content

HOST = "103.85.86.51"
PORT = 29900
USERNAME = "yyf_002"
DURATION = 300
PROTO = None

# DeepSeek 配置
API_KEY = "sk-0bc1ff0927964437b68ed860175f33b7"
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

print(f"[配置] DeepSeek API: {MODEL} @ {BASE_URL}")

# 系统消息过滤关键词（不记录、不回复）
SYSTEM_FILTERS = [
    "比赛倒计时", "扫地姬", "钓到了", "签到", "玩家系统", "自动给钟",
    "没有新的邮件", "cracked Minecraft", "LiteSignIn", "通过验证",
    "加入了游戏", "离开了游戏", "达成了", "完成了", "欢迎来到",
    "溜掉", "获得了", "失去了", "升级了", "睡觉", "起床",
    "进入了", "退出了", "重新连接", "超时", "断开", "传送",
    "重生", "淹死", "摔死", "烧死", "炸死", "清理掉落物",
    "公共垃圾桶", "清理成功", "还剩下", "秒后", "kkfish",
    "death.", "advancement", "已连接到", "已成功注册", "已成功登录",
    "哇！来了", "咦，来了", "初次见面", "喵，欢迎", "请不要刷屏",
    "您需要先", "此用户名还未注册", "请输入",
]

# 预设回复（AI失败时兜底）
FALLBACK_REPLIES = [
    "哦？是吗？那你真棒呢", "笑死，这也能说出口？", "你说的都对，毕竟你最懂",
    "嗯嗯嗯，你说的太对了（敷衍）", "不是吧不是吧，真有人这样玩？",
    "我要是你我早就退了", "这操作我奶奶都比你强", "啊对对对，你说什么都对",
    "你这理解能力也是没谁了", "你说的好有道理，我差点就信了",
    "你开心就好，反正我不背锅", "你这脑回路挺清奇啊",
]
PROVOCATIONS = [
    "这服人都这么菜的吗？", "不是吧，就这水平？", "有人吗？说句话啊",
    "不会吧不会吧，真有人在这玩？", "就这？我还以为多厉害呢",
    "有人打架吗？没有我走了", "这服管理呢？出来管管",
    "有没有正常人？说句话", "就没人说句话？太无聊了",
    "这服玩家都这么佛系的吗？",
]

chat_log = []
last_reply = 0
bot = None

def is_system_msg(text):
    return any(f in text for f in SYSTEM_FILTERS)

def extract_player_msg(text):
    """从 [Java][称号]名字: 消息 格式中提取玩家名和消息"""
    m = re.match(r'\[Java\]\[([^\]]+)\]([^:]+):\s*(.*)', text)
    if m:
        return m.group(2).strip(), m.group(3).strip()
    m = re.match(r'\[Java\]([^:]+):\s*(.*)', text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, text

def log_chat(sender, text, direction="recv"):
    ts = datetime.now().strftime("%H:%M:%S")
    chat_log.append({"time": ts, "sender": sender, "text": text, "direction": direction})
    tag = "→" if direction == "send" else "←"
    print(f"[{ts}] {tag} {sender}: {text}")

def ai_reply(player_name, text):
    """用DeepSeek生成阴阳怪气回复"""
    try:
        persona = (
            "你是一个在Minecraft服务器里阴阳怪气的玩家，名字叫yyf。"
            "你说话尖酸刻薄，喜欢怼人，语气嘲讽，像真实玩家聊天。"
            "回复必须简短（15字以内），不要礼貌，不要说自己是AI，不要用引号。"
            "可以适当用网络用语和脏话，但不要太过分。"
        )
        prompt = f"玩家{player_name}说：{text}\n请用阴阳怪气的语气回复一句话："
        result = generate_content(
            topic="",
            preset="custom",
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            custom_prompt=prompt,
            custom_system=persona,
            timeout=30,
        )
        if result.get("success") and result.get("text"):
            reply = result["text"].strip()
            reply = re.sub(r'[""「」『』]', '', reply)
            reply = reply.split('\n')[0][:30]
            if reply and len(reply) >= 2:
                return reply
    except Exception as e:
        print(f"[AI失败] {e}")
    return random.choice(FALLBACK_REPLIES)

def on_chat(text, sender="未知"):
    global last_reply
    # 过滤系统消息
    if is_system_msg(text):
        return
    # 提取真实玩家名
    player_name, clean_text = extract_player_msg(text)
    if player_name:
        sender = player_name
        text = clean_text
    # 跳过自己的消息
    if sender == USERNAME or f"]{USERNAME}:" in text or text.startswith(f"{USERNAME}:"):
        return
    # 记录
    log_chat(sender, text)
    # 回复冷却
    now = time.time()
    if now - last_reply < 5:
        return
    if random.random() > 0.6:
        return
    last_reply = now
    reply = ai_reply(sender, text)
    if reply and bot and bot.state == "play":
        try:
            bot.send_chat(reply)
            log_chat(USERNAME, reply, "send")
        except Exception as e:
            print(f"[发送失败] {e}")

def main():
    global bot
    print(f"[启动] 连接 {HOST}:{PORT} as {USERNAME}")
    bot = MCBot(host=HOST, port=PORT, username=USERNAME, timeout=15, protocol_version=PROTO)
    bot.chat_callback = on_chat
    try:
        bot.connect()
    except Exception as e:
        print(f"[连接失败] {e}")
        return
    if bot.state != "play":
        print(f"[连接失败] state={bot.state}")
        return
    print(f"[连接成功] 开始监控{DURATION}秒...")
    
    # AuthMe 注册/登录
    time.sleep(3)
    print("[AuthMe] 登录/注册...")
    bot.authme_login("yyf123456", auto_register=True)
    time.sleep(2)
    print("[AuthMe] 完成，开始监控")
    
    start = time.time()
    next_auto = start + random.randint(25, 45)
    while time.time() - start < DURATION:
        time.sleep(1)
        if bot.state != "play":
            print(f"[断开] state={bot.state}")
            break
        now = time.time()
        if now >= next_auto:
            next_auto = now + random.randint(30, 55)
            if bot.state == "play":
                msg = random.choice(PROVOCATIONS)
                try:
                    bot.send_chat(msg)
                    log_chat(USERNAME, msg, "send")
                except Exception as e:
                    print(f"[主动发言失败] {e}, state={bot.state}")
                    if "Broken pipe" in str(e) or "Connection" in str(e):
                        print("[被踢] 保存报告退出")
                        break
    
    print(f"[结束] 共记录 {len(chat_log)} 条消息")
    save_report()
    try:
        bot.close()
    except:
        pass

def save_report():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = f"/home/user/mc-v3/chat_log_{timestamp}.txt"
    html_path = f"/home/user/mc-v3/chat_log_{timestamp}.html"
    
    # 只保留玩家消息和bot发送的消息
    filtered = [e for e in chat_log if e["direction"] == "send" or not is_system_msg(e["text"])]
    
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"MC服务器聊天记录\n服务器: {HOST}:{PORT}\n用户名: {USERNAME}\n")
        f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n消息数: {len(filtered)}\n")
        f.write("=" * 60 + "\n\n")
        for e in filtered:
            tag = "发送" if e["direction"] == "send" else "接收"
            f.write(f"[{e['time']}] [{tag}] {e['sender']}: {e['text']}\n")
    
    send_count = sum(1 for m in filtered if m['direction']=='send')
    recv_count = sum(1 for m in filtered if m['direction']=='recv')
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MC聊天记录 - {HOST}:{PORT}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0a0a;color:#e0e0e0;font-family:Consolas,Monaco,monospace;padding:20px}}
.container{{max-width:900px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #0f3460;border-radius:12px;padding:24px;margin-bottom:20px}}
.header h1{{color:#00d992;font-size:24px;margin-bottom:12px}}
.header .info{{color:#888;font-size:14px;line-height:1.8}}.header .info span{{color:#e94560}}
.stats{{display:flex;gap:16px;margin-top:16px}}
.stat{{background:#0f3460;padding:12px 20px;border-radius:8px;text-align:center}}
.stat .num{{font-size:28px;color:#00d992;font-weight:bold}}.stat .label{{font-size:12px;color:#888}}
.chat{{background:#111;border:1px solid #222;border-radius:12px;overflow:hidden}}
.msg{{padding:10px 16px;border-bottom:1px solid #1a1a1a;display:flex;gap:12px;align-items:flex-start}}
.msg:hover{{background:#161616}}
.msg .time{{color:#555;font-size:12px;min-width:60px;padding-top:2px}}
.msg .sender{{font-weight:bold;min-width:100px}}
.msg.send .sender{{color:#e94560}}.msg.recv .sender{{color:#00d992}}
.msg .text{{color:#ccc;flex:1;word-break:break-all}}.msg.send .text{{color:#ff6b6b}}
.footer{{text-align:center;color:#444;font-size:12px;margin-top:20px;padding:20px}}</style>
</head><body><div class="container">
<div class="header"><h1>MC服务器聊天记录</h1>
<div class="info">服务器: <span>{HOST}:{PORT}</span> | 用户名: <span>{USERNAME}</span> | 时间: <span>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span> | AI: <span>DeepSeek</span></div>
<div class="stats">
<div class="stat"><div class="num">{len(filtered)}</div><div class="label">总消息</div></div>
<div class="stat"><div class="num">{send_count}</div><div class="label">发送</div></div>
<div class="stat"><div class="num">{recv_count}</div><div class="label">接收</div></div>
</div></div><div class="chat">
"""
    for e in filtered:
        html += f'<div class="msg {e["direction"]}"><div class="time">{e["time"]}</div><div class="sender">{e["sender"]}</div><div class="text">{e["text"]}</div></div>\n'
    html += '</div><div class="footer">Generated by mc-scanner-v3 AI Bot (DeepSeek)</div></div></body></html>'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[保存] TXT: {txt_path}")
    print(f"[保存] HTML: {html_path}")

if __name__ == "__main__":
    main()
