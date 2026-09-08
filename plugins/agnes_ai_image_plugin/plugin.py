# plugin.py
import asyncio
from pathlib import Path

from ncatbot.plugin import NcatBotPlugin
import requests
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
import yaml
from ncatbot.types import MessageArray


def load_config():
    base_dir = Path(__file__).resolve().parents[2]
    config_path = base_dir / "config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class AgnesImagePlugin(NcatBotPlugin):
    """Agnes AI 文生图插件"""

    config = load_config()
    API_KEY = config["apis"]["agnes"]["api_key"]
    BASE_URL = config["apis"]["agnes"]["image_base_url"]
    MODEL = "agnes-image-2.1-flash"
    DEFAULT_SIZE = "1024x768"

    async def on_load(self):
        print("🎨 Agnes AI 图片生成插件已加载！")
        print("💡 在群里发送: .ai出图 描述文字 即可生成图片")

    @registrar.qq.on_group_command(".ai出图", ignore_case=True)
    async def on_group_image(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if raw_text.lower().startswith(".ai出图"):
            prompt = raw_text[5:].strip()
        else:
            return

        if not prompt:
            await event.reply("请告诉我你想要画什么，例如：.ai出图 一只可爱的金毛小狗在草地奔跑")
            return

        await self._generate_and_reply(event, prompt)

    async def _generate_and_reply(self, event, prompt: str):
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.MODEL,
            "prompt": prompt,
            "size": self.DEFAULT_SIZE,
            "extra_body": {
                "response_format": "url"
            }
        }

        try:
            await event.reply("🎨 正在生成图片，请稍等...")

            response = await asyncio.to_thread(
                requests.post, self.BASE_URL, headers=headers, json=payload, timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('data') and len(result['data']) > 0:
                    image_url = result["data"][0].get("url")
                    if not isinstance(image_url, str) or not image_url.strip():
                        await event.reply("❌ 图片生成失败，API 未返回有效图片地址。")
                        return
                    msg = MessageArray()
                    msg.add_text("🖼️ 你的图片已生成：\n")
                    msg.add_image(image_url)
                    await event.reply(msg)
                else:
                    await event.reply("❌ 图片生成失败，API 返回数据异常。")
            else:
                await event.reply(f"❌ 图片生成失败，错误码: {response.status_code}")

        except requests.exceptions.Timeout:
            await event.reply("⏰ 图片生成超时，请稍后重试。")
        except Exception as e:
            await event.reply(f"❌ 发生错误: {str(e)[:100]}")

    def _extract_text(self, message_segments):
        text_parts = []
        for seg in message_segments:
            if seg.type == "text":
                text_parts.append(seg.data.get("text", ""))
        return "".join(text_parts).strip()