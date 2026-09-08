# plugin.py
import asyncio
from pathlib import Path

from ncatbot.plugin import NcatBotPlugin
import requests
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
import yaml


def load_config():
    base_dir = Path(__file__).resolve().parents[2]
    config_path = base_dir / "config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class AgnesPlugin(NcatBotPlugin):
    """Agnes AI 文本模型插件"""

    config = load_config()
    API_KEY = config["apis"]["agnes"]["api_key"]
    BASE_URL = config["apis"]["agnes"]["chat_base_url"]
    MODEL = "agnes-2.0-flash"
    BOT_UIN = int(config.get("bot_uin", 0))

    async def on_load(self):
        print("🤖 Agnes AI 插件已加载！")
        print("💡 在群里 @我 并发送消息即可获得 AI 回复。")

    @registrar.qq.on_group_command(".ai", ignore_case=True)
    async def on_group_chat(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if not raw_text.lower().startswith(".ai"):
            return

        question = raw_text[3:].strip()
        if not question:
            await event.reply("请问你想问什么呢？直接说问题就好～")
            return

        await self._call_agnes_and_reply(event, question)

    @registrar.qq.on_group_message()
    async def on_group_at_chat(self, event: GroupMessageEvent):
        if not event.message.is_at(self.BOT_UIN):
            return

        raw_text = event.raw_message.strip()
        if not raw_text:
            return

        if raw_text.lower().startswith(".ai"):
            question = raw_text[3:].strip()
        else:
            question = raw_text.strip()

        if not question:
            await event.reply("请问你想问什么呢？直接说问题就好～")
            return

        await self._call_agnes_and_reply(event, question)

    async def _call_agnes_and_reply(self, event, question: str):
        url = self.BASE_URL
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": "你是一个智能助手，回答简洁友好。"},
                {"role": "user", "content": question}
            ],
            "stream": False
        }

        try:
            response = await asyncio.to_thread(
                requests.post, url, headers=headers, json=payload, timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                reply = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not reply:
                    await event.reply("❌ AI 服务返回了空内容，请稍后重试。")
                    return

                if len(reply) > 2000:
                    reply = reply[:1997] + "..."

                await event.reply(reply)
            else:
                await event.reply(f"❌ AI 服务暂时不可用，请稍后再试。（错误码: {response.status_code}）")

        except requests.exceptions.Timeout:
            await event.reply("⏰ 请求超时，AI 可能正在忙，请稍后重试。")
        except Exception as e:
            await event.reply(f"❌ 发生错误: {str(e)[:100]}")