# -*- coding: utf-8 -*-
"""
收藏管理模块。
JSON 文件存储，支持标签、备注、自动重查、导入导出。
融合 a4v3l1 的收藏管理体验，融入 v3Pro 的扫描引擎。
"""
import json
import os
import threading
from datetime import datetime
from typing import Optional

from core.probe import slp_probe

_LOCK = threading.Lock()
_DEFAULT_PATH = "favorites.json"


def _default_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _DEFAULT_PATH)


def load_favorites(path: str = None) -> list:
    """加载收藏列表，返回 [{ip, port, tags, note, added_at, last_check, last_info}, ...]"""
    path = path or _default_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "favorites" in data:
            return data["favorites"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def save_favorites(favorites: list, path: str = None):
    """保存收藏列表到 JSON 文件。"""
    path = path or _default_path()
    with _LOCK:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(favorites, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[!] 收藏保存失败: {e}")


def _find(favorites: list, ip: str, port: int) -> int:
    for i, fav in enumerate(favorites):
        if fav.get("ip") == ip and fav.get("port") == port:
            return i
    return -1


def add_favorite(ip: str, port: int, tags: list = None, note: str = "",
                 info: dict = None, path: str = None) -> dict:
    """添加收藏。已存在则更新标签和备注。"""
    favorites = load_favorites(path)
    idx = _find(favorites, ip, port)
    now = datetime.now().isoformat()
    if idx >= 0:
        fav = favorites[idx]
        if tags is not None:
            fav["tags"] = tags
        if note:
            fav["note"] = note
        if info:
            fav["last_info"] = info
            fav["last_check"] = now
    else:
        fav = {
            "ip": ip,
            "port": port,
            "tags": tags or [],
            "note": note,
            "added_at": now,
            "last_check": now if info else None,
            "last_info": info or None,
        }
        favorites.append(fav)
    save_favorites(favorites, path)
    return fav


def remove_favorite(ip: str, port: int, path: str = None) -> bool:
    """移除收藏。返回是否成功移除。"""
    favorites = load_favorites(path)
    idx = _find(favorites, ip, port)
    if idx < 0:
        return False
    favorites.pop(idx)
    save_favorites(favorites, path)
    return True


def update_tags(ip: str, port: int, tags: list, path: str = None) -> Optional[dict]:
    """更新收藏的标签。"""
    favorites = load_favorites(path)
    idx = _find(favorites, ip, port)
    if idx < 0:
        return None
    favorites[idx]["tags"] = tags
    save_favorites(favorites, path)
    return favorites[idx]


def update_note(ip: str, port: int, note: str, path: str = None) -> Optional[dict]:
    """更新收藏的备注。"""
    favorites = load_favorites(path)
    idx = _find(favorites, ip, port)
    if idx < 0:
        return None
    favorites[idx]["note"] = note
    save_favorites(favorites, path)
    return favorites[idx]


def is_favorite(ip: str, port: int, path: str = None) -> bool:
    """检查是否已收藏。"""
    return _find(load_favorites(path), ip, port) >= 0


def rescan_one(ip: str, port: int, timeout: float = 5.0, path: str = None) -> Optional[dict]:
    """重新探测单个收藏服务器，更新 last_info 和 last_check。"""
    info = slp_probe(ip, port, timeout=timeout)
    if not info or info.get("state") != "up":
        info = {"state": "offline", "error": info.get("error", "") if info else "unreachable"}
    favorites = load_favorites(path)
    idx = _find(favorites, ip, port)
    if idx >= 0:
        favorites[idx]["last_check"] = datetime.now().isoformat()
        favorites[idx]["last_info"] = {k: v for k, v in info.items() if k != "_raw"}
        save_favorites(favorites, path)
    return info


def rescan_all(timeout: float = 5.0, workers: int = 10, path: str = None,
               progress_callback=None) -> list:
    """重新探测所有收藏服务器。返回更新后的收藏列表。"""
    import concurrent.futures
    favorites = load_favorites(path)
    if not favorites:
        return []
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for fav in favorites:
            fut = ex.submit(slp_probe, fav["ip"], fav["port"], timeout)
            futures[fut] = (fav["ip"], fav["port"])
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            ip, port = futures[fut]
            try:
                info = fut.result()
                if info and info.get("state") == "up":
                    results[(ip, port)] = {k: v for k, v in info.items() if k != "_raw"}
                else:
                    results[(ip, port)] = {"state": "offline"}
            except Exception:
                results[(ip, port)] = {"state": "error"}
            done += 1
            if progress_callback:
                progress_callback(done, len(favorites))
    now = datetime.now().isoformat()
    for fav in favorites:
        key = (fav["ip"], fav["port"])
        if key in results:
            fav["last_check"] = now
            fav["last_info"] = results[key]
    save_favorites(favorites, path)
    return favorites


def import_from_file(filepath: str, path: str = None) -> int:
    """从文本文件导入收藏（每行 ip:port）。"""
    if not os.path.exists(filepath):
        return 0
    count = 0
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if ':' in line:
                parts = line.rsplit(':', 1)
                ip, port = parts[0], int(parts[1])
            else:
                ip, port = line, 25565
            add_favorite(ip, port, path=path)
            count += 1
    return count


def get_all_tags(path: str = None) -> list:
    """获取所有标签（去重排序）。"""
    favorites = load_favorites(path)
    tags = set()
    for fav in favorites:
        for t in fav.get("tags", []):
            tags.add(t)
    return sorted(tags)


def filter_favorites(tag: str = None, search: str = None, path: str = None) -> list:
    """按标签或关键词筛选收藏。"""
    favorites = load_favorites(path)
    result = []
    for fav in favorites:
        if tag and tag not in fav.get("tags", []):
            continue
        if search:
            haystack = f"{fav['ip']}:{fav['port']} {fav.get('note', '')} {' '.join(fav.get('tags', []))}"
            info = fav.get("last_info") or {}
            haystack += f" {info.get('version', '')} {info.get('motd', '')}"
            if search.lower() not in haystack.lower():
                continue
        result.append(fav)
    return result
