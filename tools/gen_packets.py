#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协议包 ID 表自动生成器。
从官方 PrismarineJS/minecraft-data 生成，杜绝手抄错误。
用法:
  python tools/gen_packets.py --data ./minecraft-data --output packets_auto.py
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
    """下载 minecraft-data 仓库"""
    url = "https://github.com/PrismarineJS/minecraft-data/archive/refs/heads/master.zip"
    print(f"[*] 下载 minecraft-data: {url}")
    zip_path = os.path.join(tempfile.gettempdir(), "minecraft-data.zip")
    urllib.request.urlretrieve(url, zip_path)
    print(f"[*] 解压到 {dest_dir}")
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(dest_dir)
    # 找到实际目录
    extracted = os.path.join(dest_dir, "minecraft-data-master")
    if os.path.exists(extracted):
        return extracted
    return dest_dir


def parse_protocol_json(data_dir: str, version: str) -> dict:
    """解析指定版本的 protocol.json"""
    protocol_path = os.path.join(data_dir, "data", "pc", version, "protocol.json")
    if not os.path.exists(protocol_path):
        return {}
    with open(protocol_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def extract_packets(protocol_data: dict) -> dict:
    """从 protocol.json 提取各阶段包 ID"""
    result = {}
    types = protocol_data.get("types", {})

    for stage in ["handshaking", "status", "login", "configuration", "play"]:
        stage_data = types.get(stage, {})
        if not stage_data:
            continue
        result[stage] = {"toServer": {}, "toClient": {}}

        for direction in ["toServer", "toClient"]:
            packet_type = stage_data.get(direction, [])
            if isinstance(packet_type, list) and len(packet_type) > 1:
                mapper = packet_type[1]
                if isinstance(mapper, dict) and "mappings" in mapper:
                    for name, pid in mapper["mappings"].items():
                        result[stage][direction][name] = pid
    return result


def generate_auto_tables(data_dir: str, output_path: str):
    """生成 packets_auto.py"""
    versions_dir = os.path.join(data_dir, "data", "pc")
    if not os.path.exists(versions_dir):
        print(f"[!] 找不到版本目录: {versions_dir}")
        return False

    versions = sorted([d for d in os.listdir(versions_dir)
                       if os.path.isdir(os.path.join(versions_dir, d))])
    print(f"[*] 找到 {len(versions)} 个版本")

    tables = {}
    for version in versions:
        protocol_data = parse_protocol_json(data_dir, version)
        if not protocol_data:
            continue
        packets = extract_packets(protocol_data)
        if packets:
            tables[version] = packets
            print(f"  - {version}: {sum(len(v) for s in packets.values() for v in s.values())} 个包")

    # 生成 Python 文件
    content = f'''# -*- coding: utf-8 -*-
"""
自动生成的协议包 ID 表。
来源: PrismarineJS/minecraft-data
生成时间: {__import__('datetime').datetime.now().isoformat()}
版本数: {len(tables)}
"""

PACKET_TABLES_AUTO = {json.dumps(tables, ensure_ascii=False, indent=2)}
'''
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[*] 已生成: {output_path} ({len(tables)} 个版本)")
    return True


def main():
    parser = argparse.ArgumentParser(description="协议包 ID 表自动生成器")
    parser.add_argument("--data", help="minecraft-data 本地路径")
    parser.add_argument("--download", action="store_true", help="自动下载 minecraft-data")
    parser.add_argument("--output", default="packets_auto.py", help="输出文件路径")
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
