import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import yaml

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray


def load_config() -> dict:
    base_dir = Path(__file__).resolve().parents[2]
    config_path = base_dir / "config.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


config = load_config()


class BilibiliMonitorPlugin(NcatBotPlugin):
    """B站UP主动态监控插件。定时检查订阅UP的新动态，并发送到指定群。"""

    @staticmethod
    def _normalize_up_id(value: Any) -> str:
        return str(value).strip()

    @classmethod
    def _normalize_up_list(cls, values: Any) -> List[str]:
        if not values:
            return []

        normalized: List[str] = []
        seen = set()
        for value in values:
            up_id = cls._normalize_up_id(value)
            if not up_id or up_id in seen:
                continue
            seen.add(up_id)
            normalized.append(up_id)
        return normalized

    @staticmethod
    def _normalize_group_list(values: Any) -> List[str]:
        if not values:
            return []

        normalized: List[str] = []
        seen = set()
        for value in values:
            group_id = str(value).strip()
            if not group_id or group_id in seen:
                continue
            seen.add(group_id)
            normalized.append(group_id)
        return normalized

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.monitor_config = config.get("bilibili_monitor", {}) or {}
        self.api_config = config.get("apis", {}).get("bilibili", {})
        self.subscriptions = self._load_subscriptions()
        self.bilibili_cookie = str(self.monitor_config.get("cookie", "")).strip()
        try:
            interval = int(self.monitor_config.get("interval_minutes", 10))
        except (TypeError, ValueError):
            interval = 10
        self.check_interval = max(1, interval)
        self.state_path = Path(__file__).resolve().parent / "state.json"
        self.state = self._load_state()

    def _load_subscriptions(self) -> Dict[str, Dict[str, List[str]]]:
        subscriptions = self.monitor_config.get("subscriptions") or {}
        if isinstance(subscriptions, dict):
            groups = subscriptions.get("groups") or {}
            users = subscriptions.get("users") or {}
            groups = groups if isinstance(groups, dict) else {}
            users = users if isinstance(users, dict) else {}
            return {
                "groups": {
                    str(scope): self._normalize_up_list(values)
                    for scope, values in groups.items()
                    if isinstance(values, list)
                },
                "users": {
                    str(scope): self._normalize_up_list(values)
                    for scope, values in users.items()
                    if isinstance(values, list)
                },
            }

        legacy_ups = self._normalize_up_list(self.monitor_config.get("ups", []))
        legacy_groups = self._normalize_group_list(self.monitor_config.get("groups", []))
        return {"groups": {group_id: list(legacy_ups) for group_id in legacy_groups}, "users": {}}

    @staticmethod
    def _scope(event) -> tuple[str, str]:
        if isinstance(event, GroupMessageEvent):
            return "groups", str(event.group_id)
        return "users", str(event.user_id)

    def _scope_subscriptions(self, event) -> List[str]:
        kind, scope_id = self._scope(event)
        return self.subscriptions.setdefault(kind, {}).setdefault(scope_id, [])

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        if not self.state_path.exists():
            return {}
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                state = json.load(f) or {}
            return {str(key): value for key, value in state.items() if isinstance(value, dict)}
        except Exception:
            return {}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    async def on_load(self):
        self.logger.info("Bilibili monitor plugin loaded")
        self.add_scheduled_task("check_bilibili_updates", interval=f"{self.check_interval}m", callback=self.check_new_updates)

    async def check_new_updates(self):
        try:
            targets: Dict[str, List[tuple[str, str]]] = {}
            for kind, scopes in self.subscriptions.items():
                for scope_id, up_ids in scopes.items():
                    for up_id in up_ids:
                        targets.setdefault(up_id, []).append((kind, scope_id))

            for up_id, target_scopes in targets.items():
                latest = await self._fetch_latest_update(up_id)
                if not latest:
                    continue

                last_item = self.state.get(up_id, {}).get("latest_id")
                if last_item and latest.get("id") == last_item:
                    continue

                msg = self._build_message(latest)
                delivered = True
                for kind, scope_id in target_scopes:
                    try:
                        if kind == "groups":
                            await self.api.qq.post_group_array_msg(group_id=scope_id, msg=msg)
                        else:
                            await self.api.qq.post_private_array_msg(user_id=scope_id, msg=msg)
                    except Exception as exc:
                        delivered = False
                        self.logger.exception("Failed to push bilibili update to %s %s: %s", kind, scope_id, exc)
                        await asyncio.sleep(0.5)
                if delivered:
                    self.state.setdefault(up_id, {})
                    self.state[up_id]["latest_id"] = latest.get("id")
                    self.state[up_id]["updated_at"] = latest.get("time")
                    self._save_state()
        except Exception as exc:
            self.logger.exception("Scheduled task 'check_bilibili_updates' failed: %s", exc)

    def _fetch_json_sync(self, url: str) -> Dict[str, Any]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": f"{self.api_config['web_base_url'].rstrip('/')}/",
            "Origin": self.api_config["web_base_url"].rstrip("/"),
            "Accept": "application/json, text/plain, */*",
        }
        if self.bilibili_cookie:
            headers["Cookie"] = self.bilibili_cookie
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 412:
            self.logger.warning("Bilibili API returned 412 for %s", url)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_json(self, url: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self._fetch_json_sync, url)

    async def _fetch_up_info(self, up_id: str) -> Optional[Dict[str, str]]:
        try:
            data = await self._fetch_json(
                f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['user_info_path']}?mid={up_id}"
            )
            if data.get("code") != 0:
                return None
            user = (data.get("data") or {}).get("user") or {}
            if not user:
                return None
            return {
                "id": str(user.get("mid") or up_id),
                "name": str(user.get("name") or "未命名 UP 主"),
            }
        except Exception:
            self.logger.exception("Failed to validate bilibili uid %s", up_id)
            return None

    async def _fetch_latest_update(self, up_id: str) -> Optional[Dict[str, Any]]:
        up_id = self._normalize_up_id(up_id)
        if not up_id:
            return None

        try:
            user_info_url = (
                f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['user_info_path']}"
                f"?mid={up_id}"
            )
            user_data = await self._fetch_json(user_info_url)
            user_name = "UP主"
            if user_data.get("code") == 0:
                user_info = user_data.get("data", {}).get("user") or {}
                user_name = user_info.get("name", user_name)

            dynamic_url = (
                f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['dynamic_path']}"
                f"?host_mid={up_id}&offset_dynamic_id=0&platform=web"
            )
            dynamic_data = await self._fetch_json(dynamic_url)
            items = (dynamic_data.get("data") or {}).get("items") or []
            if not items:
                return None

            item = items[0]
            item_id = str((item.get("id_str") or item.get("id") or "")).strip()
            if not item_id:
                return None

            dynamic = item.get("modules", {}).get("module_dynamic", {}) or {}
            desc = dynamic.get("desc", {}) or {}
            major = dynamic.get("major", {}) or {}
            archive = major.get("archive") or {}
            article = major.get("article") or {}
            live = major.get("live") or {}
            author = item.get("modules", {}).get("module_author", {}) or {}

            cover = (
                archive.get("cover")
                or article.get("cover")
                or live.get("cover")
                or author.get("face")
            )
            title = (
                archive.get("title")
                or article.get("title")
                or live.get("title")
                or desc.get("text")
                or "新动态"
            )
            link = (
                archive.get("jump_url")
                or archive.get("link")
                or article.get("jump_url")
                or article.get("link_url")
                or live.get("link")
                or f"{self.api_config['space_base_url'].rstrip('/')}/{up_id}"
            )
            timestamp = (
                (item.get("desc") or {}).get("timestamp")
                or (item.get("modules", {}).get("module_author", {}).get("pub_ts"))
                or (item.get("added_at"))
            )

            return {
                "id": item_id,
                "title": str(title),
                "link": str(link),
                "cover": cover,
                "time": timestamp,
                "type": "dynamic",
                "author": user_name,
            }
        except Exception as exc:
            self.logger.exception("Failed to fetch latest bilibili update for uid %s: %s", up_id, exc)
            return None

    def _build_message(self, item: Dict[str, Any]) -> MessageArray:
        msg = MessageArray()
        author = item.get("author") or "B站UP主"
        msg.add_text(f"📢 {author} 发布了新动态\n")
        msg.add_text(f"标题：{item.get('title', '新动态')}\n")
        if item.get("cover"):
            msg.add_image(item["cover"])
        msg.add_text(f"链接：{item.get('link', '')}\n")
        return msg

    @registrar.qq.on_group_command(".b站订阅", ignore_case=True)
    async def on_group_subscribe(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if raw_text.lower().startswith(".b站订阅"):
            up_id = self._normalize_up_id(raw_text[len(".b站订阅"):])
        else:
            up_id = ""

        if not up_id:
            await event.reply("用法：.b站订阅 <UP主UID>\n例如：.b站订阅 4566646")
            return

        up_info = await self._fetch_up_info(up_id)
        if not up_info:
            await event.reply(f"未找到 B 站 UP 主：{up_id}，请检查 UID 是否正确。")
            return

        subscribed_up = self._scope_subscriptions(event)
        if up_id not in subscribed_up:
            subscribed_up.append(up_id)
            self._save_runtime_config()
            await event.reply(f"已订阅 B 站 UP：{up_info['name']}（UID：{up_info['id']}）")
        else:
            await event.reply(f"该 B 站 UP 已订阅：{up_info['name']}（UID：{up_info['id']}）")

    @registrar.qq.on_group_command(".b站取消订阅", ignore_case=True)
    async def on_group_unsubscribe(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if raw_text.lower().startswith(".b站取消订阅"):
            up_id = self._normalize_up_id(raw_text[len(".b站取消订阅"):])
        else:
            up_id = ""

        if not up_id:
            await event.reply("用法：.b站取消订阅 <UP主UID>")
            return

        subscribed_up = self._scope_subscriptions(event)
        if up_id in subscribed_up:
            subscribed_up.remove(up_id)
            self._save_runtime_config()
            await event.reply(f"已取消订阅：{up_id}")
        else:
            await event.reply(f"当前没有订阅：{up_id}")

    @registrar.qq.on_group_command(".b站列表", ignore_case=True)
    async def on_group_list(self, event: GroupMessageEvent):
        subscribed_up = self._scope_subscriptions(event)
        if not subscribed_up:
            await event.reply("当前没有订阅任何 B 站 UP 主。")
            return
        await event.reply("已订阅的 UP 主：\n" + "\n".join(subscribed_up))

    @registrar.qq.on_private_command(".b站订阅", ignore_case=True)
    async def on_private_subscribe(self, event: PrivateMessageEvent):
        await self.on_group_subscribe(event)

    @registrar.qq.on_private_command(".b站取消订阅", ignore_case=True)
    async def on_private_unsubscribe(self, event: PrivateMessageEvent):
        await self.on_group_unsubscribe(event)

    @registrar.qq.on_private_command(".b站列表", ignore_case=True)
    async def on_private_list(self, event: PrivateMessageEvent):
        await self.on_group_list(event)

    def _save_runtime_config(self):
        base_dir = Path(__file__).resolve().parents[2]
        config_path = base_dir / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.monitor_config["subscriptions"] = self.subscriptions
        data["bilibili_monitor"] = self.monitor_config
        config["bilibili_monitor"] = self.monitor_config

        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
