# -*- coding: utf-8 -*-
"""
全局统一配置模块。
消除 cli.py / web/app.py 各处硬编码默认值，所有模块从这里取配置。
"""
import json
import os

DEFAULT_CONFIG = {
    "username": "SecurityBot",
    "messages": None,
    "ports": [25565],
    "scan_threads": 200,
    "scan_timeout": 2.5,
    "workers": 32,            # SLP探测线程数
    "timeout": 4.0,           # SLP探测超时
    "bot_threads": 10,
    "bot_timeout": 12,
    "message_delay": 0.8,
    "retry_count": 1,
    "rate": 0,
    "authme_password": "",
    "exclude_file": "exclude.conf",
    "db_path": "mcscanner.db",
    "auto_save_db": True,
    "output_format": "json",
    "output_file": None,
    "web_host": "127.0.0.1",
    "web_port": 8080,
    "web_token": "",          # Web面板访问token，空=不启用认证
    "log_level": "INFO",
    "warn_bot_max": 20,       # 多机器人警告硬上限，防止滥用
    # v3.3 新增
    "discord_webhook": "",     # Discord Webhook URL，空=不启用通知
    "rescan_enabled": False,   # 智能重扫（玩家历史追踪+动态重扫频率）
    "duplicate_detection": False,  # 重复服务器检测
    # AI 内容生成
    "ai_api_key": "",          # AI API Key（OpenAI兼容）
    "ai_base_url": "https://api.openai.com/v1",  # AI API 地址
    "ai_model": "gpt-3.5-turbo",  # AI 模型名
}

_GLOBAL_CFG = None
_CONFIG_PATH = None


def load_config(path: str = None) -> dict:
    """加载配置文件，合并到默认配置。重复调用返回缓存。"""
    global _GLOBAL_CFG, _CONFIG_PATH
    if _GLOBAL_CFG is not None and (path is None or path == _CONFIG_PATH):
        return _GLOBAL_CFG

    cfg = DEFAULT_CONFIG.copy()
    config_path = path or "config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            cfg.update(user_cfg)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[!] 配置文件读取失败，使用默认配置: {e}")
    _GLOBAL_CFG = cfg
    _CONFIG_PATH = config_path
    return cfg


def get(key: str, default=None):
    """获取单个配置项，自动加载默认配置。"""
    if _GLOBAL_CFG is None:
        load_config()
    return _GLOBAL_CFG.get(key, default)


def set(key: str, value):
    """运行时覆盖单个配置项（不写入文件）。"""
    if _GLOBAL_CFG is None:
        load_config()
    _GLOBAL_CFG[key] = value


def get_all() -> dict:
    """返回全部配置的副本。"""
    if _GLOBAL_CFG is None:
        load_config()
    return dict(_GLOBAL_CFG)


def save_config(cfg: dict = None, path: str = None) -> bool:
    """保存配置到文件。cfg为None则保存当前内存配置。"""
    if _GLOBAL_CFG is None:
        load_config()
    data = cfg if cfg is not None else _GLOBAL_CFG
    target = path or _CONFIG_PATH or "config.json"
    try:
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _GLOBAL_CFG.update(data)
        return True
    except Exception as e:
        print(f"[!] 保存配置失败: {e}")
        return False


def reload_config(path: str = None) -> dict:
    """强制重新加载配置文件。"""
    global _GLOBAL_CFG, _CONFIG_PATH
    _GLOBAL_CFG = None
    _CONFIG_PATH = None
    return load_config(path)
