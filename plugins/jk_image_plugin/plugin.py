from pathlib import Path

from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import yaml


def load_config():
    base_dir = Path(__file__).resolve().parents[2]
    config_path = base_dir / "config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


config = load_config()
jk_image_url = config["apis"]["urls"]["random_jk_image"]


class JkImagesPlugin(NcatBotPlugin):
    @registrar.qq.on_group_command(".jk", ignore_case=True)
    async def on_group_get_news(self, event: GroupMessageEvent):
        await event.reply(await self.get_jk_image())

    @registrar.qq.on_private_command(".jk", ignore_case=True)
    async def on_private_get_news(self, event: PrivateMessageEvent):
        await event.reply(await self.get_jk_image())

    async def get_jk_image(self):
        msg = MessageArray()
        msg.add_image(jk_image_url)
        return msg
