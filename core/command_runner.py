# -*- coding: utf-8 -*-
"""
命令执行器：Bot 登录服务器后自动执行预设命令列表。
支持条件执行（根据服务器响应决定下一步）、延迟控制、结果收集。

吸收自 MCPTool 的 "登录后执行命令列表" 功能。
"""
import time
import re
from dataclasses import dataclass, field
from typing import Optional, Callable

from .bot import MCBot


@dataclass
class CommandResult:
    """单条命令执行结果"""
    command: str
    success: bool = False
    response: str = ""
    error: str = ""
    duration: float = 0.0


@dataclass
class CommandScript:
    """命令脚本：按顺序执行的命令列表"""
    commands: list[str] = field(default_factory=list)
    delay: float = 1.0  # 命令间延迟
    timeout: float = 10.0  # 单条命令超时
    stop_on_error: bool = False  # 出错时是否停止

    @classmethod
    def from_file(cls, path: str, delay: float = 1.0) -> "CommandScript":
        """从文件加载命令脚本（每行一条命令，# 开头为注释）"""
        commands = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    commands.append(line)
        return cls(commands=commands, delay=delay)

    def add(self, command: str):
        """添加命令"""
        self.commands.append(command)

    def add_conditional(self, condition: str, command: str):
        """添加条件命令（简化版，实际执行时检查）"""
        self.commands.append(f"IF {condition} THEN {command}")


class CommandRunner:
    """命令执行器"""

    def __init__(self, bot: MCBot, delay: float = 1.0, timeout: float = 10.0):
        self.bot = bot
        self.delay = delay
        self.timeout = timeout
        self.results: list[CommandResult] = []
        self._chat_buffer: list[str] = []

    def run_script(self, script: CommandScript) -> list[CommandResult]:
        """执行命令脚本"""
        for cmd in script.commands:
            result = self.execute(cmd)
            self.results.append(result)
            if not result.success and script.stop_on_error:
                break
            time.sleep(script.delay)
        return self.results

    def execute(self, command: str) -> CommandResult:
        """执行单条命令"""
        result = CommandResult(command=command)
        start = time.time()
        try:
            # 条件命令处理
            if command.upper().startswith("IF "):
                result = self._execute_conditional(command)
            else:
                before = len(self.bot.chat_messages)
                self.bot.send_command(command)
                # 等待响应
                time.sleep(self.delay)
                result.success = True
                result.response = self._get_recent_chat(before)
        except Exception as e:
            result.error = str(e)
            result.success = False
        result.duration = time.time() - start
        return result

    def _execute_conditional(self, command: str) -> CommandResult:
        """执行条件命令：IF <关键词> THEN <命令>"""
        result = CommandResult(command=command)
        match = re.match(r'IF\s+(.+?)\s+THEN\s+(.+)', command, re.IGNORECASE)
        if not match:
            result.error = "条件命令格式错误"
            return result
        condition, actual_cmd = match.group(1), match.group(2)
        # 检查最近聊天中是否包含条件关键词
        recent = self._get_recent_chat(0).lower()
        if condition.lower() in recent:
            result = self.execute(actual_cmd)
            result.command = command
        else:
            result.success = True
            result.response = f"条件不满足，跳过: {actual_cmd}"
        return result

    def _get_recent_chat(self, since: int = 0) -> str:
        """获取最近聊天（从 bot.chat_messages 的 since 索引开始）"""
        try:
            messages = self.bot.chat_messages[since:]
            return "\n".join(messages) if messages else ""
        except Exception:
            return ""

    def get_summary(self) -> str:
        """获取执行摘要"""
        success = sum(1 for r in self.results if r.success)
        failed = len(self.results) - success
        lines = [
            f"命令执行摘要: 共 {len(self.results)} 条, 成功 {success}, 失败 {failed}",
        ]
        for r in self.results:
            status = "✓" if r.success else "✗"
            lines.append(f"  {status} {r.command}")
            if r.error:
                lines.append(f"    错误: {r.error}")
        return "\n".join(lines)


# 预设的常用命令脚本
PRESET_SCRIPTS = {
    "info": CommandScript(
        commands=["plugins", "version", "help", "list"],
        delay=1.5,
        stop_on_error=False,
    ),
    "grief": CommandScript(
        commands=[
            "plugins",
            "version",
            "help",
            "list",
            "co i",
            "rg list",
            "bal",
            "money",
            "pay",
        ],
        delay=1.0,
        stop_on_error=False,
    ),
    "auth": CommandScript(
        commands=[
            "login password",
            "register password password",
        ],
        delay=2.0,
        stop_on_error=False,
    ),
}


def run_commands_on_server(host: str, port: int, username: str,
                            commands: list[str], delay: float = 1.0,
                            timeout: float = 15.0,
                            authme_password: str = "") -> list[CommandResult]:
    """
    便捷函数：连接服务器并执行命令列表。
    吸收自 MCPTool 的 "send a bot that will execute a list of commands upon login"。
    """
    from .bot import MCBot
    bot = MCBot(host, port, username=username, timeout=timeout)
    results = []
    try:
        bot.connect()
        # AuthMe 登录
        if authme_password:
            try:
                bot.authme_login(authme_password, register=False)
            except Exception:
                pass
        runner = CommandRunner(bot, delay=delay)
        script = CommandScript(commands=commands, delay=delay)
        results = runner.run_script(script)
    except Exception as e:
        results.append(CommandResult(command="connect", error=str(e)))
    finally:
        bot.close()
    return results
