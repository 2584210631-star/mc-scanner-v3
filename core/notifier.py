# -*- coding: utf-8 -*-
"""
邮件通知模块。
扫描完成后发送结果摘要到指定邮箱。
支持 SMTP SSL/TLS，兼容 QQ邮箱、163邮箱、Gmail等。
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime


def send_email(subject, body, html=False, cfg=None):
    """
    发送邮件。
    cfg: 配置字典，需包含 smtp_host, smtp_port, smtp_ssl, username, password, from, to
    返回: (success: bool, error: str)
    """
    if cfg is None:
        import config
        cfg = {
            "smtp_host": config.get("email_smtp_host", ""),
            "smtp_port": config.get("email_smtp_port", 465),
            "smtp_ssl": config.get("email_smtp_ssl", True),
            "username": config.get("email_username", ""),
            "password": config.get("email_password", ""),
            "from": config.get("email_from", "") or config.get("email_username", ""),
            "to": config.get("email_to", ""),
        }

    if not cfg.get("smtp_host") or not cfg.get("username") or not cfg.get("password") or not cfg.get("to"):
        return False, "邮件配置不完整（需要SMTP服务器、账号、密码、收件人）"

    try:
        msg = MIMEMultipart()
        # 发件人格式：显示名 <邮箱地址>，163/QQ等要求From必须包含真实邮箱
        from_name = cfg.get("from") or cfg["username"]
        from_addr = cfg["username"]
        msg["From"] = formataddr((from_name, from_addr))
        msg["To"] = Header(cfg["to"], "utf-8")
        msg["Subject"] = Header(subject, "utf-8")

        mime_type = "html" if html else "plain"
        msg.attach(MIMEText(body, mime_type, "utf-8"))

        if cfg.get("smtp_ssl", True):
            server = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
        else:
            server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=30)
            server.starttls()

        server.login(cfg["username"], cfg["password"])
        recipients = [r.strip() for r in cfg["to"].split(",") if r.strip()]
        server.sendmail(cfg["username"], recipients, msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, str(e)


def build_scan_report(results, targets_count, duration_sec, task_id=None):
    """
    根据扫描结果生成邮件正文（HTML格式）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(results)
    # 统计
    online = [r for r in results if r.get("players_online", 0) and r.get("players_online", 0) > 0]
    cracked = [r for r in results if r.get("auth") == "cracked"]
    online_count = len(online)
    cracked_count = len(cracked)

    # 有人的服务器列表
    online_rows = ""
    for r in sorted(online, key=lambda x: x.get("players_online", 0), reverse=True)[:30]:
        ip = r.get("ip", "?")
        port = r.get("port", 25565)
        ver = r.get("version", "") or "?"
        players = f"{r.get('players_online', 0)}/{r.get('players_max', 0)}"
        motd = (r.get("motd") or "")[:40]
        auth = r.get("auth", "?")
        # 玩家列表
        sample = r.get("sample") or []
        if sample:
            names = [p.get("name", "") for p in sample if p.get("name")][:10]
            player_str = ", ".join(names)
            if len(sample) > 10:
                player_str += f" 等{len(sample)}人"
        else:
            player_str = "-"
        online_rows += f"""<tr>
            <td>{ip}:{port}</td><td>{ver}</td><td>{players}</td><td>{auth}</td><td>{motd}</td><td style="font-size:11px;color:#666;max-width:200px;word-break:break-all;">{player_str}</td>
        </tr>"""

    duration_str = f"{int(duration_sec//60)}分{int(duration_sec%60)}秒" if duration_sec > 60 else f"{int(duration_sec)}秒"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
body{{font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;color:#333}}
.container{{max-width:700px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
h1{{color:#1a73e8;font-size:22px;margin:0 0 16px}}
.stats{{display:flex;gap:16px;margin:16px 0}}
.stat{{flex:1;background:#f0f7ff;border-radius:8px;padding:16px;text-align:center}}
.stat .num{{font-size:28px;font-weight:bold;color:#1a73e8}}
.stat .label{{font-size:12px;color:#666;margin-top:4px}}
table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:13px}}
th{{background:#1a73e8;color:#fff;padding:8px;text-align:left}}
td{{padding:8px;border-bottom:1px solid #eee}}
tr:hover{{background:#f9f9f9}}
.footer{{margin-top:20px;padding-top:16px;border-top:1px solid #eee;color:#999;font-size:12px;text-align:center}}
</style></head><body>
<div class="container">
<h1>MC扫描完成通知</h1>
<p>扫描任务 #{task_id or '-'} 已于 {now} 完成。</p>
<div class="stats">
<div class="stat"><div class="num">{total}</div><div class="label">发现服务器</div></div>
<div class="stat"><div class="num">{online_count}</div><div class="label">有人在线</div></div>
<div class="stat"><div class="num">{cracked_count}</div><div class="label">离线/破解</div></div>
<div class="stat"><div class="num">{duration_str}</div><div class="label">耗时</div></div>
</div>
<p><strong>扫描目标数：</strong>{targets_count}</p>
"""
    if online_rows:
        html += f"""<h3 style="margin-top:20px;">有人的服务器（前30）</h3>
<table><tr><th>地址</th><th>版本</th><th>人数</th><th>验证</th><th>MOTD</th><th>在线玩家</th></tr>{online_rows}</table>"""
    else:
        html += "<p style='color:#999;margin-top:16px;'>本次扫描未发现有人的服务器。</p>"

    html += f"""<div class="footer">由 mc-scanner-v3 自动发送 | {now}</div>
</div></body></html>"""
    return html


def notify_scan_complete(results, targets_count, duration_sec, task_id=None):
    """扫描完成后发送邮件通知。失败不抛异常，只打印日志。"""
    try:
        import config
        if not config.get("email_enabled", False):
            return False, "邮件通知未启用"
        subject = f"[MC扫描] 发现{len(results)}个服务器，{len([r for r in results if r.get('players_online',0)>0])}个有人"
        body = build_scan_report(results, targets_count, duration_sec, task_id)
        ok, err = send_email(subject, body, html=True)
        if ok:
            print(f"[邮件通知] 发送成功 -> {config.get('email_to', '')}")
        else:
            print(f"[邮件通知] 发送失败: {err}")
        return ok, err
    except Exception as e:
        print(f"[邮件通知] 异常: {e}")
        return False, str(e)
