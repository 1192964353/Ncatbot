import re
from pathlib import Path

import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.plugin import NcatBotPlugin


def load_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


class GroupAdminPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = load_config()

    async def _is_admin(self, event: GroupMessageEvent) -> bool:
        user_id = str(getattr(event, "user_id", ""))
        sender = getattr(event, "sender", None)
        sender_id = getattr(sender, "user_id", None)
        if sender_id is None and isinstance(sender, dict):
            sender_id = sender.get("user_id")
        if sender_id is not None:
            user_id = str(sender_id)
        root_id = str(self.config.get("root", ""))
        bot_id = str(self.config.get("bot_uin", ""))
        if user_id in {root_id, bot_id}:
            return True

        role = getattr(sender, "role", None)
        if role is None and isinstance(sender, dict):
            role = sender.get("role")
        if role in {"owner", "admin"}:
            return True

        get_member_info = getattr(self.api.qq, "get_group_member_info", None)
        if get_member_info is None:
            return False
        try:
            member = await get_member_info(
                group_id=str(event.group_id), user_id=user_id, no_cache=True
            )
            return (member or {}).get("role") in {"owner", "admin"}
        except Exception:
            self.logger.exception("Failed to check group role for %s", user_id)
            return False

    async def _require_admin(self, event: GroupMessageEvent) -> bool:
        if await self._is_admin(event):
            return True
        await event.reply("只有群主或管理员可以使用这个命令。")
        return False

    @staticmethod
    def _target_user_id(raw_message: str) -> str:
        mention = re.search(r"\[CQ:at,qq=(\d+)\]", raw_message)
        if mention:
            return mention.group(1)
        numbers = re.findall(r"\b\d{5,12}\b", raw_message)
        return numbers[0] if numbers else ""

    @registrar.qq.on_group_command(".禁言", ignore_case=True)
    async def ban(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        parts = event.raw_message.strip().split()
        target = self._target_user_id(event.raw_message)
        duration = 600
        for part in parts[1:]:
            if part.isdigit() and part != target:
                duration = max(60, min(int(part) * 60, 30 * 24 * 3600))
                break
        if not target:
            await event.reply("用法：.禁言 @用户 [分钟]")
            return
        await self.api.qq.set_group_ban(
            group_id=str(event.group_id), user_id=target, duration=duration
        )
        await event.reply(f"已禁言 {target} {duration // 60} 分钟。")

    @registrar.qq.on_group_command(".解禁", ignore_case=True)
    async def unban(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        target = self._target_user_id(event.raw_message)
        if not target:
            await event.reply("用法：.解禁 @用户")
            return
        await self.api.qq.set_group_ban(
            group_id=str(event.group_id), user_id=target, duration=0
        )
        await event.reply(f"已解除 {target} 的禁言。")

    @registrar.qq.on_group_command(".踢出", ignore_case=True)
    async def kick(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        target = self._target_user_id(event.raw_message)
        if not target:
            await event.reply("用法：.踢出 @用户")
            return
        await self.api.qq.set_group_kick(
            group_id=str(event.group_id), user_id=target, reject_add_request=False
        )
        await event.reply(f"已将 {target} 移出群聊。")

    @registrar.qq.on_group_command(".全员禁言", ignore_case=True)
    async def whole_ban(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        enabled = "解除" not in event.raw_message
        await self.api.qq.set_group_whole_ban(
            group_id=str(event.group_id), enable=enabled
        )
        await event.reply("已开启全员禁言。" if enabled else "已解除全员禁言。")

    @registrar.qq.on_group_command(".公告", ignore_case=True)
    async def notice(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        content = event.raw_message.strip()[len(".公告"):].strip()
        if not content:
            await event.reply("用法：.公告 <内容>")
            return
        await event.reply(f"【群公告】\n{content}")

    @registrar.qq.on_group_command(".解除全员禁言", ignore_case=True)
    async def whole_unban(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        await self.api.qq.set_group_whole_ban(
            group_id=str(event.group_id), enable=False
        )
        await event.reply("已解除全员禁言。")
