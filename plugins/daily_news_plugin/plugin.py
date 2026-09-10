from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import asyncio

import yaml
import requests
import os
from pathlib import Path



def load_config():
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


config = load_config()
news_image_url = config["apis"]["urls"]["daily_news_image"]


class NewsPlugin(NcatBotPlugin):
    async def on_load(self):
        if self.add_scheduled_task("push_news", interval="9:00"):
            self.logger.info("每日新闻定时任务已注册，将在每天 9:00 执行")
        else:
            self.logger.error("每日新闻定时任务注册失败")

    async def push_news(self):
        group_ids = await self._get_group_ids()
        if not group_ids:
            self.logger.warning("每日新闻未发送：未获取到可推送的群组")
            return

        self.logger.info("开始向 %d 个群组推送每日新闻", len(group_ids))
        message = await self.get_news()
        sent_count = 0
        for group_id in group_ids:
            try:
                await self.api.qq.post_group_array_msg(group_id=group_id, msg=message)
                sent_count += 1
            except Exception:
                self.logger.exception("向群组 %s 推送每日新闻失败", group_id)
            await asyncio.sleep(1)
        self.logger.info("每日新闻推送完成：成功 %d/%d 个群组", sent_count, len(group_ids))

    async def _get_group_ids(self):
        get_group_list = getattr(self.api.qq, "get_group_list", None)
        if get_group_list is None:
            self.logger.warning("当前 API 不支持获取群列表，跳过每日新闻定时推送")
            return []
        try:
            result = await get_group_list()
            groups = result.get("data", result) if isinstance(result, dict) else result
            if not isinstance(groups, list):
                self.logger.warning("获取群列表返回了非列表数据：%s", type(groups).__name__)
                return []
            group_ids = [str(item["group_id"]) for item in groups if isinstance(item, dict) and item.get("group_id")]
            self.logger.info("获取到 %d 个群组用于每日新闻推送", len(group_ids))
            return group_ids
        except Exception:
            self.logger.exception("Failed to get group list for daily news")
            return []

    @registrar.qq.on_group_command(".每日新闻", ignore_case=True)
    async def on_group_get_news(self, event: GroupMessageEvent):
        await event.reply(await self.get_news())

    @registrar.qq.on_private_command(".每日新闻", ignore_case=True)
    async def on_private_get_news(self, event: PrivateMessageEvent):
        await event.reply(await self.get_news())

    async def get_news(self):
        msg = MessageArray()
        msg.add_text("《每日新闻》\n")
        msg.add_image(news_image_url)
        return msg

def download_image_to_local(image_url: str, save_dir: str = "./images", filename: str = None) -> str:
    """
    下载图片到本地并返回保存路径

    Args:
        image_url (str): 图片的URL地址
        save_dir (str): 保存目录，默认为 ./images
        filename (str): 自定义文件名（不含后缀），如果不传则自动生成

    Returns:
        str: 图片在本地的完整路径
    """
    try:
        # 1. 创建保存目录（如果不存在）
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        # 2. 下载图片
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()

        # 3. 确定文件后缀（从 Content-Type 或 URL 中推断）
        content_type = resp.headers.get('content-type', '')
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        else:
            ext = '.jpg'

        # 4. 确定文件名
        if filename is None:
            timestamp = int(time.time())
            filename = f"image_{timestamp}{ext}"
        else:
            filename = f"{filename}{ext}"

        # 5. 保存到本地
        file_path = os.path.join(save_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(resp.content)

        return file_path

    except requests.exceptions.Timeout:
        print("下载超时")
        return None
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return None
    except Exception as e:
        print(f"保存失败: {e}")
        return None
