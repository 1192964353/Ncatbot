import re
import time
from datetime import datetime
from pathlib import Path

import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin


class StatusMonitorPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root_dir = Path(__file__).resolve().parents[2]
        self.started_at = time.time()
        with (self.root_dir / "config.yaml").open("r", encoding="utf-8") as file:
            self.config = yaml.safe_load(file) or {}

    def _is_owner(self, event) -> bool:
        root_id = str(self.config.get("root", "")).strip()
        user_ids = set()

        def collect(value):
            if value is None:
                return
            if isinstance(value, dict):
                user_id = value.get("user_id")
            else:
                user_id = getattr(value, "user_id", None)
            if user_id is not None:
                user_ids.add(str(user_id).strip())

        collect(event)
        collect(getattr(event, "sender", None))
        for field_name in ("raw_event", "data", "event", "raw"):
            payload = getattr(event, field_name, None)
            collect(payload)
            if isinstance(payload, dict):
                collect(payload.get("sender"))

        return bool(root_id and root_id in user_ids)

    def _plugin_names(self):
        names = []
        for manifest in sorted((self.root_dir / "plugins").glob("*/manifest.toml")):
            match = re.search(r'^name\s*=\s*["\']([^"\']+)', manifest.read_text(encoding="utf-8"), re.MULTILINE)
            names.append(match.group(1) if match else manifest.parent.name)
        return names

    def _error_lines(self):
        log_path = self.root_dir / "logs" / "bot.log"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return [line for line in lines if re.search(r"\b(ERROR|Exception|Traceback|失败|错误)\b", line, re.IGNORECASE)][-5:]
        except OSError:
            return []

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        total = int(seconds)
        days, total = divmod(total, 86400)
        hours, total = divmod(total, 3600)
        minutes, _ = divmod(total, 60)
        return f"{days}天{hours}小时{minutes}分钟"

    @registrar.qq.on_group_command(".状态", ignore_case=True)
    async def group_status(self, event: GroupMessageEvent):
        await event.reply(self._status_text())

    @registrar.qq.on_private_command(".状态", ignore_case=True)
    async def private_status(self, event: PrivateMessageEvent):
        await event.reply(self._status_text())

    def _status_text(self):
        return (
            "🤖 机器人状态\n"
            f"运行时间：{self._format_uptime(time.time() - self.started_at)}\n"
            f"启动时间：{datetime.fromtimestamp(self.started_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"已发现插件：{len(self._plugin_names())}\n"
            f"最近错误：{len(self._error_lines())} 条"
        )

    @registrar.qq.on_group_command(".插件状态", ignore_case=True)
    async def group_plugin_status(self, event: GroupMessageEvent):
        await event.reply("已发现插件：\n" + "\n".join(self._plugin_names()))

    @registrar.qq.on_private_command(".插件状态", ignore_case=True)
    async def private_plugin_status(self, event: PrivateMessageEvent):
        await event.reply("已发现插件：\n" + "\n".join(self._plugin_names()))

    @registrar.qq.on_group_command(".错误日志", ignore_case=True)
    async def group_error_log(self, event: GroupMessageEvent):
        if not self._is_owner(event):
            await event.reply("只有机器人所有者可以查看错误日志。")
            return
        await event.reply(self._error_text())

    @registrar.qq.on_private_command(".错误日志", ignore_case=True)
    async def private_error_log(self, event: PrivateMessageEvent):
        if not self._is_owner(event):
            await event.reply("只有机器人所有者可以查看错误日志。")
            return
        await event.reply(self._error_text())

    def _error_text(self):
        errors = self._error_lines()
        if not errors:
            return "最近没有发现错误日志。"
        return "最近错误：\n" + "\n".join(errors)
