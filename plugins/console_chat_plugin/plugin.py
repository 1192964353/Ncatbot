"""通过服务器控制台向 QQ 群或用户发送文本消息。"""

import asyncio
import sys
from typing import Any

from ncatbot.core import registrar
from ncatbot.plugin import NcatBotPlugin
from ncatbot.types import MessageArray


class ConsoleChatPlugin(NcatBotPlugin):
    name = "console_chat"
    version = "1.0.0"

    async def on_load(self):
        self._console_running = True
        if not sys.stdin or not sys.stdin.isatty():
            self._console_running = False
            self.logger.warning(
                "当前进程没有交互式控制台，跳过 console_chat 输入监听；QQ 插件仍会正常工作"
            )
            return
        self._console_task = asyncio.create_task(self._console_loop())
        self.logger.info(
            "控制台聊天已启动：输入 help 查看帮助，输入 quit 停止控制台监听"
        )

    async def on_close(self):
        self._console_running = False
        task = getattr(self, "_console_task", None)
        if task and not task.done():
            task.cancel()

    @staticmethod
    def _help_text() -> str:
        return (
            "控制台聊天命令：\n"
            "  g <群号> <消息>       发送群消息\n"
            "  u <QQ号> <消息>       发送私聊消息\n"
            "  all <消息>            发送到机器人加入的所有群\n"
            "  groups                查看机器人所在群\n"
            "  help                  显示帮助\n"
            "  quit                  停止控制台监听\n"
        )

    async def _console_loop(self):
        print(self._help_text(), flush=True)
        while self._console_running:
            try:
                line = await asyncio.to_thread(input, "qq> ")
            except (EOFError, KeyboardInterrupt):
                self._console_running = False
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("控制台输入读取失败")
                continue

            await self._handle_console_line(line.strip())

    async def _handle_console_line(self, line: str):
        if not line:
            return
        parts = line.split(maxsplit=2)
        command = parts[0].lower()

        if command == "help":
            print(self._help_text(), flush=True)
            return
        if command == "quit":
            self._console_running = False
            print("控制台聊天已停止。", flush=True)
            return
        if command == "groups":
            await self._list_groups()
            return
        if command == "g":
            if len(parts) < 3 or not parts[1].isdigit():
                print("用法：g <群号> <消息>", flush=True)
                return
            await self._send_group(parts[1], parts[2])
            return
        if command == "u":
            if len(parts) < 3 or not parts[1].isdigit():
                print("用法：u <QQ号> <消息>", flush=True)
                return
            await self._send_private(parts[1], parts[2])
            return
        if command == "all":
            if len(parts) < 2:
                print("用法：all <消息>", flush=True)
                return
            await self._send_to_all_groups(parts[1] if len(parts) == 2 else line[len(parts[0]) + 1 :])
            return

        print("未知命令，输入 help 查看帮助。", flush=True)

    @staticmethod
    def _text_message(text: str) -> MessageArray:
        message = MessageArray()
        message.add_text(text)
        return message

    async def _send_group(self, group_id: str, text: str):
        try:
            await self.api.qq.post_group_array_msg(
                group_id=group_id, msg=self._text_message(text)
            )
            print(f"已发送到群 {group_id}。", flush=True)
        except Exception:
            self.logger.exception("控制台发送群消息失败: %s", group_id)
            print(f"发送到群 {group_id} 失败，详情请查看日志。", flush=True)

    async def _send_private(self, user_id: str, text: str):
        try:
            await self.api.qq.post_private_array_msg(
                user_id=user_id, msg=self._text_message(text)
            )
            print(f"已发送给用户 {user_id}。", flush=True)
        except Exception:
            self.logger.exception("控制台发送私聊消息失败: %s", user_id)
            print(f"发送给用户 {user_id} 失败，详情请查看日志。", flush=True)

    async def _get_group_ids(self) -> list[str]:
        get_group_list = getattr(self.api.qq, "get_group_list", None)
        if get_group_list is None:
            query = getattr(self.api.qq, "query", None)
            get_group_list = getattr(query, "get_group_list", None)
        if get_group_list is None:
            return []

        result = await get_group_list()
        groups: Any = result.get("data", result) if isinstance(result, dict) else result
        if not isinstance(groups, list):
            return []

        group_ids = []
        for item in groups:
            if isinstance(item, dict):
                group_id = item.get("group_id") or item.get("id")
            else:
                group_id = getattr(item, "group_id", None) or getattr(item, "id", None)
            if group_id is not None:
                group_ids.append(str(group_id))
        return group_ids

    async def _list_groups(self):
        try:
            group_ids = await self._get_group_ids()
            print(
                "当前群组：" + (", ".join(group_ids) if group_ids else "未获取到群组"),
                flush=True,
            )
        except Exception:
            self.logger.exception("控制台获取群列表失败")
            print("获取群列表失败，详情请查看日志。", flush=True)

    async def _send_to_all_groups(self, text: str):
        try:
            group_ids = await self._get_group_ids()
        except Exception:
            self.logger.exception("控制台获取群列表失败")
            print("获取群列表失败，详情请查看日志。", flush=True)
            return

        if not group_ids:
            print("未获取到机器人所在的群。", flush=True)
            return

        success = 0
        for group_id in group_ids:
            try:
                await self.api.qq.post_group_array_msg(
                    group_id=group_id, msg=self._text_message(text)
                )
                success += 1
            except Exception:
                self.logger.exception("控制台群发失败: %s", group_id)
            await asyncio.sleep(1)
        print(f"群发完成：成功 {success}/{len(group_ids)} 个群。", flush=True)
