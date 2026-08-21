# plugin.py
from ncatbot.plugin import NcatBotPlugin
import requests
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
import yaml

class AgnesPlugin(NcatBotPlugin):
    """Agnes AI 文本模型插件"""
    
    # 配置（建议从环境变量读取，不要硬编码）
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    API_KEY = config["apis"]["agnes"]["api_key"]
    BASE_URL = config["apis"]["agnes"]["chat_base_url"]
    MODEL = "agnes-2.0-flash"

    print("API_KEY=",API_KEY,"BASE_URL=",BASE_URL )
    
    async def on_load(self):
        """插件加载时打印提示"""
        print("🤖 Agnes AI 插件已加载！")
        print("💡 在群里 @我 并发送消息即可获得 AI 回复。")

    @registrar.qq.on_group_command(".ai", ignore_case=True)
    async def on_group_chat(self, event: GroupMessageEvent):
        """处理消息事件"""
        
        raw_text = event.raw_message.strip()

        # 2. 提取用户问题（去掉 @ 和 /ai 前缀）
        question = raw_text[3:].strip()
        
        if not question:
            await event.reply("请问你想问什么呢？直接说问题就好～")
            return
        
        # 3. 调用 Agnes AI
        await self._call_agnes_and_reply(event, question)

    @registrar.qq.on_group_message()
    async def on_group_at_chat(self, event: GroupMessageEvent ):
        """处理消息事件"""
        if not (event.message.is_at(2805737403)):
            return  # 没被艾特就不回复
        raw_text = event.raw_message.strip()

        #获取正文
        question = raw_text[3:].strip()  
        print("question:",question)
        if not question:
            await event.reply("请问你想问什么呢？直接说问题就好～")
            return
        
        # 3. 调用 Agnes AI
        await self._call_agnes_and_reply(event, question)
    
    async def _call_agnes_and_reply(self, event, question: str):
        """调用 Agnes AI 并回复"""
        
        url = f"{self.BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": "你是一个智能助手，回答简洁友好。"},
                {"role": "user", "content": question}
            ],
            "stream": False
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                reply = result['choices'][0]['message']['content']
                
                # 如果回复太长，适当截断（QQ消息有长度限制）
                if len(reply) > 2000:
                    reply = reply[:1997] + "..."
                
                await event.reply(reply)
            else:
                await event.reply(f"❌ AI 服务暂时不可用，请稍后再试。（错误码: {response.status_code}）")
                
        except requests.exceptions.Timeout:
            await event.reply("⏰ 请求超时，AI 可能正在忙，请稍后重试。")
        except Exception as e:
            await event.reply(f"❌ 发生错误: {str(e)[:100]}")