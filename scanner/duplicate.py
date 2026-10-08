# -*- coding: utf-8 -*-
"""
重复服务器检测（v3.2.1 新增，融合 matscan 特性）。
识别同一台服务器在多个端口/IP上运行的情况。
基于 MOTD + 版本 + 最大玩家数 + 协议号 + favicon 等指纹进行匹配。
支持精确指纹匹配和软指纹匹配（宽松匹配）。
"""
import hashlib
import re
import threading


def compute_server_fingerprint(result: dict) -> str:
    """
    计算服务器的精确指纹（用于重复检测）。
    基于：MOTD文本 + 版本名 + 最大玩家数 + 协议号 + favicon(前100字符)
    """
    motd = _normalize_text(result.get("motd", ""))
    version = _normalize_text(result.get("version", ""))
    max_players = result.get("players_max", result.get("max", 0))
    proto = result.get("proto", 0)
    favicon = (result.get("favicon", "") or "")[:100]

    raw = f"{motd}|{version}|{max_players}|{proto}|{favicon}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def compute_soft_fingerprint(result: dict) -> str:
    """
    计算软指纹（宽松匹配，用于发现可能的重复）。
    仅基于：MOTD文本（去颜色码和动态内容）+ 最大玩家数。
    """
    motd = _normalize_text(result.get("motd", ""))
    # 去除常见的动态部分（玩家数、时间等）
    motd = re.sub(r"\d+/\d+", "", motd)
    motd = re.sub(r"\d{1,2}:\d{2}", "", motd)
    max_players = result.get("players_max", result.get("max", 0))
    raw = f"{motd.strip()}|{max_players}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class DuplicateDetector:
    """重复服务器检测器。"""

    def __init__(self):
        self.fingerprints = {}      # {fingerprint: [result, ...]}
        self.soft_fingerprints = {}  # {soft_fingerprint: [result, ...]}
        self.duplicates = []         # 检测到的重复组
        # "ip:port" -> {duplicates 下标}。子集关系的两个组必然共享至少一个服务器，
        # 所以可用索引定位候选组，避免 _record_duplicate 每次全表扫描（O(n²)）。
        # 一个 key 可能属于多个组（合并前后），必须保存集合，否则会漏掉候选组。
        self._group_index = {}
        # add() 由多 worker 线程并发调用（engine._run_batch），必须串行化
        self._lock = threading.Lock()

    def add(self, result: dict):
        """添加一个扫描结果，检测重复。"""
        fp = compute_server_fingerprint(result)
        soft_fp = compute_soft_fingerprint(result)

        result["_fingerprint"] = fp
        result["_soft_fingerprint"] = soft_fp

        with self._lock:
            # 精确指纹匹配
            if fp in self.fingerprints:
                self.fingerprints[fp].append(result)
                self._record_duplicate(self.fingerprints[fp], "exact")
            else:
                self.fingerprints[fp] = [result]

            # 软指纹匹配（可能的重复）
            if soft_fp in self.soft_fingerprints:
                existing = self.soft_fingerprints[soft_fp]
                existing_fps = {r.get("_fingerprint") for r in existing}
                if fp not in existing_fps:
                    existing.append(result)
                    if len(existing) > 1:
                        self._record_duplicate(existing, "soft")
            else:
                self.soft_fingerprints[soft_fp] = [result]

    def get_duplicates(self) -> list:
        """获取所有重复服务器组。"""
        with self._lock:
            return list(self.duplicates)

    def get_unique(self) -> list:
        """获取去重后的服务器列表（每组保留第一个）。"""
        with self._lock:
            return [results[0] for results in self.fingerprints.values() if results]

    def stats(self) -> dict:
        """获取重复检测统计。"""
        with self._lock:
            total = sum(len(v) for v in self.fingerprints.values())
            unique = len(self.fingerprints)
            return {
                "total_servers": total,
                "unique_servers": unique,
                "duplicate_groups": len(self.duplicates),
                "duplicate_count": total - unique,
            }

    @staticmethod
    def _server_key(item) -> str:
        if isinstance(item, dict):
            return f"{item.get('ip')}:{item.get('port')}"
        return f"{item['ip']}:{item['port']}"

    def _reindex_group(self, idx: int, servers: list):
        """把组内服务器写入索引（组只会变大或保持，旧键无需清理）"""
        for item in servers:
            self._group_index.setdefault(self._server_key(item), set()).add(idx)

    def _record_duplicate(self, group: list, match_type: str):
        """记录一组重复服务器。如果已有子集组，则更新为更大的组。"""
        group_servers = set(self._server_key(r) for r in group)
        # 用索引定位候选组（子集关系的两组必然共享服务器）；
        # 按下标升序处理，与旧实现"取第一个匹配组"的语义保持一致
        candidates = set()
        for k in group_servers:
            candidates |= self._group_index.get(k, set())
        candidates = sorted(candidates)
        for i in candidates:
            if i >= len(self.duplicates):
                continue
            existing = self.duplicates[i]
            existing_servers = set(self._server_key(s) for s in existing["servers"])
            if existing_servers.issubset(group_servers) or group_servers.issubset(existing_servers):
                # 合并：保留更大的组
                merged_servers = group if len(group) >= len(existing["servers"]) else existing["servers"]
                self.duplicates[i] = {
                    "match_type": match_type,
                    "fingerprint": group[0].get("_fingerprint", ""),
                    "servers": [{"ip": r.get("ip"), "port": r.get("port"),
                                 "motd": r.get("motd", ""), "version": r.get("version", "")}
                                for r in merged_servers],
                }
                self._reindex_group(i, merged_servers)
                return
        self.duplicates.append({
            "match_type": match_type,
            "fingerprint": group[0].get("_fingerprint", ""),
            "servers": [{"ip": r.get("ip"), "port": r.get("port"),
                         "motd": r.get("motd", ""), "version": r.get("version", "")}
                        for r in group],
        })
        self._reindex_group(len(self.duplicates) - 1, group)


def _normalize_text(text) -> str:
    """标准化文本：去除颜色码、多余空格、转小写。"""
    if not text:
        return ""
    # motd 可能是 dict/其他类型（远端可控），先转 str，否则 re.sub 抛 TypeError 使重复检测失效
    if not isinstance(text, str):
        text = str(text)
    text = re.sub(r"§[0-9a-fk-or]", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text
