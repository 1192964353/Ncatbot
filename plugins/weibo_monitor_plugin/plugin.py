import asyncio
import json
import re
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


class WeiboMonitorPlugin(NcatBotPlugin):
    """微博用户动态监控插件。定时检查订阅用户的新动态，并发送到指定群。"""

    @staticmethod
    def _to_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    @staticmethod
    def _normalize_user_id(value: Any) -> str:
        raw = str(value).strip()
        if not raw:
            return ""
        if "weibo.com" in raw or "weibo.cn" in raw:
            match = re.search(r"(?:u/|uid=|user/|weibo\.com/)(\d+)", raw)
            if match:
                return match.group(1)
        match = re.search(r"(\d+)", raw)
        return match.group(1) if match else raw

    @classmethod
    def _normalize_user_list(cls, values: Any) -> List[str]:
        if not values:
            return []

        normalized: List[str] = []
        seen = set()
        for value in values:
            user_id = cls._normalize_user_id(value)
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            normalized.append(user_id)
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
        self.monitor_config = config.get("weibo_monitor", {}) or {}
        self.api_config = config.get("apis", {}).get("weibo", {})
        self.subscriptions = self._load_subscriptions()
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
                    str(scope): self._normalize_user_list(values)
                    for scope, values in groups.items()
                    if isinstance(values, list)
                },
                "users": {
                    str(scope): self._normalize_user_list(values)
                    for scope, values in users.items()
                    if isinstance(values, list)
                },
            }

        legacy_users = self._normalize_user_list(self.monitor_config.get("users", []))
        legacy_groups = self._normalize_group_list(self.monitor_config.get("groups", []))
        return {"groups": {group_id: list(legacy_users) for group_id in legacy_groups}, "users": {}}

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
        self.logger.info("Weibo monitor plugin loaded")
        self.add_scheduled_task("check_weibo_updates", interval=f"{self.check_interval}m", callback=self.check_new_updates)

    async def check_new_updates(self):
        try:
            targets: Dict[str, List[tuple[str, str]]] = {}
            for kind, scopes in self.subscriptions.items():
                for scope_id, user_ids in scopes.items():
                    for user_id in user_ids:
                        targets.setdefault(user_id, []).append((kind, scope_id))

            for user_id, target_scopes in targets.items():
                latest = await self._fetch_latest_update(user_id)
                if not latest:
                    continue

                last_item = self.state.get(user_id, {}).get("latest_id")
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
                        self.logger.exception("Failed to push weibo update to %s %s: %s", kind, scope_id, exc)
                        await asyncio.sleep(0.5)
                if delivered:
                    self.state.setdefault(user_id, {})
                    self.state[user_id]["latest_id"] = latest.get("id")
                    self.state[user_id]["updated_at"] = latest.get("time")
                    self._save_state()
        except Exception as exc:
            self.logger.exception("Scheduled task 'check_weibo_updates' failed: %s", exc)

    def _build_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{self.api_config['api_base_url'].rstrip('/')}/",
            "Accept": "application/json, text/plain, */*",
        }

    def _request_json_sync(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = requests.get(url, params=params, headers=self._build_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    async def _request_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await asyncio.to_thread(self._request_json_sync, url, params)

    async def _fetch_user_info(self, user_id: str) -> Optional[Dict[str, str]]:
        try:
            data = await self._request_json(
                f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['user_info_path']}",
                {"type": "uid", "value": user_id},
            )
            if data.get("ok") != 1:
                return None
            user = (data.get("data") or {}).get("userInfo") or {}
            if not user:
                return None
            return {
                "id": str(user.get("id") or user_id),
                "name": str(user.get("screen_name") or user.get("name") or "未命名微博用户"),
            }
        except Exception:
            self.logger.exception("Failed to validate weibo uid %s", user_id)
            return None

    async def _fetch_latest_update(self, user_id: str) -> Optional[Dict[str, Any]]:
        user_id = self._normalize_user_id(user_id)
        if not user_id:
            return None

        try:
            info_url = f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['user_info_path']}"
            info_params = {"type": "uid", "value": user_id}
            info_data = await self._request_json(info_url, info_params)
            if info_data.get("ok") != 1:
                return None

            user_info = (info_data.get("data") or {}).get("userInfo") or {}
            user_name = user_info.get("screen_name") or user_info.get("name") or "微博用户"

            tabs = (info_data.get("data") or {}).get("tabsInfo", {}).get("tabs") or []
            container_id = None
            for tab in tabs:
                if tab.get("tab_type") == "weibo":
                    container_id = tab.get("containerid")
                    break

            if not container_id:
                container_id = f"107603{user_id}_-_WEIBO_SECOND_PROFILE_WEIBO"

            feed_url = f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['user_info_path']}"
            feed_params = {
                "type": "uid",
                "value": user_id,
                "containerid": container_id,
            }
            feed_data = await self._request_json(feed_url, feed_params)
            cards = (feed_data.get("data") or {}).get("cards") or []
            if not cards:
                return None

            for card in cards:
                if card.get("card_type") != "9":
                    continue
                mblog = card.get("mblog") or {}
                item_id = str(mblog.get("idstr") or mblog.get("id") or "").strip()
                if not item_id:
                    continue

                title = self._to_text(mblog.get("text") or "微博动态")
                if len(title) > 100:
                    title = title[:97] + "..."

                pics = mblog.get("pics") or []
                cover = pics[0].get("url") if pics and isinstance(pics[0], dict) else ""
                link = f"{self.api_config['api_base_url'].rstrip('/')}{self.api_config['detail_path']}/{item_id}"

                return {
                    "id": item_id,
                    "title": title,
                    "link": link,
                    "cover": cover,
                    "time": mblog.get("created_at"),
                    "author": user_name,
                }

            return None
        except Exception as exc:
            self.logger.exception("Failed to fetch latest weibo update for uid %s: %s", user_id, exc)
            return None

    def _build_message(self, item: Dict[str, Any]) -> MessageArray:
        msg = MessageArray()
        author = item.get("author") or "微博用户"
        msg.add_text(f"📢 {author} 发布了新动态\n")
        msg.add_text(f"内容：{item.get('title', '新动态')}\n")
        if item.get("cover"):
            msg.add_image(item["cover"])
        msg.add_text(f"链接：{item.get('link', '')}\n")
        return msg

    @registrar.qq.on_group_command(".微博订阅", ignore_case=True)
    async def on_group_subscribe(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if raw_text.lower().startswith(".微博订阅"):
            user_id = self._normalize_user_id(raw_text[len(".微博订阅"):])
        else:
            user_id = ""

        if not user_id:
            await event.reply("用法：.微博订阅 <微博UID或链接>\n例如：.微博订阅 1234567890")
            return

        user_info = await self._fetch_user_info(user_id)
        if not user_info:
            await event.reply(f"未找到微博用户：{user_id}，请检查 UID 或链接是否正确。")
            return

        subscribed_users = self._scope_subscriptions(event)
        if user_id not in subscribed_users:
            subscribed_users.append(user_id)
            self._save_runtime_config()

            await event.reply(f"已订阅微博用户：{user_info['name']}（UID：{user_info['id']}）")
        else:
            await event.reply(f"该微博用户已订阅：{user_info['name']}（UID：{user_info['id']}）")

    @registrar.qq.on_group_command(".微博取消订阅", ignore_case=True)
    async def on_group_unsubscribe(self, event: GroupMessageEvent):
        raw_text = event.raw_message.strip()
        if raw_text.lower().startswith(".微博取消订阅"):
            user_id = self._normalize_user_id(raw_text[len(".微博取消订阅"):])
        else:
            user_id = ""

        if not user_id:
            await event.reply("用法：.微博取消订阅 <微博UID或链接>")
            return

        subscribed_users = self._scope_subscriptions(event)
        if user_id in subscribed_users:
            subscribed_users.remove(user_id)
            self._save_runtime_config()
            await event.reply(f"已取消订阅：{user_id}")
        else:
            await event.reply(f"当前没有订阅：{user_id}")

    @registrar.qq.on_group_command(".微博列表", ignore_case=True)
    async def on_group_list(self, event: GroupMessageEvent):
        subscribed_users = self._scope_subscriptions(event)
        if not subscribed_users:
            await event.reply("当前没有订阅任何微博用户。")
            return
        await event.reply("已订阅的微博用户：\n" + "\n".join(subscribed_users))

    @registrar.qq.on_private_command(".微博订阅", ignore_case=True)
    async def on_private_subscribe(self, event: PrivateMessageEvent):
        await self.on_group_subscribe(event)

    @registrar.qq.on_private_command(".微博取消订阅", ignore_case=True)
    async def on_private_unsubscribe(self, event: PrivateMessageEvent):
        await self.on_group_unsubscribe(event)

    @registrar.qq.on_private_command(".微博列表", ignore_case=True)
    async def on_private_list(self, event: PrivateMessageEvent):
        await self.on_group_list(event)

    def _save_runtime_config(self):
        base_dir = Path(__file__).resolve().parents[2]
        config_path = base_dir / "config.yaml"
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.monitor_config["subscriptions"] = self.subscriptions
        data["weibo_monitor"] = self.monitor_config
        config["weibo_monitor"] = self.monitor_config

        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
