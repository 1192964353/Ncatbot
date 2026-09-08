import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray


class ReminderPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state_path = Path(__file__).resolve().parent / "reminders.json"
        self.reminders = self._load()

    def _load(self):
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, list):
                return []
            return [
                item for item in data
                if isinstance(item, dict)
                and isinstance(item.get("id"), int)
                and isinstance(item.get("target"), str)
                and isinstance(item.get("kind"), str)
                and isinstance(item.get("text"), str)
                and isinstance(item.get("due"), str)
            ]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(self.reminders, file, ensure_ascii=False, indent=2)

    async def on_load(self):
        self.add_scheduled_task("check_reminders", interval="30s")

    @staticmethod
    def _parse_duration(value: str):
        match = re.fullmatch(r"(\d+)\s*(秒|分钟|分|小时|天)", value)
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * {"秒": 1, "分钟": 60, "分": 60, "小时": 3600, "天": 86400}[unit]
        return timedelta(seconds=seconds)

    @staticmethod
    def _message(text: str, creator_id: str = ""):
        message = MessageArray()
        if creator_id:
            if hasattr(message, "add_at"):
                message.add_at(creator_id)
            else:
                message.add_text(f"[CQ:at,qq={creator_id}] ")
        message.add_text(text)
        return message

    @registrar.qq.on_group_command(".提醒", ignore_case=True)
    async def add_group_reminder(self, event: GroupMessageEvent):
        await self._add_reminder(event, str(event.group_id))

    @registrar.qq.on_private_command(".提醒", ignore_case=True)
    async def add_private_reminder(self, event: PrivateMessageEvent):
        await self._add_reminder(event, str(event.user_id))

    async def _add_reminder(self, event, target: str):
        content = event.raw_message.strip()[len(".提醒"):].strip()
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            await event.reply("用法：.提醒 20分钟后 开会\n或：.提醒 20分钟 开会")
            return
        duration_text = parts[0].removesuffix("后")
        delta = self._parse_duration(duration_text)
        if delta is None or delta.total_seconds() > 365 * 86400:
            await event.reply("时间格式支持：秒、分钟、小时、天，例如 20分钟。")
            return
        reminder = {
            "id": max([item.get("id", 0) for item in self.reminders] or [0]) + 1,
            "target": target,
            "creator_id": str(event.user_id),
            "kind": "group" if isinstance(event, GroupMessageEvent) else "private",
            "text": parts[1],
            "due": (datetime.now() + delta).isoformat(timespec="seconds"),
        }
        self.reminders.append(reminder)
        self._save()
        await event.reply(f"提醒已创建，编号 {reminder['id']}，将在 {duration_text} 后提醒。")

    @registrar.qq.on_group_command(".提醒列表", ignore_case=True)
    async def list_group_reminders(self, event: GroupMessageEvent):
        items = [item for item in self.reminders if item["target"] == str(event.group_id)]
        if not items:
            await event.reply("当前没有待处理提醒。")
            return
        await event.reply("\n".join(f"#{item['id']} {item['due']} {item['text']}" for item in items))

    @registrar.qq.on_group_command(".取消提醒", ignore_case=True)
    async def cancel_group_reminder(self, event: GroupMessageEvent):
        await self._cancel_reminder(event, str(event.group_id))

    async def _cancel_reminder(self, event, target: str):
        raw_id = event.raw_message.strip()[len(".取消提醒"):].strip()
        if not raw_id.isdigit():
            await event.reply("用法：.取消提醒 <编号>")
            return
        reminder_id = int(raw_id)
        before = len(self.reminders)
        self.reminders = [
            item for item in self.reminders
            if not (item["id"] == reminder_id and item["target"] == target)
        ]
        self._save()
        await event.reply("已取消提醒。" if len(self.reminders) < before else "没有找到这个提醒。")

    async def check_reminders(self):
        now = datetime.now()
        pending = []
        for item in self.reminders:
            try:
                if datetime.fromisoformat(item["due"]) > now:
                    pending.append(item)
                    continue
            except (KeyError, TypeError, ValueError):
                self.logger.warning("Skipping malformed reminder %s", item)
                continue
            message = self._message(
                f"⏰ 提醒：{item['text']}",
                str(item.get("creator_id", "")) if item["kind"] == "group" else "",
            )
            try:
                if item["kind"] == "group":
                    await self.api.qq.post_group_array_msg(group_id=item["target"], msg=message)
                else:
                    await self.api.qq.post_private_array_msg(user_id=item["target"], msg=message)
            except Exception:
                self.logger.exception("Failed to send reminder %s", item["id"])
                pending.append(item)
        if len(pending) != len(self.reminders):
            self.reminders = pending
            self._save()