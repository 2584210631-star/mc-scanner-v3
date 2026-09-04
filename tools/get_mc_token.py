#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 正版 Token 获取工具（Microsoft 设备码授权）
用法: python3 tools/get_mc_token.py
流程: 设备码 -> 浏览器登录微软账号 -> 获取 access token -> Mojang 验证 -> 保存 token
"""
import json
import sys
import time
import urllib.request
import urllib.parse

# Minecraft Java 版官方 Azure 应用 ID
CLIENT_ID = "00000000402b5328"
SCOPE = "XboxLive.signin offline_access"


def http_post(url, data, headers=None):
    if headers is None:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def http_post_json(url, data, headers=None):
    if headers is None:
        headers = {"Content-Type": "application/json"}
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def step1_device_code():
    """步骤1: 获取设备码"""
    print("[1/5] 请求设备码...")
    data = {
        "client_id": CLIENT_ID,
        "scope": SCOPE,
    }
    resp = http_post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode", data)
    print(f"\n请在浏览器打开: {resp['verification_uri']}")
    print(f"输入验证码: {resp['user_code']}")
    print(f"\n(页面打开后登录你的微软账号，输入上面的验证码并授权)")
    return resp["device_code"], int(resp["interval"])


def step2_poll_token(device_code, interval):
    """步骤2: 轮询获取 Microsoft access token"""
    print("\n[2/5] 等待浏览器授权...")
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": CLIENT_ID,
        "device_code": device_code,
    }
    while True:
        time.sleep(interval)
        try:
            resp = http_post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token", data)
            if "access_token" in resp:
                print("  授权成功!")
                return resp["access_token"], resp.get("refresh_token", "")
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode())
            error = body.get("error", "")
            if error == "authorization_pending":
                print("  等待中... (请在浏览器完成登录)")
                continue
            elif error == "slow_down":
                interval += 2
                continue
            elif error == "expired_token":
                print("  设备码已过期，请重新运行")
                sys.exit(1)
            else:
                print(f"  错误: {error} - {body.get('error_description', '')}")
                sys.exit(1)


def step3_xbox_live(ms_access_token):
    """步骤3: 用 Microsoft token 换 Xbox Live token"""
    print("[3/5] 登录 Xbox Live...")
    data = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": f"d={ms_access_token}",
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }
    resp = http_post_json("https://user.auth.xboxlive.com/user/authenticate", data)
    return resp["Token"], resp["DisplayClaims"]["xui"][0]["uhs"]


def step4_xsts(xbl_token):
    """步骤4: 用 Xbox Live token 换 XSTS token"""
    print("[4/5] 获取 XSTS token...")
    data = {
        "Properties": {
            "SandboxId": "RETAIL",
            "UserTokens": [xbl_token],
        },
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    try:
        resp = http_post_json("https://xsts.auth.xboxlive.com/xsts/authorize", data)
        return resp["Token"], resp["DisplayClaims"]["xui"][0]["uhs"]
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        if body.get("XErr") == 2148916233:
            print("  错误: 该微软账号没有购买 Minecraft Java 版!")
        elif body.get("XErr") == 2148916235:
            print("  错误: 该账号所在地区不支持 Xbox Live")
        else:
            print(f"  XSTS 错误: {body}")
        sys.exit(1)


def step5_minecraft_token(xsts_token, uhs):
    """步骤5: 用 XSTS token 换 Minecraft access token"""
    print("[5/5] 获取 Minecraft access token...")
    data = {"identityToken": f"XBL3.0 x={uhs};{xsts_token}"}
    resp = http_post_json("https://api.minecraftservices.com/authentication/login_with_xbox", data)
    mc_access_token = resp["access_token"]

    # 获取玩家信息
    req = urllib.request.Request(
        "https://api.minecraftservices.com/minecraft/profile",
        headers={"Authorization": f"Bearer {mc_access_token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        profile = json.loads(r.read().decode())

    return mc_access_token, profile


def main():
    print("=" * 60)
    print("Minecraft 正版 Token 获取工具")
    print("=" * 60)
    print()

    device_code, interval = step1_device_code()
    ms_token, refresh_token = step2_poll_token(device_code, interval)
    xbl_token, uhs = step3_xbox_live(ms_token)
    xsts_token, uhs = step4_xsts(xbl_token)
    mc_token, profile = step5_minecraft_token(xsts_token, uhs)

    print()
    print("=" * 60)
    print("获取成功!")
    print(f"玩家名: {profile['name']}")
    print(f"UUID: {profile['id']}")
    print(f"Minecraft Access Token: {mc_token[:50]}...")
    print("=" * 60)

    # 保存到文件
    result = {
        "username": profile["name"],
        "uuid": profile["id"],
        "access_token": mc_token,
        "refresh_token": refresh_token,
        "expires_at": int(time.time()) + 86400,  # 约24小时
    }
    out_path = "minecraft_token.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n已保存到: {out_path}")
    print("注意: token 有效期约24小时，refresh_token 可用于刷新")


if __name__ == "__main__":
    main()
