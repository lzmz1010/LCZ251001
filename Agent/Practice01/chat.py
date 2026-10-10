import configparser
import os
import sys

from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")

# 读取 config.ini 中的 LLM 配置
cfg = configparser.ConfigParser()
cfg.read(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
    encoding="utf-8",
)
s = cfg["llm"]

client = OpenAI(base_url=s["base_url"], api_key=s["api_key"])

# 保存完整聊天记录，每一轮都发送给 LLM
messages = []

print("开始对话，直接输入内容按回车；按 Ctrl+C 退出。\n")

while True:
    try:
        user_input = input("你: ")
        messages.append({"role": "user", "content": user_input})

        stream = client.chat.completions.create(
            model=s["model"],
            messages=messages,  # 发送全部历史记录
            stream=True,        # 打字机流式输出
        )

        print("AI: ", end="", flush=True)
        reply = ""
        for chunk in stream:
            if not chunk.choices:
                continue
            piece = chunk.choices[0].delta.content or ""
            print(piece, end="", flush=True)  # 边生成边打印
            reply += piece
        print("\n")
        messages.append({"role": "assistant", "content": reply})

    except KeyboardInterrupt:
        print("\n已退出对话。")
        break
    except Exception as e:
        print("\n出错:", e)
