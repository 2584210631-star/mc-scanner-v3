"""纯Python Ed25519签名实现，零外部依赖。
用于Minecraft聊天签名，替代cryptography库（Termux等环境可能装不上）。
基于Daniel J. Bernstein的Ed25519算法。"""
from __future__ import annotations

# Ed25519 参数
P = 2 ** 255 - 19
A = 486662
B = (15112221349535400772501151409588531511454012693041857206046113283949847762202,
     46316835694926478169428394003475163141307993866256225615783033603165251855960)
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
I = pow(2, (P - 1) // 4, P)


def _xrecover(y):
    xx = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * I) % P
    if x % 2 != 0:
        x = P - x
    return x


def _edwards_add(pt1, pt2):
    x1, y1 = pt1
    x2, y2 = pt2
    dxy = D * x1 * x2 * y1 * y2
    x3 = (x1 * y2 + x2 * y1) * pow(1 + dxy, P - 2, P) % P
    y3 = (y1 * y2 + x1 * x2) * pow(1 - dxy, P - 2, P) % P
    return (x3, y3)


def _scalarmult(pt, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(pt, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, pt)
    return Q


def _scalarmult_base(e):
    return _scalarmult(B, e)


def _H(m):
    import hashlib
    return hashlib.sha512(m).digest()


def _int_decode(s):
    return int.from_bytes(s, "little")


def _int_encode(i):
    return i.to_bytes(32, "little")


def _point_compress(P):
    x, y = P
    return _int_encode(y + ((x & 1) << 255))


def seed_to_public(seed: bytes) -> bytes:
    """从32字节seed派生公钥（32字节压缩格式）"""
    h = _H(seed)
    a = _int_decode(h[:32])
    a &= (1 << 254) - 8
    a |= 1 << 254
    A = _scalarmult_base(a)
    return _point_compress(A)


def sign(seed: bytes, message: bytes) -> bytes:
    """Ed25519签名。seed为32字节私钥seed，返回64字节签名。"""
    h = _H(seed)
    a = _int_decode(h[:32])
    a &= (1 << 254) - 8
    a |= 1 << 254
    prefix = h[32:]
    A = _scalarmult_base(a)
    A_comp = _point_compress(A)
    r = _int_decode(_H(prefix + message)) % L
    R = _scalarmult_base(r)
    R_comp = _point_compress(R)
    k = _int_decode(_H(R_comp + A_comp + message)) % L
    S = (r + k * a) % L
    return R_comp + _int_encode(S)


def load_private_key_der(der_bytes: bytes) -> bytes:
    """从PKCS#8 DER格式解析Ed25519私钥，返回32字节seed。
    PKCS#8结构: SEQUENCE { INTEGER 0, SEQUENCE { OID Ed25519 }, OCTET STRING { OCTET STRING(32) } }"""
    # 极简DER解析：找到最后一个32字节的OCTET STRING
    # Ed25519 PKCS#8 DER 通常 48 字节左右，私钥seed在末尾的32字节
    if len(der_bytes) >= 32:
        # 私钥seed是DER中最后一个OCTET STRING的内容
        # 扫描找 0x04 0x20 (OCTET STRING, length 32)
        for i in range(len(der_bytes) - 34):
            if der_bytes[i] == 0x04 and der_bytes[i + 1] == 0x20:
                return der_bytes[i + 2:i + 34]
        # 兜底：取最后32字节
        return der_bytes[-32:]
    raise ValueError(f"DER数据太短: {len(der_bytes)}字节")
