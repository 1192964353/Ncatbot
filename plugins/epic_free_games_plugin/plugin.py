from ncatbot.plugin import NcatBotPlugin
from uapi import UapiClient
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import datetime
import asyncio
from pathlib import Path

import yaml



def load_config():
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


config = load_config()
client = UapiClient(config["apis"]["uapi"]["base_url"])


class EpicFreeGamesPlugin(NcatBotPlugin):
    async def on_load(self):
        self.logger.debug(f"{self.name} 已加载")
        self.add_scheduled_task("epic_free_games", interval="9:30")

    async def epic_free_games(self):
        try:
            now = datetime.datetime.now()
            if now.weekday() != 4:
                return
            if now.hour != 9 or now.minute != 30:
                return

            msg = await self.get_free_games()
            for group_id in await self._get_group_ids():
                await self.api.qq.post_group_array_msg(group_id=group_id, msg=msg)
                await asyncio.sleep(1)
        except Exception as exc:
            self.logger.exception(
                "Scheduled task '%s' failed: %s",
                "epic_free_games",
                exc,
            )

    async def _get_group_ids(self):
        get_group_list = getattr(self.api.qq, "get_group_list", None)
        if get_group_list is None:
            self.logger.warning("当前 API 不支持获取群列表，跳过 EPIC 定时推送")
            return []
        try:
            result = await get_group_list()
            groups = result.get("data", result) if isinstance(result, dict) else result
            return [str(item["group_id"]) for item in groups if isinstance(item, dict) and item.get("group_id")]
        except Exception:
            self.logger.exception("Failed to get group list for epic free games")
            return []

    @registrar.qq.on_group_command(".免费游戏", ignore_case=True)
    async def on_group_hello(self, event: GroupMessageEvent):
        await event.reply(await self.get_free_games())

    @registrar.qq.on_private_command(".免费游戏", ignore_case=True)
    async def on_private_hello(self, event: PrivateMessageEvent):
        await event.reply(await self.get_free_games())

    async def get_free_games(self):
        result = await asyncio.to_thread(client.game.get_game_epic_free)
        msg = MessageArray()
        msg.add_text("《EPIC 本周免费游戏》\n")
        msg.add_text("\n")
        if isinstance(result, dict) and result.get('message') == '获取成功':
            for game in result.get('data', []):
                msg.add_text(f"{game.get('title')}\n")
                msg.add_text(f"{game.get('link')}\n")
                msg.add_image(game.get('cover'))
                msg.add_text("------------------------------\n")
        return msg