# -*- coding: utf-8 -*-
"""微软/Minecraft正版认证模块。
Azure AD v2.0 设备码流程 + RSA/AES加密握手。
用Azure CLI官方client_id，支持v2.0端点。
"""
import json
import os
import time
import struct
import hashlib
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


def xbox_auth(msa_token):
    """MSA token → Xbox Live token。v2.0 JWT直接用，v1.0加t=前缀"""
    # v2.0返回的是JWT（eyJ开头），直接用；v1.0短token加t=前缀
    rps_ticket = msa_token if msa_token.startswith("eyJ") else f"t={msa_token}"
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
