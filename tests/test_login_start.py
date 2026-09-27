# -*- coding: utf-8 -*-
"""Login Start 字节构造测试：覆盖 760/763/764 三个关键分界点。"""
from core.probe import build_login_start_payload
from core.buffer import write_string, write_uuid, offline_uuid


class TestLoginStartPayload:
    def test_763_has_flag(self):
        """1.20.1 (763): username + \\x01(hasUUID) + UUID"""
        p = build_login_start_payload("Test", 763)
        expected = write_string("Test") + b'\x01' + write_uuid(offline_uuid("Test"))
        assert p == expected
        # 明确：uuid 前面有一个 0x01 字节
        assert p[len(write_string("Test"))] == 0x01

    def test_764_no_flag(self):
        """1.20.2 (764): username + UUID（无 0x01 标志位）"""
        p = build_login_start_payload("Test", 764)
        expected = write_string("Test") + write_uuid(offline_uuid("Test"))
        assert p == expected
        # 明确：username 后面直接跟 UUID 首字节，没有 0x01
        prefix = write_string("Test")
        assert p[len(prefix):len(prefix)+1] != b'\x01'

    def test_766_no_flag(self):
        """1.20.5 (766): 同 764，无标志位"""
        p = build_login_start_payload("Test", 766)
        expected = write_string("Test") + write_uuid(offline_uuid("Test"))
        assert p == expected

    def test_760_has_flag(self):
        """1.19.2 (760): 有标志位"""
        p = build_login_start_payload("Test", 760)
        prefix = write_string("Test")
        assert p[len(prefix)] == 0x01

    def test_759_has_flag(self):
        """1.19 (759): 有标志位"""
        p = build_login_start_payload("Test", 759)
        prefix = write_string("Test")
        assert p[len(prefix)] == 0x01
