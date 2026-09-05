#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协议包 ID 表自动生成器。
从官方 PrismarineJS/minecraft-data 生成，杜绝手抄错误。
用法:
  python tools/gen_packets.py --data ./minecraft-data --output core/packets_auto.py
  python tools/gen_packets.py --download  # 自动下载 minecraft-data
"""
import argparse
import json
import os
import sys
import urllib.request
import zipfile
import tempfile
import shutil


def download_minecraft_data(dest_dir: str):
    url = "https://github.com/PrismarineJS/minecraft-data/archive/refs/heads/master.zip"
    print(f"[*] 下载 minecraft-data: {url}")
    zip_path = os.path.join(tempfile.gettempdir(), "minecraft-data.zip")
    urllib.request.urlretrieve(url, zip_path)
    print(f"[*] 解压到 {dest_dir}")
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(dest_dir)
    extracted = os.path.join(dest_dir, "minecraft-data-master")
    return extracted if os.path.exists(extracted) else dest_dir


def get_proto_version(data_dir: str, version: str) -> int:
    vpath = os.path.join(data_dir, "data", "pc", version, "version.json")
    if os.path.exists(vpath):
        with open(vpath, 'r', encoding='utf-8') as f:
            return json.load(f).get("version", 0)
    return 0


def extract_packets(protocol_data: dict) -> dict:
    """从 protocol.json 提取各阶段包 ID: {stage: {direction: {name: pid_int}}}"""
    result = {}
    for stage in ["handshaking", "status", "login", "configuration", "play"]:
        stage_data = protocol_data.get(stage)
        if not isinstance(stage_data, dict):
            continue
        result[stage] = {"toServer": {}, "toClient": {}}
        for direction in ["toServer", "toClient"]:
            dir_data = stage_data.get(direction)
            if not isinstance(dir_data, dict):
                continue
            types = dir_data.get("types", {})
            packet_def = types.get("packet")
            if not isinstance(packet_def, list) or len(packet_def) < 2:
                continue
            try:
                fields = packet_def[1]
                if not isinstance(fields, list) or len(fields) == 0:
                    continue
                name_field = fields[0]
                type_info = name_field.get("type", [])
                if isinstance(type_info, list) and len(type_info) > 1:
                    mapper = type_info[1]
                    mappings = mapper.get("mappings", {})
                    for pid_hex, name in mappings.items():
                        try:
                            pid = int(pid_hex, 16) if pid_hex.startswith("0x") else int(pid_hex)
                            result[stage][direction][name] = pid
                        except ValueError:
                            pass
            except Exception:
                continue
    return result


def generate_auto_tables(data_dir: str, output_path: str):
    versions_dir = os.path.join(data_dir, "data", "pc")
    if not os.path.exists(versions_dir):
        print(f"[!] 找不到版本目录: {versions_dir}")
        return False

    versions = sorted([d for d in os.listdir(versions_dir)
                       if os.path.isdir(os.path.join(versions_dir, d))])
    print(f"[*] 找到 {len(versions)} 个版本")

    # 按协议号去重：同一协议号只保留第一个有 protocol.json 的版本
    proto_to_packets = {}
    proto_to_version = {}
    for version in versions:
        proto = get_proto_version(data_dir, version)
        if proto == 0 or proto in proto_to_packets:
            continue
        protocol_path = os.path.join(data_dir, "data", "pc", version, "protocol.json")
        if not os.path.exists(protocol_path):
            continue
        with open(protocol_path, 'r', encoding='utf-8') as f:
            protocol_data = json.load(f)
        packets = extract_packets(protocol_data)
        if packets and packets.get("play", {}).get("toServer"):
            proto_to_packets[proto] = packets
            proto_to_version[proto] = version
            print(f"  - 协议 {proto} ({version}): play.toServer={len(packets['play']['toServer'])} 包")

    print(f"[*] 共 {len(proto_to_packets)} 个协议版本")

    content = f'''# -*- coding: utf-8 -*-
"""
自动生成的协议包 ID 表（从官方 minecraft-data）。
生成时间: {__import__('datetime').datetime.now().isoformat()}
协议版本数: {len(proto_to_packets)}
不要手动编辑此文件，运行 python tools/gen_packets.py --download 重新生成。
"""

PACKET_TABLES_AUTO = {json.dumps(proto_to_packets, ensure_ascii=False, indent=2)}
'''
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[*] 已生成: {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="minecraft-data 本地路径")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", default="core/packets_auto.py")
    args = parser.parse_args()

    data_dir = args.data
    if args.download or not data_dir:
        dest = os.path.join(tempfile.gettempdir(), "mcscanner_mcdata")
        if os.path.exists(dest):
            shutil.rmtree(dest)
        data_dir = download_minecraft_data(dest)

    if not data_dir or not os.path.exists(data_dir):
        print("[!] 请提供 --data 路径或使用 --download")
        sys.exit(1)

    success = generate_auto_tables(data_dir, args.output)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
