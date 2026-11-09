import configparser
import json
import os
import subprocess
import sys

from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")
if sys.stdin and hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# 读取 config.ini 中的 LLM 配置
cfg = configparser.ConfigParser()
cfg.read(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
    encoding="utf-8",
)
s = cfg["llm"]

client = OpenAI(base_url=s["base_url"], api_key=s["api_key"])

# 工具定义
tools = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断输入的年份是否为闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "要判断的年份，例如 2024",
                    }
                },
                "required": ["year"],
            },
        },
    },
]


def get_date():
    """调用本地 date 命令获取当前日期和时间（不使用 Python 的日期时间库）"""
    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; date",
        ]
    else:
        cmd = ["date"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or result.stderr).strip()
    return output or "无法获取日期和时间"


def is_leap_year(year):
    """用 Python 代码判断给定年份是否为闰年"""
    year = int(year)
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def run_tool(name, arguments):
    """执行模型请求的工具，返回给 LLM 的字符串结果"""
    if name == "getDate":
        return get_date()

    if name == "isLeapYear":
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = {}
        year = args.get("year")
        if year is None:
            return "缺少参数 year"
        leap = is_leap_year(year)
        return f"{year} 是闰年" if leap else f"{year} 不是闰年"

    return f"未知工具: {name}"


# 保存完整聊天记录，每一轮都发送给 LLM
messages = []

print("开始对话，直接输入内容按回车；按 Ctrl+C 退出。\n")

while True:
    try:
        user_input = input("你: ")
        messages.append({"role": "user", "content": user_input})

        # 内层循环：模型可能请求调用工具，处理完后再取最终回答
        while True:
            stream = client.chat.completions.create(
                model=s["model"],
                messages=messages,  # 发送全部历史记录
                tools=tools,
                stream=True,        # 打字机流式输出
            )

            print("AI: ", end="", flush=True)
            reply = ""
            tool_calls = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = delta.content or ""
                if piece:
                    print(piece, end="", flush=True)  # 边生成边打印
                    reply += piece

                # 收集流式返回的工具调用参数
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        index = tc.index or 0
                        while len(tool_calls) <= index:
                            tool_calls.append(
                                {"id": "", "name": "", "arguments": ""}
                            )
                        if tc.id:
                            tool_calls[index]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls[index]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls[index]["arguments"] += tc.function.arguments
            print()

            assistant_message = {"role": "assistant", "content": reply}
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_message)

            # 没有工具调用，说明已经得到最终回答
            if not tool_calls:
                break

            # 执行模型请求的工具，并把结果回传给 LLM
            for tc in tool_calls:
                result = run_tool(tc["name"], tc["arguments"])
                print(f"[工具] {tc['name']} -> {result}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )
        print()

    except KeyboardInterrupt:
        print("\n已退出对话。")
        break
    except Exception as e:
        print("\n出错:", e)
