#!/usr/bin/env python3
"""观察者发消息调试脚本 - 打印连接全过程和包ID"""
import sys
import time
import struct
sys.path.insert(0, '.')

from core.bot import MCBot
from core.buffer import BytesStream, read_varint_from_stream, read_string_from_stream

HOST = "198.18.0.12"
PORT = 29136
USERNAME = "DebugBot"

def debug_observer():
    print(f"[*] 连接 {HOST}:{PORT} 用户名={USERNAME}")
    bot = MCBot(host=HOST, port=PORT, username=USERNAME, timeout=10)

    # 替换后台线程为调试模式
    original_recv = bot.conn.recv_packet if bot.conn else None

    def debug_chat(text, sender):
        print(f"[CHAT] sender={sender} text={text[:100]}")

    bot.chat_callback = debug_chat

    try:
        ok = bot.connect()
        print(f"[*] connect() 返回: {ok}, protocol={bot.protocol_version}, state={bot.state}")
    except Exception as e:
        print(f"[!] connect 异常: {e}")
        return

    if not ok:
        print("[!] 连接失败")
        return

    print(f"[*] 已连接，协议版本={bot.protocol_version}")
    print(f"[*] play_packets 关键字段:")
    pkts = bot.play_packets
    for k in ['sb_chat', 'sb_chat_command', 'sb_keep_alive', 'sb_confirm_teleport',
              'sb_player_position_look', 'sb_client_info', 'cb_teleport', 'cb_chat_message']:
        print(f"    {k} = {pkts.get(k)}")

    # 等3秒让服务器完成初始化
    print("[*] 等待3秒...")
    time.sleep(3)

    # 检查后台线程是否还活着
    print(f"[*] 后台线程存活: {bot.play_thread.is_alive() if bot.play_thread else 'None'}")
    print(f"[*] connected={bot.connected}")

    # 发消息
    test_msg = "调试测试消息123"
    print(f"[*] 发送聊天消息: {test_msg}")
    try:
        payload = bot.protocol_handler.send_chat_payload(test_msg)
        print(f"[*] send_chat_payload 长度={len(payload)}, 前20字节={payload[:20].hex()}")
        bot.send_chat(test_msg)
        print("[*] 消息已发送")
    except Exception as e:
        print(f"[!] send_chat 异常: {e}")

    # 等3秒看服务器响应
    print("[*] 等待3秒看服务器响应...")
    time.sleep(3)

    print(f"[*] 最终 connected={bot.connected}")
    print(f"[*] 收到聊天消息数: {len(bot.chat_messages)}")
    for m in bot.chat_messages[-5:]:
        print(f"    - {m[:100]}")

    bot.close()
    print("[*] 已断开")

if __name__ == "__main__":
    debug_observer()
