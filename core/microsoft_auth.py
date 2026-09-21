# -*- coding: utf-8 -*-
"""微软/Minecraft正版认证模块。
OAuth设备码流程(v1.0 ADAL) + RSA/AES加密握手。
用Minecraft Launcher官方client_id，无需自己注册Azure。
"""
import json
import os
import time
import struct
import hashlib
import urllib.request
import urllib.parse
import urllib.error

CLIENT_ID = "00000000402b5328"  # Minecraft Launcher 官方ID
SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"  # 官方桌面重定向URI

def _post(url, data=None, headers=None):
    """简单POST请求"""
    body = urllib.parse.urlencode(data).encode() if data else b""
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def start_device_code(client_id=None):
    """开始设备码流程(v1.0)，返回 {user_code, verification_uri, device_code, interval}"""
    cid = client_id or CLIENT_ID
    data = {
        "client_id": cid,
        "scope": SCOPE,
    }
    r = _post("https://login.live.com/oauth20_token.srf", data)
    return {
        "user_code": r["user_code"],
        "verification_uri": r["verification_url"],
        "device_code": r["device_code"],
        "interval": r.get("interval", 5),
        "expires_in": r.get("expires_in", 900),
    }


def poll_token(device_code, client_id=None, interval=5):
    """轮询获取MSA access token(v1.0)。用户登录后返回 {access_token, refresh_token}"""
    cid = client_id or CLIENT_ID
    data = {
        "client_id": cid,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "code": device_code,
        "resource": "https://user.auth.xboxlive.com",
    }
    r = _post("https://login.live.com/oauth20_token.srf", data)
    return r


def get_auth_url(client_id=None, redirect_uri=None):
    """生成授权码流程的登录URL（PCL2方式）"""
    cid = client_id or CLIENT_ID
    rd = redirect_uri or REDIRECT_URI
    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": rd,
        "scope": SCOPE,
        "response_mode": "query",
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
        "resource": "https://user.auth.xboxlive.com",
    }
    r = _post("https://login.live.com/oauth20_token.srf", data)
    return r


def xbox_auth(msa_token):
    """MSA token → Xbox Live token。v1.0用t=前缀"""
    data = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": f"t={msa_token}",
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
        "Properties": {"SandboxId": "RETAIL", "UserToken": xbox_token},
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
