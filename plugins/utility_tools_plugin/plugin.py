import asyncio
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray


def load_config() -> dict:
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


class UtilityToolsPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = load_config()
        self.api_config = self.config.get("apis", {})

    @staticmethod
    def _request_json(url: str, **kwargs):
        response = requests.get(url, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @registrar.qq.on_group_command(".天气", ignore_case=True)
    async def group_weather(self, event: GroupMessageEvent):
        await self._weather(event)

    @registrar.qq.on_private_command(".天气", ignore_case=True)
    async def private_weather(self, event: PrivateMessageEvent):
        await self._weather(event)

    async def _weather(self, event):
        city = event.raw_message.strip()[len(".天气"):].strip()
        if not city:
            await event.reply("用法：.天气 <城市>，例如：.天气 北京")
            return
        try:
            data = await asyncio.to_thread(
                self._request_json,
                f"{self.api_config['weather']['base_url'].rstrip('/')}/{quote(city)}?format=j1",
                headers={"User-Agent": "NcatBot/1.0"},
            )
            current = (data.get("current_condition") or [{}])[0]
            area = ((data.get("nearest_area") or [{}])[0].get("areaName") or [{}])[0].get("value", city)
            description = ((current.get("weatherDesc") or [{}])[0]).get("value", "未知")
            await event.reply(
                f"🌤️ {area}\n天气：{description}\n"
                f"温度：{current.get('temp_C', '?')}°C\n"
                f"体感：{current.get('FeelsLikeC', '?')}°C\n"
                f"湿度：{current.get('humidity', '?')}%\n"
                f"风速：{current.get('windspeedKmph', '?')} km/h"
            )
        except Exception:
            self.logger.exception("Failed to query weather for %s", city)
            await event.reply("天气查询失败，请稍后重试或检查城市名称。")

    @registrar.qq.on_group_command(".翻译", ignore_case=True)
    async def group_translate(self, event: GroupMessageEvent):
        await self._translate(event)

    @registrar.qq.on_private_command(".翻译", ignore_case=True)
    async def private_translate(self, event: PrivateMessageEvent):
        await self._translate(event)

    async def _translate(self, event):
        text = event.raw_message.strip()[len(".翻译"):].strip()
        if not text:
            await event.reply("用法：.翻译 <内容>\n也支持：.翻译 日译中 <内容>")
            return
        language_hint = "自动识别并翻译成中文"
        match = re.match(r"^(中译英|英译中|日译中|中译日|韩译中)\s+(.+)$", text, re.IGNORECASE)
        if match:
            language_hint, text = match.group(1), match.group(2)
        try:
            agnes = self.config.get("apis", {}).get("agnes", {})
            response = await asyncio.to_thread(
                requests.post,
                agnes["chat_base_url"],
                headers={"Authorization": f"Bearer {agnes.get('api_key', '')}", "Content-Type": "application/json"},
                json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": f"请{language_hint}，只输出译文：\n{text}"}], "temperature": 0.1},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            result = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            await event.reply(result or "翻译服务没有返回内容。")
        except Exception:
            self.logger.exception("Failed to translate text")
            await event.reply("翻译失败，请稍后重试。")

    @registrar.qq.on_group_command(".二维码", ignore_case=True)
    async def group_qr(self, event: GroupMessageEvent):
        await self._qr(event)

    @registrar.qq.on_private_command(".二维码", ignore_case=True)
    async def private_qr(self, event: PrivateMessageEvent):
        await self._qr(event)

    async def _qr(self, event):
        content = event.raw_message.strip()[len(".二维码"):].strip()
        if not content:
            await event.reply("用法：.二维码 <文字或链接>")
            return
        qr_url = f"{self.api_config['qr']['base_url']}?size=300&text={quote(content)}"
        message = MessageArray()
        message.add_text("二维码：\n")
        message.add_image(qr_url)
        await event.reply(message)

    @registrar.qq.on_group_command(".链接", ignore_case=True)
    async def group_link(self, event: GroupMessageEvent):
        await self._link(event)

    @registrar.qq.on_private_command(".链接", ignore_case=True)
    async def private_link(self, event: PrivateMessageEvent):
        await self._link(event)

    async def _link(self, event):
        url = event.raw_message.strip()[len(".链接"):].strip()
        if not self._valid_url(url):
            await event.reply("用法：.链接 <http://或https://链接>")
            return
        await event.reply(f"链接有效：\n{url}")

    @registrar.qq.on_group_command(".短链接", ignore_case=True)
    async def group_short_link(self, event: GroupMessageEvent):
        await self._short_link(event)

    @registrar.qq.on_private_command(".短链接", ignore_case=True)
    async def private_short_link(self, event: PrivateMessageEvent):
        await self._short_link(event)

    async def _short_link(self, event):
        url = event.raw_message.strip()[len(".短链接"):].strip()
        if not self._valid_url(url):
            await event.reply("用法：.短链接 <http://或https://链接>")
            return
        try:
            response = await asyncio.to_thread(
                requests.get,
                self.api_config["short_url"]["api_url"],
                params={"format": "json", "url": url},
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("shorturl"):
                await event.reply(f"短链接：\n{result['shorturl']}")
            else:
                await event.reply(f"短链接生成失败：{result.get('errormessage', '未知错误')}")
        except Exception:
            self.logger.exception("Failed to shorten URL")
            await event.reply("短链接生成失败，请稍后重试。")
