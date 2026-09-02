# -*- coding: utf-8 -*-
"""
警告业务服务。
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import config
import logger
from core.bot import join_and_warn, DEFAULT_WARNING_MESSAGES, MCBot
from scanner.engine import ScanEngine
from storage import db
from service import parse_and_filter_targets


def _get_messages(messages=None, message_file=None):
    """获取警告消息列表"""
    if messages:
        return messages if isinstance(messages, list) else [messages]
    if message_file and os.path.exists(message_file):
        with open(message_file, 'r', encoding='utf-8') as f:
            return [l.strip() for l in f if l.strip()]
    cfg = config.load_config()
    return cfg.get("messages") or DEFAULT_WARNING_MESSAGES


def warn_targets(targets_str: str, username=None, messages=None, message_file=None,
                 workers=None, bot_workers=None, timeout=None, message_delay=None,
                 authme_password=None, rate=0, exclude_file=None, db_path=None,
                 stop_event=None) -> list:
    """完整警告流程：扫描发现离线服 → 登录发警告"""
    cfg = config.load_config()
    messages = _get_messages(messages, message_file)
    targets, total = parse_and_filter_targets(targets_str, exclude_file=exclude_file)
    if not targets:
        logger.warning("没有有效目标")
        return []

    engine = ScanEngine(
        db_path=db_path or cfg["db_path"],
        workers=workers or cfg["workers"],
        timeout=timeout or cfg["timeout"],
        auth_check=True,
        rate_limit=rate,
        bot_workers=bot_workers or cfg["bot_threads"],
        bot_timeout=cfg["bot_timeout"],
        stop_event=stop_event,
    )
    results = engine.warn_targets(
        iter(targets),
        username=username or cfg["username"],
        messages=messages,
        message_delay=message_delay or cfg["message_delay"],
        authme_password=authme_password or cfg.get("authme_password") or None,
    )
    success = sum(1 for r in results if r.success)
    msg_sent = sum(r.messages_sent for r in results)
    logger.info(f"警告完成: 成功登录 {success}/{len(results)}, 发送消息 {msg_sent} 条")
    return results


def warn_from_db(auth="cracked", modded=None, search=None, limit=0,
                 username=None, messages=None, message_file=None,
                 workers=5, message_delay=None, authme_password=None,
                 db_path=None) -> list:
    """从数据库已扫描结果直接发警告，不重新扫描"""
    cfg = config.load_config()
    db_path = db_path or cfg["db_path"]
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    messages = _get_messages(messages, message_file)
    rows = db.query(db_path, auth=auth, modded=modded, search=search,
                    limit=limit or 100000, offset=0)
    if not rows:
        logger.warning("数据库中没有符合条件的服务器")
        return []

    logger.info(f"从数据库读取 {len(rows)} 个服务器，开始发送警告")
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for row in rows:
            ip = row.get('ip')
            port = row.get('port', 25565)
            if not ip:
                continue
            fut = ex.submit(join_and_warn, ip, port,
                            username or cfg["username"], messages,
                            cfg["bot_timeout"], message_delay or cfg["message_delay"],
                            None, authme_password or cfg.get("authme_password") or None)
            futures[fut] = (ip, port)
        for i, fut in enumerate(as_completed(futures), 1):
            ip, port = futures[fut]
            try:
                r = fut.result()
                results.append(r)
                if i % 10 == 0:
                    logger.info(f"警告进度: {i}/{len(rows)}")
            except Exception as e:
                from core.bot import BotResult
                results.append(BotResult(ip=ip, port=port, error=str(e)))
    success = sum(1 for r in results if r.success)
    msg_sent = sum(r.messages_sent for r in results)
    logger.info(f"警告完成: 成功 {success}/{len(results)}, 发送消息 {msg_sent} 条")
    return results


def warn_single(ip: str, port: int = 25565, username=None, messages=None,
                message_delay=0.8, authme_password=None, timeout=15.0):
    """对单个服务器发警告"""
    cfg = config.load_config()
    messages = _get_messages(messages)
    logger.info(f"单服务器警告: {ip}:{port}")
    result = join_and_warn(
        ip, port,
        username=username or cfg["username"],
        messages=messages,
        timeout=timeout,
        message_delay=message_delay,
        authme_password=authme_password or None,
    )
    return result


def warn_multi_bots(ip: str, port: int = 25565, bot_count=5, name_prefix="SecurityBot",
                    messages=None, message_delay=0.5, authme_password=None) -> list:
    """多机器人同时警告单个服务器（有硬上限防止滥用）"""
    cfg = config.load_config()
    max_bots = cfg.get("warn_bot_max", 20)
    bot_count = min(bot_count, max_bots)
    messages = _get_messages(messages)
    logger.info(f"多机器人警告: {bot_count}个机器人 -> {ip}:{port}")

    results = []
    with ThreadPoolExecutor(max_workers=min(bot_count, max_bots)) as ex:
        futures = []
        for i in range(bot_count):
            name = f"{name_prefix}_{i+1:02d}"
            fut = ex.submit(join_and_warn, ip, port, name, messages,
                            15.0, message_delay, None, authme_password or None)
            futures.append((name, fut))
        for name, fut in futures:
            try:
                r = fut.result()
                results.append({"name": name, "success": r.success,
                                "messages_sent": r.messages_sent, "error": r.error})
            except Exception as e:
                results.append({"name": name, "success": False, "error": str(e)[:100]})
    success_count = sum(1 for r in results if r["success"])
    total_messages = sum(r["messages_sent"] for r in results)
    logger.info(f"多机器人警告完成: {success_count}/{bot_count}成功, 共{total_messages}条消息")
    return results


def send_command(command: str, ip: str, port: int = 25565, username=None,
                 authme_password=None, hold=3.0):
    """登录服务器并发送命令"""
    cfg = config.load_config()
    logger.info(f"发送命令: {command} -> {ip}:{port}")
    bot = MCBot(host=ip, port=port, username=username or cfg["username"])
    try:
        bot.connect()
        if authme_password:
            bot.authme_login(authme_password, register=False)
        bot.send_command(command)
        bot.keep_alive(hold)
        auth_mode = getattr(bot, 'auth_mode', 'unknown')
        return {"success": True, "command": command, "auth_mode": auth_mode}
    except Exception as e:
        logger.error(f"发送命令失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        bot.close()
