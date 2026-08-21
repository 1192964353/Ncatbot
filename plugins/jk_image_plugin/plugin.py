from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import asyncio

import yaml
import inspect
import requests
import os
import time
from pathlib import Path

# 配置（建议从环境变量读取，不要硬编码）
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
GroupList = config.get("groupList",{}).get("news",[])
# 下载图片并获取本地路径
jk_image_url = config["apis"]["urls"]["random_jk_image"]

class JkImagesPlugin(NcatBotPlugin):

    #群聊消息
    @registrar.qq.on_group_command(".jk", ignore_case=True)
    async def on_group_getNews(self, event: GroupMessageEvent):
        await event.reply(await self.GetJkImage())

    #私聊消息
    @registrar.qq.on_private_command(".jk", ignore_case=True)
    async def on_group_getNews(self, event: PrivateMessageEvent):
        await event.reply(await self.GetJkImage())

    async def GetJkImage(self):
        msg = MessageArray()
        msg.add_image(jk_image_url)
        return msg
