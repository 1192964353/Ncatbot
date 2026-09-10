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
from typing import List, Dict, Optional


class LoliconPlugin(NcatBotPlugin):
    name = "Lolicon"
    version = "1.0.0"

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

        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    "Referer": "https://www.pixiv.net/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
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
                        self.logger.warning(f"下载内容异常（过小）: {url}, 大小: {len(content)} 字节")
                        return None, "content_invalid"
                    self.logger.warning(f"下载失败，状态码: {response.status}, url: {url}")
                    return None, f"http_{response.status}"
        except asyncio.TimeoutError:
            self.logger.error(f"下载图片超时: {url}")
            return None, "timeout"
        except aiohttp.ClientError as e:
            self.logger.error(f"下载图片网络错误: {url}, 错误: {e}")
            return None, "network"
        except Exception as e:
            self.logger.error(f"下载图片异常: {url}, 错误: {e}")
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
    ) -> "tuple[List[Dict], Optional[str]]":
        """调用 Lolicon API，返回 (图片数据列表, 失败原因)，成功且有结果时失败原因为 None"""
        api_url = "https://api.lolicon.app/setu/v2"
        # 支持传递多个同名 query 参数（多个 tag）
        if not tags:
            tags = ["萝莉"]
        # 使用 list[tuple] 以便生成重复的 `tag=...` 参数
        params = [("r18", r18), ("num", count), ("size", "regular")]
        for tag in tags:
            if tag:
                params.append(("tag", tag))
        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url, params=params) as response:
                    if response.status != 200:
                        self.logger.warning(f"Lolicon API 返回异常状态码: {response.status}")
                        return [], f"http_{response.status}"
                    data = await response.json()
                    error_msg = data.get("error") or ""
                    if error_msg:
                        self.logger.warning(f"Lolicon API 返回错误: {error_msg}")
                        return [], "api_error"
                    raw_list = data.get("data", [])
                    # 为支持客户端的 AND 语义：先请求较多条目以提高命中率，再在客户端过滤
                    request_limit = min(30, max(count, count * 3))
                    result = raw_list[:request_limit]

                    def _normalize_tags_field(item) -> List[str]:
                        t = item.get("tags") or item.get("tag") or item.get("tags", [])
                        if isinstance(t, str):
                            # 按空白或逗号切分
                            parts = [p.strip().lower() for p in re.split(r"[\s,]+", t) if p.strip()]
                            return parts
                        if isinstance(t, list):
                            return [str(p).strip().lower() for p in t]
                        return []

                    import re

                    # 执行 AND 过滤：图片必须包含所有请求的标签（大小写不敏感）
                    wanted = [str(x).strip().lower() for x in (tags or []) if x]
                    if wanted:
                        filtered = []
                        for item in result:
                            item_tags = _normalize_tags_field(item)
                            # 如果没有返回 tag 列表，则保守认为不匹配
                            if not item_tags:
                                continue
                            matched_all = True
                            for w in wanted:
                                # 允许子串匹配（更宽松），例如用户输入的短 tag
                                if not any(w in it for it in item_tags):
                                    matched_all = False
                                    break
                            if matched_all:
                                filtered.append(item)
                        result = filtered

                    if not result:
                        # API 正常响应但未匹配到结果，通常是 tag 不存在或组合无结果
                        return [], "no_result"
                    return result[:count], None
        except asyncio.TimeoutError:
            self.logger.error("调用 Lolicon API 超时")
            return [], "timeout"
        except aiohttp.ClientError as e:
            self.logger.error(f"调用 Lolicon API 网络错误: {e}")
            return [], "network"
        except Exception as e:
            self.logger.error(f"调用 API 异常: {e}")
            return [], "exception"

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
        tag = "萝莉"
        if len(args) > 1:
            try:
                count = int(args[1])
            except ValueError:
                tag = args[1]
        if len(args) > 2:
            tag = args[2]

        count = max(1, min(10, count))
        images_data, error_code = await self._call_lolicon_api(count=count, r18=0, tags=[tag])

        if not images_data:
            await event.reply(text=self._api_error_message(error_code))
            return

        await self._send_images(event, images_data)

    @registrar.qq.on_private_command("/r18", ignore_case=True)
    async def r18_cmd(self, event: PrivateMessageEvent):
        """发送 R18 二次元图片命令（仅限私聊）"""
        args = event.raw_message.split()
        count = 1
        tag = ""
        if len(args) > 1:
            try:
                count = int(args[1])
            except ValueError:
                tag = args[1]
        if len(args) > 2:
            tag = args[2]

        count = max(1, min(5, count))
        tags = [tag] if tag else ["萝莉"]
        images_data, error_code = await self._call_lolicon_api(count=count, r18=1, tags=tags)

        if not images_data:
            await event.reply(text=self._api_error_message(error_code))
            return

        await self._send_images(event, images_data)

    async def _send_images(self, event: MessageEvent, images_data: List[Dict]):
        urls = [
            img.get("urls", {}).get("regular", "")
            for img in images_data
            if img.get("urls", {}).get("regular")
        ]
        if not urls:
            await event.reply(text="没有可用的图片链接")
            return

        await event.reply(text="正在获取图片，请稍候...")
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

        # 分批发送，每批最多 5 张
        batch_size = min(5, len(valid_paths))
        total_sent = 0
        upload_fail_count = 0

        for i in range(0, len(valid_paths), batch_size):
            batch = valid_paths[i : i + batch_size]
            
            # 构造 MessageArray
            msg_array = MessageArray()
            for path in batch:
                # ncatbot5 内部可能会自动处理协议前缀，这里直接传本地绝对路径
                msg_array.add_image(str(path.absolute()))
                
            try:
                # 使用用户提供的 API 方法发送
                if isinstance(event, GroupMessageEvent):
                    await self.api.qq.post_group_array_msg(group_id=event.group_id, msg=msg_array)
                elif isinstance(event, PrivateMessageEvent):
                    await self.api.qq.post_private_array_msg(user_id=event.user_id, msg=msg_array)
                else:
                    # 回退到 reply
                    await event.reply(rtf=msg_array)
                    
                total_sent += len(batch)
            except Exception as e:
                self.logger.error(f"发送图片失败: {e}")
                upload_fail_count += len(batch)

            if i + batch_size < len(valid_paths):
                await asyncio.sleep(0.5)

        download_fail_count = sum(fail_reasons.values())
        if download_fail_count > 0 or upload_fail_count > 0:
            detail_parts = []
            if download_fail_count > 0:
                detail_parts.append(f"下载失败 {download_fail_count} 张（{self._format_fail_reasons(fail_reasons)}）")
            if upload_fail_count > 0:
                detail_parts.append(f"上传失败 {upload_fail_count} 张")
            await event.reply(text=f"发送完成！成功: {total_sent} 张；{'；'.join(detail_parts)}")

    def _format_fail_reasons(self, fail_reasons: Dict[str, int]) -> str:
        """将下载失败原因统计转换为可读文案"""
        labels = {
            "timeout": "网络超时",
            "network": "网络连接异常",
            "content_invalid": "图片内容异常",
            "exception": "未知错误",
        }
        parts = []
        for reason, count in fail_reasons.items():
            if reason.startswith("http_"):
                label = f"服务器返回状态码 {reason[5:]}"
            else:
                label = labels.get(reason, reason)
            parts.append(f"{label} x{count}")
        return "、".join(parts) if parts else "未知原因"


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
