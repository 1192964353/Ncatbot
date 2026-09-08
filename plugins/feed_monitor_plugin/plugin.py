import asyncio
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

import requests
import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray


class FeedMonitorPlugin(NcatBotPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config_path = Path(__file__).resolve().parents[2] / "config.yaml"
        with config_path.open("r", encoding="utf-8") as file:
            self.config = yaml.safe_load(file) or {}
        self.github_api_base_url = self.config["apis"]["github"]["api_base_url"].rstrip("/")
        self.state_path = Path(__file__).resolve().parent / "subscriptions.json"
        self.state = self._load()

    def _load(self):
        try:
            with self.state_path.open("r", encoding="utf-8") as file:
                state = json.load(file)
            if not isinstance(state, dict):
                return {"subscriptions": [], "seen": {}}
            subscriptions = [
                item for item in state.get("subscriptions", [])
                if isinstance(item, dict)
                and isinstance(item.get("id"), int)
                and item.get("kind") in {"rss", "github"}
                and isinstance(item.get("target"), str)
                and isinstance(item.get("group_id"), str)
            ]
            seen = state.get("seen", {})
            return {
                "subscriptions": subscriptions,
                "seen": seen if isinstance(seen, dict) else {},
            }
        except (FileNotFoundError, json.JSONDecodeError):
            return {"subscriptions": [], "seen": {}}

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(self.state, file, ensure_ascii=False, indent=2)

    async def on_load(self):
        self.add_scheduled_task("check_subscriptions", interval="10m")

    @staticmethod
    def _fetch(url: str, headers: Optional[Dict[str, str]] = None):
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response

    async def _fetch_rss(self, url: str):
        response = await asyncio.to_thread(self._fetch, url)
        root = ET.fromstring(response.content)
        item = root.find(".//item")
        if item is None:
            item = root.find(".//{http://www.w3.org/2005/Atom}entry")
        if item is None:
            return None

        def value(names):
            for name in names:
                child = item.find(name)
                if child is None:
                    continue
                text = child.text or child.attrib.get("href", "")
                if text:
                    return text.strip()
            return ""

        link = value(["link", "{http://www.w3.org/2005/Atom}link"])
        return {
            "id": value(["guid", "{http://www.w3.org/2005/Atom}id"]) or link,
            "title": value(["title", "{http://www.w3.org/2005/Atom}title"]),
            "link": link,
        }

    async def _validate_rss(self, url: str):
        try:
            response = await asyncio.to_thread(self._fetch, url)
            root = ET.fromstring(response.content)
            title = root.findtext("./channel/title") or root.findtext(
                "./{http://www.w3.org/2005/Atom}title"
            ) or url
            return str(title).strip()
        except Exception:
            self.logger.exception("Failed to validate RSS feed %s", url)
            return None

    async def _validate_github(self, repo: str):
        try:
            response = await asyncio.to_thread(
                self._fetch,
                f"{self.github_api_base_url}/repos/{repo}",
                {"Accept": "application/vnd.github+json"},
            )
            data = response.json()
            return str(data.get("full_name") or repo)
        except Exception:
            self.logger.exception("Failed to validate GitHub repository %s", repo)
            return None

    async def _fetch_github(self, repo: str):
        response = await asyncio.to_thread(
            self._fetch,
            f"{self.github_api_base_url}/repos/{repo}/releases/latest",
            {"Accept": "application/vnd.github+json"},
        )
        data = response.json()
        return {
            "id": str(data.get("id", "")),
            "title": data.get("name") or data.get("tag_name", ""),
            "link": data.get("html_url", ""),
        }

    @registrar.qq.on_group_command(".订阅", ignore_case=True)
    async def subscribe(self, event: GroupMessageEvent):
        parts = event.raw_message.strip().split(maxsplit=2)
        if len(parts) < 3 or parts[1].lower() not in {"rss", "github"}:
            await event.reply("用法：.订阅 rss <URL>\n或：.订阅 github <owner/repo>")
            return
        kind, target = parts[1].lower(), parts[2].strip()
        if kind == "rss" and not re.match(r"https?://", target):
            await event.reply("RSS 地址必须以 http:// 或 https:// 开头。")
            return
        if kind == "github" and not re.fullmatch(r"[^/\s]+/[^/\s]+", target):
            await event.reply("GitHub 仓库格式应为 owner/repo。")
            return
        target_info = await (self._validate_rss(target) if kind == "rss" else self._validate_github(target))
        if not target_info:
            label = "RSS 订阅源" if kind == "rss" else "GitHub 仓库"
            await event.reply(f"未找到{label}：{target}，请检查地址或仓库名是否正确。")
            return
        group_id = str(event.group_id)
        subscriptions = self.state.setdefault("subscriptions", [])
        if any(item.get("kind") == kind and item.get("target") == target and item.get("group_id") == group_id
               for item in subscriptions):
            await event.reply("这个订阅已经存在。")
            return
        item = {
            "id": max([x.get("id", 0) for x in subscriptions] or [0]) + 1,
            "kind": kind,
            "target": target,
            "group_id": group_id,
        }
        subscriptions.append(item)
        self._save()
        await event.reply(f"订阅成功，编号 {item['id']}。\n目标：{target_info}")

    @registrar.qq.on_group_command(".订阅列表", ignore_case=True)
    async def list_subscriptions(self, event: GroupMessageEvent):
        items = [x for x in self.state.get("subscriptions", []) if x.get("group_id") == str(event.group_id)]
        if not items:
            await event.reply("当前群没有订阅。")
            return
        await event.reply("\n".join(f"#{x['id']} {x['kind']} {x['target']}" for x in items))

    @registrar.qq.on_group_command(".取消订阅", ignore_case=True)
    async def unsubscribe(self, event: GroupMessageEvent):
        raw_id = event.raw_message.strip()[len(".取消订阅"):].strip()
        if not raw_id.isdigit():
            await event.reply("用法：.取消订阅 <编号>")
            return
        group_id = str(event.group_id)
        subscriptions = self.state.get("subscriptions", [])
        before = len(subscriptions)
        self.state["subscriptions"] = [
            item for item in subscriptions
            if not (item.get("id") == int(raw_id) and item.get("group_id") == group_id)
        ]
        self._save()
        await event.reply("已取消订阅。" if len(self.state["subscriptions"]) < before else "没有找到这个订阅。")

    async def check_subscriptions(self):
        for item in list(self.state.get("subscriptions", [])):
            try:
                if item["kind"] == "rss":
                    latest = await self._fetch_rss(item["target"])
                else:
                    latest = await self._fetch_github(item["target"])
                if not latest or not latest.get("id"):
                    continue
                seen = self.state.setdefault("seen", {})
                key = str(item.get("id"))
                if key not in seen:
                    seen[key] = latest["id"]
                    continue
                if seen[key] == latest["id"]:
                    continue
                message = MessageArray()
                message.add_text(f"📢 订阅更新：{latest['title']}\n{latest['link']}")
                await self.api.qq.post_group_array_msg(group_id=item["group_id"], msg=message)
                seen[key] = latest["id"]
            except Exception:
                self.logger.exception("Failed to check subscription %s", item.get("id"))
        self._save()
