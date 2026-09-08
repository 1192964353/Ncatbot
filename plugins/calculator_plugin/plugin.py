import ast
import operator
import re
from typing import Any

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent, PrivateMessageEvent
from ncatbot.plugin import NcatBotPlugin


_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorPlugin(NcatBotPlugin):
    @staticmethod
    def _format_number(value: Any) -> str:
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            text = format(value, ".12g")
            return text.rstrip("0").rstrip(".") if "." in text else text
        return str(value)

    @classmethod
    def calculate(cls, expression: str) -> str:
        raw = (expression or "").strip()
        if not raw:
            raise ValueError("空表达式")

        if re.search(r"[A-Za-z_\\]", raw):
            raise ValueError("表达式中不能包含字母或下划线")

        try:
            tree = ast.parse(raw, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"语法错误: {exc.msg}") from exc

        def _eval(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return _eval(node.body)

            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    return node.value
                raise ValueError("仅支持数字常量")

            if isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                op_type = type(node.op)
                if op_type not in _ALLOWED_BIN_OPS:
                    raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
                return _ALLOWED_BIN_OPS[op_type](left, right)

            if isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                op_type = type(node.op)
                if op_type not in _ALLOWED_UNARY_OPS:
                    raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
                return _ALLOWED_UNARY_OPS[op_type](operand)

            raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

        result = _eval(tree)
        if isinstance(result, complex):
            raise ValueError("不支持复数结果")

        return cls._format_number(result)

    @registrar.qq.on_group_command(".calc", ignore_case=True)
    async def on_group_calc(self, event: GroupMessageEvent):
        text = event.raw_message.strip()
        if text.lower().startswith(".calc"):
            expr = text[5:].strip()
        else:
            expr = ""

        if not expr:
            await event.reply("用法：.calc <表达式>\n例如：.calc 12*(3+4)")
            return

        try:
            result = self.calculate(expr)
        except Exception:
            await event.reply("表达式无效，请输入合法的四则运算表达式。\n例如：.calc 12*(3+4) / 2")
            return

        await event.reply(f"计算结果：{result}")

    @registrar.qq.on_group_command(".计算", ignore_case=True)
    async def on_group_calc_cn(self, event: GroupMessageEvent):
        text = event.raw_message.strip()
        if text.lower().startswith(".计算"):
            expr = text[3:].strip()
        else:
            expr = ""

        if not expr:
            await event.reply("用法：.计算 <表达式>\n例如：.计算 12*(3+4)")
            return

        try:
            result = self.calculate(expr)
        except Exception:
            await event.reply("表达式无效，请输入合法的四则运算表达式。\n例如：.计算 12*(3+4) / 2")
            return

        await event.reply(f"计算结果：{result}")

    @registrar.qq.on_private_command(".calc", ignore_case=True)
    async def on_private_calc(self, event: PrivateMessageEvent):
        await self.on_group_calc(event)

    @registrar.qq.on_private_command(".计算", ignore_case=True)
    async def on_private_calc_cn(self, event: PrivateMessageEvent):
        await self.on_group_calc_cn(event)
