# -*- coding: utf-8 -*-
"""微软/Minecraft正版认证模块。
Azure AD v2.0 设备码流程 + RSA/AES加密握手。
用Azure CLI官方client_id，支持v2.0端点。
"""
import json
import urllib.request
import urllib.parse
import urllib.error

# v2.0设备码流程用Azure CLI的client_id（支持v2.0端点）
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
SCOPE = "XboxLive.signin offline_access"
# FCL启动器的client_id（旧版MSA端点授权码流程，已验证可用）
FCL_CLIENT_ID = "d903cc0e-c3b4-4a3c-b347-06c2e6269be0"
FCL_REDIRECT_URI = "http://localhost:8090/auth-response"
# 旧版client_id（保留，用于兼容）
LEGACY_CLIENT_ID = "00000000402b5328"
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"

def _post(url, data=None, headers=None):
    """简单POST请求，出错时返回错误详情"""
    body = urllib.parse.urlencode(data).encode() if data else b""
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors='replace')
        print(f"[MSA] HTTP {e.code}: {err_body[:300]}")
        return {"error": f"HTTP {e.code}", "error_description": err_body[:500]}
    except Exception as e:
        print(f"[MSA] 请求异常: {e}")
        return {"error": str(e)}


def start_device_code(client_id=None):
    """开始设备码流程(v2.0)，返回 {user_code, verification_uri, device_code, interval}"""
    cid = client_id or CLIENT_ID
    data = {
        "client_id": cid,
        "scope": SCOPE,
    }
    r = _post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode", data)
    if "error" in r and "user_code" not in r:
        return r
    return {
        "user_code": r["user_code"],
        "verification_uri": r.get("verification_uri", "https://www.microsoft.com/link"),
        "device_code": r["device_code"],
        "interval": r.get("interval", 5),
        "expires_in": r.get("expires_in", 900),
    }


def poll_token(device_code, client_id=None, interval=5):
    """轮询获取MSA access token(v2.0)。用户登录后返回 {access_token, refresh_token}"""
    cid = client_id or CLIENT_ID
    data = {
        "client_id": cid,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
    }
    r = _post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token", data)
    return r


def get_auth_url(client_id=None, redirect_uri=None):
    """生成授权URL（隐式流程，直接返回access_token）"""
    cid = client_id or CLIENT_ID
    rd = redirect_uri or REDIRECT_URI
    params = {
        "client_id": cid,
        "response_type": "token",
        "redirect_uri": rd,
        "scope": SCOPE,
    }
    return "https://login.live.com/oauth20_authorize.srf?" + urllib.parse.urlencode(params)


def exchange_code(code, client_id=None, redirect_uri=None):
    """用授权码换MSA access token"""
    cid = client_id or CLIENT_ID
    rd = redirect_uri or REDIRECT_URI
    data = {
        "client_id": cid,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": rd,
        "scope": SCOPE,
    }
    r = _post("https://login.live.com/oauth20_token.srf", data)
    return r


def get_fcl_auth_url():
    """生成FCL授权码流程的登录URL（旧版MSA端点，已验证可用）"""
    params = {
        "client_id": FCL_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": FCL_REDIRECT_URI,
        "scope": SCOPE,
    }
    return "https://login.live.com/oauth20_authorize.srf?" + urllib.parse.urlencode(params)


def fcl_exchange_code(code):
    """用FCL授权码换MSA access token（旧版MSA端点）"""
    data = {
        "client_id": FCL_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": FCL_REDIRECT_URI,
        "scope": SCOPE,
    }
    r = _post("https://login.live.com/oauth20_token.srf", data)
    return r


def fcl_get_device_code():
    """FCL设备码流程：获取设备码（v2.0端点，FCL同款）"""
    data = {
        "client_id": FCL_CLIENT_ID,
        "scope": SCOPE,
    }
    r = _post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode", data)
    return r


def fcl_poll_device_code(device_code):
    """FCL设备码流程：轮询获取MSA token（v2.0端点）"""
    data = {
        "client_id": FCL_CLIENT_ID,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
    }
    r = _post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token", data)
    return r


def xbox_auth(msa_token):
    """MSA token → Xbox Live token。v2.0端点用d=前缀（FCL同款）"""
    # v2.0端点返回的token用d=前缀（FCL/Minecraft启动器都这么做）
    rps_ticket = f"d={msa_token}"
    data = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": rps_ticket,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://user.auth.xboxlive.com/user/authenticate",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        r = json.loads(resp.read().decode())
    return r["Token"], r["DisplayClaims"]["xui"][0]["uhs"]


def xsts_auth(xbox_token):
    """Xbox token → XSTS token"""
    data = {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://xsts.auth.xboxlive.com/xsts/authorize",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        r = json.loads(e.read().decode())
        if r.get("XErr") == 2148916233:
            raise Exception("该微软账号没有Xbox账号，需要先登录一次Xbox")
        if r.get("XErr") == 2148916235:
            raise Exception("账号被封禁或需要验证年龄")
        raise Exception(f"XSTS认证失败: {r}")
    return r["Token"]


def mc_login(uhs, xsts_token):
    """XSTS → Minecraft access token"""
    data = {"identityToken": f"XBL3.0 x={uhs};{xsts_token}"}
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://api.minecraftservices.com/authentication/login_with_xbox",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        r = json.loads(resp.read().decode())
    return r["access_token"]


def mc_profile(mc_token):
    """获取MC玩家信息"""
    req = urllib.request.Request(
        "https://api.minecraftservices.com/minecraft/profile"
    )
    req.add_header("Authorization", f"Bearer {mc_token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode())
        return {"uuid": r["id"], "name": r["name"]}
    except urllib.error.HTTPError:
        raise Exception("该账号未购买Minecraft")


def full_login_flow(msa_token):
    """完整流程：MSA token → MC token + profile"""
    xbox_token, uhs = xbox_auth(msa_token)
    xsts_token = xsts_auth(xbox_token)
    mc_token = mc_login(uhs, xsts_token)
    profile = mc_profile(mc_token)
    return {"access_token": mc_token, "uuid": profile["uuid"], "name": profile["name"]}


def join_server(mc_token, uuid, server_id_hash):
    """向Mojang发送joinServer请求（正版加密握手时调用）"""
    data = {
        "accessToken": mc_token,
        "selectedProfile": uuid,
        "serverId": server_id_hash,
    }
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://sessionserver.mojang.com/session/minecraft/join",
        data=body, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {mc_token}")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[正版] joinServer失败: {e}")
        return False


def fetch_certificates(mc_token):
    """从Mojang获取聊天签名用的Ed25519证书。
    客户端生成Ed25519密钥对，将公钥(SubjectPublicKeyInfo DER)发给Mojang签名。
    返回 {privateKey(PEM), publicKey(PEM), publicKeySignature(base64), expiresAt} 或 None。
    """
    import os, base64 as _b64
    try:
        from .ed25519 import seed_to_public
    except ImportError:
        seed_to_public = None

    # 1. 客户端生成Ed25519密钥对
    seed = os.urandom(32)
    if seed_to_public:
        pub_raw = seed_to_public(seed)  # 32字节
    else:
        # 兜底：用cryptography生成（如果可用）
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption
        _priv = Ed25519PrivateKey.from_private_bytes(seed)
        pub_raw = _priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    # 2. 构造SubjectPublicKeyInfo DER (Ed25519, 44字节)
    #    30 2a 30 05 06 03 2b 65 70 03 21 00 <32B pub>
    spki_der = bytes.fromhex("302a300506032b6570032100") + pub_raw

    # 3. 构造PKCS#8 DER (Ed25519私钥, 48字节)
    #    30 2e 02 01 00 30 05 06 03 2b 65 70 04 22 04 20 <32B seed>
    pkcs8_der = bytes.fromhex("302e020100300506032b657004220420") + seed

    # 4. 公钥base64编码，发给Mojang签名
    pub_b64 = _b64.b64encode(spki_der).decode()

    req_body = json.dumps({"publicKey": pub_b64}).encode()
    req = urllib.request.Request(
        "https://api.minecraftservices.com/player/certificates",
        method="POST",
        data=req_body,
        headers={"Content-Type": "application/json"}
    )
    req.add_header("Authorization", f"Bearer {mc_token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            # 5. Mojang返回签名后的公钥和签名
            #    用客户端生成的密钥对（Mojang返回的publicKey应和我们发的一致）
            return {
                "privateKey": _b64.b64encode(pkcs8_der).decode(),
                "publicKey": data.get("keyPair", {}).get("publicKey", pub_b64),
                "publicKeySignature": data["publicKeySignature"],
                "expiresAt": data["expiresAt"],
            }
    except Exception as e:
        print(f"[正版] 获取certificates失败: {e}")
        return None


def refresh_msa_token(refresh_token, client_id=None):
    """用refresh_token刷新MSA access_token。返回 {access_token, refresh_token} 或 None"""
    if not refresh_token:
        return None
    cid = client_id or FCL_CLIENT_ID  # FCL流程用FCL_CLIENT_ID
    data = {
        "client_id": cid,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    }
    r = _post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token", data)
    if r.get("access_token"):
        return {"access_token": r["access_token"], "refresh_token": r.get("refresh_token", refresh_token)}
    print(f"[正版] MSA token刷新失败: {r.get('error', 'unknown')}")
    return None


def refresh_mc_token(refresh_token, client_id=None):
    """完整刷新流程：MSA refresh_token → 新MC token。返回 {access_token, uuid, name, refresh_token} 或 None"""
    msa = refresh_msa_token(refresh_token, client_id)
    if not msa:
        return None
    try:
        result = full_login_flow(msa["access_token"])
        result["refresh_token"] = msa["refresh_token"]
        print(f"[正版] token自动刷新成功: {result.get('name')}")
        return result
    except Exception as e:
        print(f"[正版] MC token刷新失败: {e}")
        return None
