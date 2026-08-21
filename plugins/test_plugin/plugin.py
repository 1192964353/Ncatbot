from ncatbot.plugin import NcatBotPlugin
from uapi import UapiClient
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import datetime
import asyncio

import yaml

# 获取当前日期时间
current_datetime = datetime.datetime.now()
weekday = current_datetime.weekday()

client = UapiClient("https://uapis.cn")


# 配置（建议从环境变量读取，不要硬编码）
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
GroupList = config.get("groupList",{}).get("epic_free_games",{})
print("GroupList：",GroupList)

class EpicFreeGamesPlugin(NcatBotPlugin):

    # 定时任务 每周五上午9:30发送EPIC每周免费游戏更新
    async def on_load(self):
        self.logger.debug(f"{self.name} 已加载")
        self.add_scheduled_task("test", interval="5s")

    async def test1(self):
        if weekday == 4:  # 星期五
            for group_id in GroupList:
                await self.api.qq.post_group_array_msg(self, group_id=group_id, MessageArray=await self.GetFreeGames())  # 你的发消息函数
                await asyncio.sleep(1)  # 加个小延时，避免发送太快被限制
    
    async def test(self):
        await self.api.qq.post_group_array_msg(self, group_id=1061778880, MessageArray=await self.GetFreeGames())  # 你的发消息函数
        await asyncio.sleep(1)  # 加个小延时，避免发送太快被限制
    

    #群组消息
    @registrar.qq.on_group_command(".免费游戏", ignore_case=True)
    async def on_group_hello(self, event: GroupMessageEvent):
        print("免费游戏插件_group")
        await event.reply(await self.GetFreeGames())        

    #私聊消息
    @registrar.qq.on_private_command(".免费游戏", ignore_case=True)
    async def on_private_hello(self, event: PrivateMessageEvent):
        print("免费游戏插件_private")
        await event.reply(await self.GetFreeGames())
    
    async def GetFreeGames(self):
        result = client.game.get_game_epic_free()
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