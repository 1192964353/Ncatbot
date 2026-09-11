from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import datetime
import asyncio
import json
from urllib.request import urlopen

class EpicFreeGamesPlugin(NcatBotPlugin):
    async def on_load(self):
        self.logger.debug(f"{self.name} 已加载")
        self.add_scheduled_task("epic_free_games", interval="09:30")

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
        # 兼容两种位置：api.qq.get_group_list 或 api.qq.query.get_group_list
        get_group_list = getattr(self.api.qq, "get_group_list", None)
        if get_group_list is None:
            q = getattr(self.api.qq, "query", None)
            get_group_list = getattr(q, "get_group_list", None) if q is not None else None
        if get_group_list is None:
            self.logger.warning("当前 API 不支持获取群列表，跳过 EPIC 定时推送")
            return []

        try:
            result = await get_group_list()
            groups = result.get("data", result) if isinstance(result, dict) else result
            if not isinstance(groups, list):
                self.logger.warning("获取群列表返回了非列表数据：%s", type(groups).__name__)
                return []

            ids = []
            for item in groups:
                gid = None
                if isinstance(item, dict):
                    gid = item.get("group_id") or item.get("id")
                else:
                    gid = getattr(item, "group_id", None) or getattr(item, "id", None)
                if gid is not None:
                    ids.append(str(gid))
            return ids
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
        try:
            result = await asyncio.to_thread(self._fetch_free_games)
        except Exception as exc:
            self.logger.warning("获取 EPIC 免费游戏失败: %s", exc)
            result = {}

        msg = MessageArray()
        msg.add_text("《EPIC 本周免费游戏》\n")
        msg.add_text("\n")
        if isinstance(result, dict) and result.get('message') == '获取成功':
            for game in result.get('data', []):
                msg.add_text(f"{game.get('title')}\n")
                msg.add_text(f"{game.get('link')}\n")
                msg.add_image(game.get('cover'))
                msg.add_text("------------------------------\n")
        else:
            msg.add_text("暂时无法获取 EPIC 免费游戏信息，请稍后再试。")
        return msg

    @staticmethod
    def _fetch_free_games() -> dict:
        with urlopen("https://uapis.cn/api/v1/game/epic-free", timeout=15) as response:
            return json.load(response)
