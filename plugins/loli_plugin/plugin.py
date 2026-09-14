"""Lolicon 插件 — 调用 Lolicon API v2 发送随机二次元图片。"""

from ncatbot.plugin import NcatBotPlugin
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent, MessageEvent
from ncatbot.types import MessageArray, Image
from pathlib import Path
import aiohttp
import json
import asyncio
import hashlib
import time
import re
from typing import List, Dict, Optional


class LoliconPlugin(NcatBotPlugin):
    name = "Lolicon"
    version = "1.0.0"
    blocked_tags = {"ai","AI","Ai"}

    async def on_load(self):
        self.cache_dir = Path("plugins/Lolicon/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_index_file = self.cache_dir / "cache_index.json"
        self.cache_index = self._load_cache_index()
        self.logger.info(f"{self.name} 插件已加载")

    def _load_cache_index(self) -> Dict:
        if self.cache_index_file.exists():
            try:
                with open(self.cache_index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"加载缓存索引失败: {e}")
        return {}

    def _save_cache_index(self):
        try:
            with open(self.cache_index_file, "w", encoding="utf-8") as f:
                json.dump(self.cache_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存缓存索引失败: {e}")

    def _get_cache_path(self, url: str) -> Path:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return self.cache_dir / f"{url_hash}.jpg"

    async def _download_image(self, url: str) -> "tuple[Optional[Path], Optional[str]]":
        """下载图片，返回 (缓存路径, 失败原因)，成功时失败原因为 None"""
        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            return cache_path, None

        timeout = aiohttp.ClientTimeout(total=30, connect=15, sock_read=25)
        headers = {
            "Referer": "https://www.pixiv.net/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        max_attempts = 3

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with session.get(url, headers=headers, ssl=False) as response:
                        if response.status == 200:
                            content = await response.read()
                            if len(content) > 1000:
                                with open(cache_path, "wb") as f:
                                    f.write(content)
                                self.cache_index[url] = {
                                    "path": str(cache_path),
                                    "timestamp": time.time(),
                                    "size": len(content),
                                }
                                self._save_cache_index()
                                return cache_path, None

                            self.logger.warning(
                                "下载内容异常（过小），第 %d/%d 次: %s, 大小: %d 字节",
                                attempt,
                                max_attempts,
                                url,
                                len(content),
                            )
                            if attempt == max_attempts:
                                return None, "content_invalid"
                        elif response.status >= 500:
                            self.logger.warning(
                                "下载服务端错误，第 %d/%d 次: %s, 状态码: %d",
                                attempt,
                                max_attempts,
                                url,
                                response.status,
                            )
                            if attempt == max_attempts:
                                return None, f"http_{response.status}"
                        else:
                            self.logger.warning(
                                "下载失败，状态码: %d, url: %s",
                                response.status,
                                url,
                            )
                            return None, f"http_{response.status}"
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "下载图片超时，第 %d/%d 次: %s",
                        attempt,
                        max_attempts,
                        url,
                    )
                    if attempt == max_attempts:
                        return None, "timeout"
                except aiohttp.ClientError as e:
                    self.logger.warning(
                        "下载图片网络错误，第 %d/%d 次: %s, 错误: %s",
                        attempt,
                        max_attempts,
                        url,
                        e,
                    )
                    if attempt == max_attempts:
                        return None, "network"
                except Exception as e:
                    self.logger.error(f"下载图片异常: {url}, 错误: {e}")
                    return None, "exception"

                await asyncio.sleep(1.5 * attempt)

        return None, "exception"

    async def _download_images_concurrent(
        self, urls: List[str]
    ) -> List["tuple[Optional[Path], Optional[str]]"]:
        semaphore = asyncio.Semaphore(5)

        async def download_with_semaphore(url: str) -> "tuple[Optional[Path], Optional[str]]":
            async with semaphore:
                return await self._download_image(url)

        tasks = [download_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _call_lolicon_api(
        self, count: int = 1, r18: int = 0, tags: Optional[List[str]] = None
    ) -> "tuple[List[Dict], Optional[str], int]":
        """循环查询并过滤图片，返回 (图片列表, 失败原因, 屏蔽数量)。"""
        api_url = "https://api.lolicon.app/setu/v2"
        if not tags:
            tags = ["萝莉"]

        wanted = [str(tag).strip().lower() for tag in tags if tag]
        request_count = min(30, max(count, count * 3))
        blocked_count = 0
        collected = []
        seen_urls = set()

        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for _ in range(5):
                    params = [("r18", r18), ("num", request_count), ("size", "regular")]
                    for tag in tags:
                        if tag:
                            params.append(("tag", tag))

                    async with session.get(api_url, params=params) as response:
                        if response.status != 200:
                            self.logger.warning(f"Lolicon API 返回异常状态码: {response.status}")
                            return collected, f"http_{response.status}", blocked_count
                        data = await response.json()
                        error_msg = data.get("error") or ""
                        if error_msg:
                            self.logger.warning(f"Lolicon API 返回错误: {error_msg}")
                            return collected, "api_error", blocked_count

                        raw_items = data.get("data", [])
                        if not isinstance(raw_items, list):
                            self.logger.warning(
                                "Lolicon API data 不是列表：%s",
                                type(raw_items).__name__,
                            )
                            return collected, "api_error", blocked_count

                        self.logger.info(
                            "Lolicon API 本轮返回 %d 张，目标 %d 张，已收集 %d 张",
                            len(raw_items),
                            count,
                            len(collected),
                        )
                        for item in raw_items[:request_count]:
                            if not isinstance(item, dict):
                                continue
                            item_tags = self._normalize_tags_field(item)
                            ai_type = str(item.get("aiType", ""))
                            if ai_type == "2" or any(
                                blocked in item_tags for blocked in self.blocked_tags
                            ):
                                blocked_count += 1
                                continue
                            if not item_tags or any(
                                not any(w in item_tag for item_tag in item_tags)
                                for w in wanted
                            ):
                                continue
                            image_url = item.get("urls", {}).get("regular")
                            if image_url and image_url not in seen_urls:
                                seen_urls.add(image_url)
                                collected.append(item)
                                if len(collected) >= count:
                                    return collected[:count], None, blocked_count

                if not collected:
                    return [], "no_result", blocked_count
                self.logger.info(
                    "Lolicon API 查询结束：目标 %d 张，实际收集 %d 张，屏蔽 AI %d 张",
                    count,
                    len(collected),
                    blocked_count,
                )
                return collected[:count], None, blocked_count
        except asyncio.TimeoutError:
            self.logger.error("调用 Lolicon API 超时")
            return collected, "timeout", blocked_count
        except aiohttp.ClientError as e:
            self.logger.error(f"调用 Lolicon API 网络错误: {e}")
            return collected, "network", blocked_count
        except Exception as e:
            self.logger.error(f"调用 API 异常: {e}")
            return collected, "exception", blocked_count

    @staticmethod
    def _normalize_tags_field(item) -> List[str]:
        tags = item.get("tags") or item.get("tag") or []
        if isinstance(tags, str):
            return [tag.strip().lower() for tag in re.split(r"[\s,]+", tags) if tag.strip()]
        if isinstance(tags, list):
            return [str(tag).strip().lower() for tag in tags]
        return []

    def _api_error_message(self, error_code: Optional[str]) -> str:
        """将 API 错误码转换为易懂的提示文案"""
        if error_code == "no_result":
            return "没有找到符合条件的图片，请检查 tag 是否正确或换个标签试试"
        if error_code == "api_error":
            return "图片源接口返回错误，请稍后重试"
        if error_code == "timeout":
            return "请求图片源超时，请稍后重试"
        if error_code == "network":
            return "网络连接异常，无法访问图片源，请稍后重试"
        if error_code and error_code.startswith("http_"):
            return f"图片源服务异常（状态码 {error_code[5:]}），请稍后重试"
        return "获取图片失败，请稍后重试"

    @registrar.qq.on_command(".loli", ".萝莉", ignore_case=True)
    async def loli_cmd(self, event: MessageEvent):
        """发送随机二次元图片命令"""
        args = event.raw_message.split()
        count = 1
        tags: List[str] = []
        if len(args) > 1:
            try:
                count = int(args[1])
                tags = args[2:]
            except ValueError:
                tags = args[1:]

        # 过滤空标签并回退默认
        tags = [t for t in tags if t]
        if not tags:
            tags = ["萝莉"]

        count = max(1, min(10, count))
        images_data, error_code, blocked_count = await self._call_lolicon_api(
            count=count, r18=0, tags=tags
        )

        if not images_data:
            await event.reply(text=self._api_error_message(error_code))
            return

        await self._send_images(event, images_data, blocked_count)

    @registrar.qq.on_private_command("/r18", ignore_case=True)
    async def r18_cmd(self, event: PrivateMessageEvent):
        """发送 R18 二次元图片命令（仅限私聊）"""
        args = event.raw_message.split()
        count = 1
        tags: List[str] = []
        if len(args) > 1:
            try:
                count = int(args[1])
                tags = args[2:]
            except ValueError:
                tags = args[1:]

        tags = [t for t in tags if t]
        if not tags:
            tags = ["萝莉"]

        count = max(1, min(5, count))
        images_data, error_code, blocked_count = await self._call_lolicon_api(
            count=count, r18=1, tags=tags
        )

        if not images_data:
            await event.reply(text=self._api_error_message(error_code))
            return

        await self._send_images(event, images_data, blocked_count)

    async def _send_images(
        self, event: MessageEvent, images_data: List[Dict], blocked_count: int = 0
    ):
        image_tags = []
        for index, image in enumerate(images_data, start=1):
            tags = self._normalize_tags_field(image)
            image_tags.append(f"第{index}张: {', '.join(tags) if tags else '无标签'}")
        self.logger.info("本次发送图片的标签：%s", "；".join(image_tags))

        urls = [
            img.get("urls", {}).get("regular", "")
            for img in images_data
            if img.get("urls", {}).get("regular")
        ]
        if not urls:
            await event.reply(text="没有可用的图片链接")
            return

        blocked_text = f"，已屏蔽 {blocked_count} 张 AI 图片" if blocked_count else ""
        await event.reply(text=f"正在获取图片，请稍候{blocked_text}...")
        results = await self._download_images_concurrent(urls)

        # 过滤有效的图片路径，并统计下载失败原因
        valid_paths = []
        fail_reasons: Dict[str, int] = {}

        def record_fail(reason: str):
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"下载图片异常: {result}")
                record_fail("exception")
                continue
            path, reason = result
            if path and isinstance(path, Path) and path.exists():
                valid_paths.append(path)
            else:
                record_fail(reason or "exception")

        if not valid_paths:
            await event.reply(text=f"所有图片下载失败：{self._format_fail_reasons(fail_reasons)}")
            return

        self.logger.info(
            "Lolicon 图片下载完成：请求 %d 张，成功 %d 张，失败 %d 张",
            len(urls),
            len(valid_paths),
            len(urls) - len(valid_paths),
        )

        # 每张图片单独发送，避免多图消息体过大触发 NapCat API 1200 超时
        batch_size = 1
        total_sent = 0
        upload_fail_count = 0

        for i in range(0, len(valid_paths), batch_size):
            batch = valid_paths[i : i + batch_size]
            
            # 每次重试都会重新构造消息对象，避免复用已被 NapCat 处理过的上传消息。
            success, send_err = await self._post_image(
                event, batch[0], blocked_count
            )
            if success:
                total_sent += len(batch)
            else:
                self.logger.error(f"发送图片失败，原因: {send_err}")
                upload_fail_count += len(batch)
                # 记录上传失败原因以供汇总
                record_fail(send_err or "send_exception")

            if i + batch_size < len(valid_paths):
                await asyncio.sleep(2.0)

        download_fail_count = sum(fail_reasons.values())
        detail_parts = []
        if blocked_count > 0:
            detail_parts.append(f"已屏蔽 {blocked_count} 张 AI 图片")
        if download_fail_count > 0 or upload_fail_count > 0:
            if download_fail_count > 0:
                detail_parts.append(f"下载失败 {download_fail_count} 张（{self._format_fail_reasons(fail_reasons)}）")
            if upload_fail_count > 0:
                detail_parts.append(f"上传失败 {upload_fail_count} 张")
            await event.reply(text=f"发送完成！成功: {total_sent} 张；{'；'.join(detail_parts)}")
        elif blocked_count > 0:
            await event.reply(text=f"发送完成！成功: {total_sent} 张；{'；'.join(detail_parts)}")

    def _format_fail_reasons(self, fail_reasons: Dict[str, int]) -> str:
        """将下载失败原因统计转换为可读文案"""
        labels = {
            "timeout": "网络超时",
            "network": "网络连接异常",
            "content_invalid": "图片内容异常",
            "exception": "未知错误",
            "send_timeout": "发送超时",
            "send_api_1200": "平台 API 超时（1200）",
            "send_exception": "发送失败",
        }
        parts = []
        for reason, count in fail_reasons.items():
            if reason.startswith("http_"):
                label = f"服务器返回状态码 {reason[5:]}"
            else:
                label = labels.get(reason, reason)
            parts.append(f"{label} x{count}")
        return "、".join(parts) if parts else "未知原因"

    async def _post_image(
        self,
        event: MessageEvent,
        path: Path,
        blocked_count: int = 0,
        retries: int = 3,
    ) -> "tuple[bool, Optional[str]]":
        """发送单张本地图片；每次重试重新构造消息，降低 C1200 影响。"""
        last_err = None
        for attempt in range(retries + 1):
            msg_array = MessageArray()
            if blocked_count > 0:
                msg_array.add_text(f"已屏蔽 {blocked_count} 张 AI 图片\n")
            msg_array.add_image(str(path.absolute()))

            success, last_err = await self._post_array_msg(
                event,
                msg_array,
                retries=0,
                attempt_number=attempt + 1,
                total_attempts=retries + 1,
            )
            if success:
                return True, None
            if attempt < retries:
                if last_err == "send_api_1200":
                    delay = 3.0 * (attempt + 1)
                    self.logger.warning(
                        "图片发送遇到 API 1200，等待 %.1f 秒后重试（第 %d/%d 次）",
                        delay,
                        attempt + 2,
                        retries + 1,
                    )
                else:
                    delay = 1.5 * (attempt + 1)
                await asyncio.sleep(delay)
        return False, last_err

    async def _post_array_msg(
        self,
        event: MessageEvent,
        msg_array: MessageArray,
        retries: int = 3,
        attempt_number: Optional[int] = None,
        total_attempts: Optional[int] = None,
    ) -> "tuple[bool, Optional[str]]":
        """发送消息的封装：带短重试，返回 (success, error_code)。"""
        delay = 0.8
        last_err = None
        for attempt in range(retries + 1):
            try:
                if isinstance(event, GroupMessageEvent):
                    await self.api.qq.post_group_array_msg(group_id=event.group_id, msg=msg_array)
                elif isinstance(event, PrivateMessageEvent):
                    await self.api.qq.post_private_array_msg(user_id=event.user_id, msg=msg_array)
                else:
                    await event.reply(rtf=msg_array)
                return True, None
            except Exception as e:
                # 解析常见超时 / 平台返回码日志
                err_str = str(e)
                current_attempt = attempt_number or attempt + 1
                max_attempts = total_attempts or retries + 1
                self.logger.error(
                    f"发送图片异常（尝试 {current_attempt}/{max_attempts}）: {err_str}"
                )
                if '1200' in err_str:
                    last_err = 'send_api_1200'
                elif 'timeout' in err_str.lower() or 'timeout' in err_str:
                    last_err = 'send_timeout'
                else:
                    last_err = 'send_exception'

                if attempt < retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                return False, last_err


    @registrar.qq.on_command("/清理缓存", "/loli_clear", ignore_case=True)
    async def clear_cache_cmd(self, event: MessageEvent):
        """清理图片缓存命令"""
        await event.reply(text="正在清理清理缓存，请稍候...")
        try:
            count = 0
            total_size_bytes = 0
            
            # 遍历并删除缓存目录下的所有文件
            for file in self.cache_dir.iterdir():
                if file.is_file():
                    total_size_bytes += file.stat().st_size
                    file.unlink()
                    count += 1
            
            # 清空索引
            self.cache_index = {}
            self._save_cache_index()
            
            size_mb = total_size_bytes / (1024 * 1024)
            await event.reply(text=f"✅ 清理完成！\n删除了 {count} 个缓存文件，共释放 {size_mb:.2f} MB 空间。")
            self.logger.info(f"清理了 {count} 个缓存文件，共释放 {size_mb:.2f} MB")
        except Exception as e:
            self.logger.error(f"清理缓存失败: {e}")
            await event.reply(text=f"❌ 清理缓存失败: {e}")
