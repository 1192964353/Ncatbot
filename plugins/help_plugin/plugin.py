import re

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin


PLUGIN_LIST_TEXT = """🤖 机器人插件类型

1. AI功能
2. 图片娱乐
3. 游戏资讯
4. 计算工具
5. 新闻资讯
6. 订阅监控
7. 群管理
8. 提醒任务
9. 实用工具
10. 权限与状态
11. 下载工具

输入 `.help 新闻资讯` 或 `.help 5` 查看对应类别的具体指令，类别或序号前的空格可有可无；`.帮助` 是中文别名。
"""


PLUGIN_HELP_TEXT = """🤖 插件帮助用法

请在 `.help` 后输入插件类型或序号，空格可加可不加，例如：
- .help AI功能
- .helpAI功能
- .help 新闻资讯
- .help新闻资讯
- .help 5
- .help5
- .help 实用工具
- .help 9
- .help 权限与状态
- .help 10
"""


CATEGORY_HELP = {
    "AI功能": """🤖 AI 功能
- .ai <问题>
  例如：.ai 你好，帮我总结今天的会议
- .ai出图 <描述>
  例如：.ai出图 一只可爱的金毛小狗在草地奔跑
""",
    "图片娱乐": """🖼️ 图片娱乐
- .jk
    获取随机图片。
- .loli [数量] [标签]
- .萝莉 [数量] [标签]
    获取随机二次元图片，数量最多 10 张；未指定标签时使用“萝莉”。
- /r18 [数量] [标签]
    获取 R18 二次元图片，仅支持私聊，数量最多 5 张。
- /清理缓存
- /loli_clear
    清理 Lolicon 图片缓存。
""",
        "下载工具": """📥 下载工具
- .jm <本子ID>
    下载并发送禁漫本子 PDF；本子 ID 必须是纯数字。
- .jmzip <本子ID>
    下载并发送禁漫本子 ZIP；ZIP 发送失败时回退发送 PDF。
    支持群聊和私聊，文件会缓存到项目根目录的 pdf/ 文件夹。
""",
    "新闻资讯": """📰 新闻资讯
- .每日新闻
  获取每日新闻图片。
""",
    "游戏资讯": """🎮 游戏资讯
- .免费游戏
  获取本周 EPIC 免费游戏。
""",
    "计算工具": """🧮 计算工具
- .calc <表达式>
- .计算 <表达式>
  例如：.calc 12*(3+4)/2
""",
    "订阅监控": """📡 订阅监控
- .b站订阅 <UP主UID>
- .b站取消订阅 <UP主UID>
- .b站列表
- .微博订阅 <微博UID或链接>
- .微博取消订阅 <微博UID或链接>
- .微博列表
- .订阅 rss <URL>
- .订阅 github <owner/repo>
- .订阅列表
- .取消订阅 <编号>
    B站、微博、RSS 和 GitHub 订阅均按群聊或私聊用户分别隔离；RSS、GitHub 及统一订阅的列表、取消操作仅支持群聊。
""",
    "群管理": """🛡️ 群管理
- .禁言 @用户或QQ号 [分钟]
- .解禁 @用户或QQ号
- .踢出 @用户或QQ号
- .全员禁言
- .解除全员禁言
- .公告 <内容>（发送群内公告消息）
  仅群主或管理员可以使用。
""",
    "提醒任务": """⏰ 提醒任务
- .提醒 20分钟后 开会
- .提醒列表
- .取消提醒 <编号>
  时间支持秒、分钟、小时、天；创建提醒支持私聊，列表和取消仅支持群聊。
""",
        "实用工具": """🧰 实用工具
- .天气 <城市>
- .翻译 <内容>
- .翻译 日译中 <内容>
- .二维码 <文字或链接>
- .链接 <URL>
- .短链接 <URL>
""",
        "权限与状态": """🔐 权限与状态
- .授权 @用户或QQ号
- .取消授权 @用户或QQ号
- .权限列表
- .状态
- .插件状态
- .错误日志
    授权管理需要群主或管理员；错误日志仅机器人所有者可查看；状态和插件状态不限制权限。
""",
}


CATEGORY_BY_NUMBER = {
    "1": "AI功能",
    "2": "图片娱乐",
    "3": "游戏资讯",
    "4": "计算工具",
    "5": "新闻资讯",
    "6": "订阅监控",
    "7": "群管理",
    "8": "提醒任务",
    "9": "实用工具",
    "10": "权限与状态",
    "11": "下载工具",
}


class HelpPlugin(NcatBotPlugin):
    @registrar.qq.on_group_message()
    async def on_group_help(self, event: GroupMessageEvent):
        if self._is_help_command(event.raw_message):
            await event.reply(self._help_text(event.raw_message))

    @registrar.qq.on_private_message()
    async def on_private_help(self, event: PrivateMessageEvent):
        if self._is_help_command(event.raw_message):
            await event.reply(self._help_text(event.raw_message))

    @staticmethod
    def _is_help_command(raw_message: str) -> bool:
        return bool(re.match(r"^\.(?:help|帮助)(?:\s*\S+)?\s*$", raw_message.strip(), re.IGNORECASE))

    @staticmethod
    def _help_text(raw_message: str) -> str:
        raw_text = raw_message.strip()
        match = re.match(r"^\.(?:help|帮助)(.*)$", raw_text, re.IGNORECASE)
        if not match:
            return PLUGIN_LIST_TEXT

        selector = match.group(1).strip().split(maxsplit=1)
        if not selector:
            return PLUGIN_LIST_TEXT

        selector_text = selector[0]
        category = CATEGORY_BY_NUMBER.get(selector_text)
        if category is None:
            normalized_selector = selector_text.casefold()
            category = next(
                (name for name in CATEGORY_HELP if name.casefold() == normalized_selector),
                None,
            )
        if category is None:
            return PLUGIN_HELP_TEXT
        return CATEGORY_HELP[category]
