#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
观察者（Observer）端到端测试。
用带推送能力的 mock 服务器验证：连接保持、聊天抓取、玩家进出、发送消息、停止。
"""
import io
import json
import os
import socket
import struct
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'libs'))

from core.buffer import (read_varint_from_stream, read_string_from_stream,
                         write_string, write_uuid, write_varint)
from core.bot import MCBot
from tests.mock_server import SocketStream
from web.app import ObserverSession, observer_sessions, observer_lock

PROTO = 767  # 1.21
CB_KEEP_ALIVE = 0x26
CB_SYSTEM_CHAT = 0x62
CB_PLAYER_INFO = 0x38
CB_LOGIN = 0x2B


def _read_varint(data, offset):
    result = 0
    num_read = 0
    while True:
        byte = data[offset + num_read]
        result |= (byte & 0x7F) << (7 * num_read)
        num_read += 1
        if not (byte & 0x80):
            break
    if result >= (1 << 31):
        result -= (1 << 32)
    return result, offset + num_read


def _read_string(data, offset):
    length, offset = _read_varint(data, offset)
    return data[offset:offset + length].decode("utf-8", "replace"), offset + length


class PushServer:
    """最小 MC 服务器：cracked 登录，进入 play 后可推送聊天/玩家信息包。"""
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.conn = None
        self.received_messages = []
        self.player_uuids = {}
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _send_packet(self, packet_id, payload=b""):
        if not self.conn:
            return
        try:
            body = write_varint(packet_id) + payload
            self.conn.sendall(write_varint(len(body)) + body)
        except Exception:
            pass

    def _accept(self):
        while self.running:
            try:
                self.sock.settimeout(1.0)
                self.conn, _ = self.sock.accept()
                self.conn.settimeout(8.0)
                threading.Thread(target=self._handle, daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _handle(self):
        conn = self.conn
        stream = SocketStream(conn)
        state = 0  # handshake
        last_ka = time.time()
        while self.running:
            try:
                length = read_varint_from_stream(stream)
                if length <= 0 or length > 1024 * 1024:
                    break
                data = stream.read(length)
                buf = io.BytesIO(data)
                packet_id = read_varint_from_stream(buf)
                payload = buf.read()
                if state == 0:
                    if packet_id == 0x00:
                        _, off = _read_varint(payload, 0)
                        _, off = _read_string(payload, off)
                        off += 2
                        state, _ = _read_varint(payload, off)
                    continue
                elif state == 1:  # status
                    if packet_id == 0x00:
                        self._send_packet(0x00, write_string(json.dumps({
                            "version": {"name": "1.21", "protocol": PROTO},
                            "players": {"online": 2, "max": 100},
                            "description": {"text": "observer-test"},
                        })))
                    elif packet_id == 0x01:  # ping -> 原样回显作为 pong
                        try:
                            self.conn.sendall(write_varint(len(data)) + data)
                        except Exception:
                            pass
                        break
                elif state == 2:  # login
                    if packet_id == 0x00:
                        username, _ = _read_string(payload, 0)
                        puuid = uuid.uuid3(uuid.NAMESPACE_OID, f"OfflinePlayer:{username}")
                        self._send_packet(0x02, write_uuid(puuid) + write_string(username))
                    elif packet_id == 0x03:  # login acknowledged
                        state = 3  # configuration
                        self._send_packet(0x0E, write_varint(0))  # known packs 询问
                elif state == 3:  # configuration
                    if packet_id == 0x00:  # client information -> 询问品牌
                        self._send_packet(0x01, write_string("minecraft:brand"))
                    elif packet_id == 0x02:  # plugin message (品牌回复)
                        pass
                    elif packet_id == 0x03:  # finish configuration (client)
                        self._send_packet(0x03, b"")  # finish configuration (server)
                        state = 4
                        self._send_login_play()
                    elif packet_id == 0x04:  # keep alive
                        pass
                elif state == 4:  # play
                    if packet_id == 0x1B:  # keep alive response
                        pass
                    elif packet_id in (0x08, 0x03, 0x05, 0x06):  # chat (各版本)
                        try:
                            msg, _ = _read_string(payload, 0)
                            self.received_messages.append(msg)
                        except Exception:
                            pass
                    if time.time() - last_ka > 2:
                        self._send_packet(CB_KEEP_ALIVE, struct.pack(">q", 12345))
                        last_ka = time.time()
            except Exception:
                break
        try:
            conn.close()
        except Exception:
            pass

    def _send_login_play(self):
        p = (struct.pack(">i", 1) + b"\x00" + write_varint(1)
             + write_string("minecraft:overworld") + write_string("minecraft:overworld")
             + write_string("minecraft:overworld") + struct.pack(">q", 0) + write_varint(20)
             + write_varint(8) + write_varint(8) + b"\x00" + b"\x01" + b"\x00" + b"\x00"
             + b"\x00" + b"\x00" + struct.pack(">i", 0))
        self._send_packet(CB_LOGIN, p)

    def push_system_chat(self, text):
        self._send_packet(CB_SYSTEM_CHAT, write_string(json.dumps({"text": text})) + write_varint(0))

    def push_player_add(self, name):
        puuid = uuid.uuid4()
        self.player_uuids[name] = puuid
        payload = write_varint(0x01) + write_varint(1) + write_uuid(puuid) + write_string(name) + write_varint(0)
        self._send_packet(CB_PLAYER_INFO, payload)

    def push_player_remove(self, name):
        puuid = self.player_uuids.get(name, uuid.uuid3(uuid.NAMESPACE_OID, f"Obs:{name}"))
        payload = write_varint(0x80) + write_varint(1) + write_uuid(puuid)
        self._send_packet(CB_PLAYER_INFO, payload)

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


def wait_until(fn, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return None


def test_observer_flow():
    server = PushServer()
    try:
        obs = ObserverSession("127.0.0.1", server.port, "ObsBot", timeout=5.0)
        obs.session_id = "test-obs-1"
        with observer_lock:
            observer_sessions[obs.session_id] = obs
        obs.thread = threading.Thread(target=obs.run, daemon=True)
        obs.thread.start()

        # 1. 连接成功
        assert wait_until(lambda: obs.status == "connected"), f"未连接成功, status={obs.status} err={obs.error}"
        assert obs.auth_mode == "offline", obs.auth_mode

        # 2. 推送聊天与玩家信息
        time.sleep(0.5)
        server.push_system_chat("hello observer")
        server.push_player_add("Steve")
        server.push_player_add("Alex")
        time.sleep(1.0)
        server.push_player_remove("Alex")
        time.sleep(0.5)

        # 3. 事件被捕获
        types = [e[2] for e in obs.events]
        assert "chat" in types, f"未捕获聊天: {types}"
        assert "join" in types, f"未捕获加入: {types}"
        assert "leave" in types, f"未捕获离开: {types}"
        players = obs._players()
        assert "Steve" in players and "Alex" not in players, f"玩家列表异常: {players}"
        print("[OK] 聊天/进出事件与玩家列表正确:", types, players)

        # 4. 观察中发消息
        assert obs.status == "connected"
        obs.bot.send_chat("still alive")
        time.sleep(0.5)
        assert any("still alive" in m for m in server.received_messages), f"服务器未收到: {server.received_messages}"

        # 5. 停止
        obs.stop()
        time.sleep(1.0)
        assert obs.status in ("stopped", "disconnected"), obs.status
        assert not getattr(obs.bot, "connected", True), "连接应已关闭"
        print("[OK] 观察中发消息 + 停止正常")

        # 6. full() 输出结构完整
        full = obs.full()
        for key in ("status", "players_online", "players", "events", "last_seq", "chat", "version_name"):
            assert key in full, f"full() 缺少 {key}"
        print("[OK] full() 输出结构完整")
        return True
    finally:
        server.stop()


if __name__ == "__main__":
    ok = test_observer_flow()
    print("\n=== 观察者 e2e 测试通过 ===" if ok else "\n=== 测试失败 ===")
