import json
import re
from pathlib import Path

import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.plugin import NcatBotPlugin


class PermissionPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_path = Path(__file__).resolve().parents[2] / "config.yaml"
        self.state_path = Path(__file__).resolve().parent / "permissions.json"
        self.config = self._load_config()
        self.state = self._load_state()

    def _load_config(self):
        with self.config_path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _load_state(self):
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                state = json.load(file)
            return {"users": [str(user) for user in state.get("users", [])]}
        except (FileNotFoundError, json.JSONDecodeError):
            return {"users": []}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(self.state, file, ensure_ascii=False, indent=2)

    async def _is_admin(self, event: GroupMessageEvent) -> bool:
        user_id = str(getattr(event, "user_id", ""))
        sender = getattr(event, "sender", None)
        sender_id = getattr(sender, "user_id", None)
        if sender_id is None and isinstance(sender, dict):
            sender_id = sender.get("user_id")
        if sender_id is not None:
            user_id = str(sender_id)
        if user_id in {str(self.config.get("root", "")), str(self.config.get("bot_uin", ""))}:
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
        await event.reply("只有群主或管理员可以管理权限。")
        return False

    @staticmethod
    def _target(raw_message: str, command: str) -> str:
        mention = re.search(r"\[CQ:at,qq=(\d+)\]", raw_message)
        if mention:
            return mention.group(1)
        rest = raw_message.strip()[len(command):].strip()
        match = re.search(r"\b\d{5,12}\b", rest)
        return match.group(0) if match else ""

    @registrar.qq.on_group_command(".授权", ignore_case=True)
    async def authorize(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        user_id = self._target(event.raw_message, ".授权")
        if not user_id:
            await event.reply("用法：.授权 @用户或QQ号")
            return
        if user_id not in self.state["users"]:
            self.state["users"].append(user_id)
            self._save_state()
        await event.reply(f"已授权用户：{user_id}")

    @registrar.qq.on_group_command(".取消授权", ignore_case=True)
    async def revoke(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        user_id = self._target(event.raw_message, ".取消授权")
        if not user_id:
            await event.reply("用法：.取消授权 @用户或QQ号")
            return
        if user_id in self.state["users"]:
            self.state["users"].remove(user_id)
            self._save_state()
            await event.reply(f"已取消授权：{user_id}")
        else:
            await event.reply(f"用户 {user_id} 当前没有授权。")

    @registrar.qq.on_group_command(".权限列表", ignore_case=True)
    async def list_permissions(self, event: GroupMessageEvent):
        if not await self._require_admin(event):
            return
        users = self.state["users"]
        await event.reply("已授权用户：\n" + ("\n".join(users) if users else "暂无"))
