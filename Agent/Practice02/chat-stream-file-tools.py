import configparser
import json
import mimetypes
import os
import shutil
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
    {
        "type": "function",
        "function": {
            "name": "getWorkingDirectory",
            "description": "获取当前的工作目录",
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
            "name": "listDirectory",
            "description": "列出指定目录下所有的文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要列出内容的目录路径，例如 D:/LLM/Agent",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的文件类型（扩展名、MIME 类型、纯文本或二进制）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件的完整路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readTextFile",
            "description": "读取指定纯文本文件的内容，二进制文件不可读取",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要读取的文本文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "根据指定的目录和文件名创建新文件，可选写入初始内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "新文件所在的目录路径，不存在时会自动创建",
                    },
                    "filename": {
                        "type": "string",
                        "description": "文件名，例如 note.txt",
                    },
                    "content": {
                        "type": "string",
                        "description": "文件的初始内容，可不填",
                    },
                },
                "required": ["directory", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editTextFile",
            "description": "编辑指定纯文本文件的内容，支持追加、替换、覆盖三种方式",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文本文件路径"},
                    "mode": {
                        "type": "string",
                        "enum": ["append", "replace", "overwrite"],
                        "description": (
                            "编辑方式：append=在文件末尾追加 content；"
                            "replace=把 old_text 替换为 new_text；"
                            "overwrite=用 content 覆盖整个文件"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "append 或 overwrite 模式下写入的内容",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "replace 模式下要被替换的原文本",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "replace 模式下替换成的新文本",
                    },
                },
                "required": ["path", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDirectory",
            "description": "创建新目录（包括多级父目录）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要创建的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDirectory",
            "description": "删除指定的目录及其下的所有内容（支持非空目录）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"}
                },
                "required": ["path"],
            },
        },
    },
]

# 常见扩展名的中文说明
EXT_DESC = {
    ".py": "Python 源文件",
    ".txt": "纯文本文件",
    ".md": "Markdown 文档",
    ".json": "JSON 数据文件",
    ".ini": "配置文件",
    ".csv": "CSV 表格文件",
    ".html": "HTML 网页文件",
    ".css": "CSS 样式文件",
    ".js": "JavaScript 源文件",
    ".ts": "TypeScript 源文件",
    ".c": "C 源文件",
    ".cpp": "C++ 源文件",
    ".h": "C/C++ 头文件",
    ".java": "Java 源文件",
    ".doc": "Word 文档",
    ".docx": "Word 文档",
    ".xls": "Excel 表格",
    ".xlsx": "Excel 表格",
    ".pdf": "PDF 文档",
    ".png": "PNG 图片",
    ".jpg": "JPEG 图片",
    ".jpeg": "JPEG 图片",
    ".gif": "GIF 图片",
    ".zip": "ZIP 压缩包",
    ".exe": "可执行文件",
    ".dll": "动态链接库",
}

MAX_READ_CHARS = 20000  # 单次读取文本的最大返回长度


def resolve(path):
    """把用户传入的路径统一转换为绝对路径"""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))


def is_text_bytes(sample):
    """根据文件开头的一段字节判断是否为纯文本"""
    if b"\x00" in sample:
        return False
    for encoding in ("utf-8", "gbk"):
        try:
            sample.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def read_text(path):
    """读取纯文本文件内容，自动尝试 utf-8 和 gbk 编码"""
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别的文件编码（仅支持纯文本文件）")


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


def get_working_directory():
    """用 Python 获取当前工作目录"""
    return os.getcwd()


def list_directory(path):
    """列出目录下的所有文件和子目录，子目录在前"""
    path = resolve(path)
    if not os.path.isdir(path):
        return f"目录不存在: {path}"
    entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
    if not entries:
        return f"目录为空: {path}"
    lines = [f"当前目录: {path}"]
    for entry in entries:
        if entry.is_dir():
            lines.append(f"[目录] {entry.name}")
        else:
            lines.append(f"[文件] {entry.name} ({entry.stat().st_size} 字节)")
    return "\n".join(lines)


def get_file_type(path):
    """获取文件的扩展名、MIME 类型，并判断是纯文本还是二进制"""
    path = resolve(path)
    if not os.path.isfile(path):
        return f"文件不存在: {path}"
    ext = os.path.splitext(path)[1].lower()
    desc = EXT_DESC.get(ext, "未知类型" if ext else "无扩展名")
    mime, _ = mimetypes.guess_type(path)
    with open(path, "rb") as f:
        sample = f.read(8192)
    kind = "纯文本" if is_text_bytes(sample) else "二进制"
    return (
        f"文件: {path}\n"
        f"扩展名: {ext or '(无)'} ({desc})\n"
        f"MIME 类型: {mime or '未知'}\n"
        f"内容类型: {kind}"
    )


def read_text_file(path):
    """读取纯文本文件的内容，二进制文件直接拒绝"""
    path = resolve(path)
    if not os.path.isfile(path):
        return f"文件不存在: {path}"
    if os.path.getsize(path) == 0:
        return "(空文件)"
    with open(path, "rb") as f:
        sample = f.read(8192)
    if not is_text_bytes(sample):
        return f"该文件不是纯文本文件，无法读取: {path}"
    content = read_text(path)
    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS] + f"\n...(内容过长，已截断，共 {len(content)} 字符)"
    return content


def create_file(directory, filename, content=""):
    """在指定目录下创建新文件，目录不存在时自动创建"""
    directory = resolve(directory)
    full_path = os.path.join(directory, str(filename))
    if os.path.exists(full_path):
        return f"文件已存在，未创建: {full_path}"
    os.makedirs(directory, exist_ok=True)
    with open(full_path, "w", encoding="utf-8", newline="") as f:
        f.write(content or "")
    return f"创建成功: {full_path} ({os.path.getsize(full_path)} 字节)"


def edit_text_file(path, mode, content="", old_text="", new_text=""):
    """编辑纯文本文件，支持 append / replace / overwrite 三种模式"""
    path = resolve(path)
    if not os.path.isfile(path):
        return f"文件不存在: {path}"
    with open(path, "rb") as f:
        sample = f.read(8192)
    if not is_text_bytes(sample):
        return f"该文件不是纯文本文件，无法编辑: {path}"

    if mode == "append":
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(content or "")
        return f"已追加内容: {path} (当前 {os.path.getsize(path)} 字节)"

    if mode == "overwrite":
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content or "")
        return f"已覆盖内容: {path} (当前 {os.path.getsize(path)} 字节)"

    if mode == "replace":
        if not old_text:
            return "replace 模式必须提供参数 old_text"
        text = read_text(path)
        count = text.count(old_text)
        if count == 0:
            return f"未在文件中找到 old_text: {path}"
        text = text.replace(old_text, new_text or "")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return f"已替换 {count} 处内容: {path} (当前 {os.path.getsize(path)} 字节)"

    return f"不支持的编辑方式: {mode}（可选 append / replace / overwrite）"


def create_directory(path):
    """创建新目录（多级目录一并创建）"""
    path = resolve(path)
    if os.path.isdir(path):
        return f"目录已存在: {path}"
    os.makedirs(path, exist_ok=True)
    return f"目录创建成功: {path}"


def delete_directory(path):
    """删除目录及其全部内容，支持非空目录"""
    path = resolve(path)
    if not os.path.isdir(path):
        return f"目录不存在: {path}"
    if os.path.ismount(path) or os.path.dirname(path) == path:
        return f"出于安全考虑，拒绝删除磁盘根目录: {path}"
    shutil.rmtree(path)
    return f"目录已删除（含全部内容）: {path}"


def delete_file(path):
    """删除指定的文件"""
    path = resolve(path)
    if not os.path.isfile(path):
        return f"文件不存在: {path}"
    os.remove(path)
    return f"文件已删除: {path}"


def run_tool(name, arguments):
    """执行模型请求的工具，返回给 LLM 的字符串结果"""
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return f"工具参数不是合法的 JSON: {arguments}"

    try:
        if name == "getDate":
            return get_date()

        if name == "isLeapYear":
            year = args.get("year")
            if year is None:
                return "缺少参数 year"
            leap = is_leap_year(year)
            return f"{year} 是闰年" if leap else f"{year} 不是闰年"

        if name == "getWorkingDirectory":
            return get_working_directory()

        if name == "listDirectory":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return list_directory(path)

        if name == "getFileType":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return get_file_type(path)

        if name == "readTextFile":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return read_text_file(path)

        if name == "createFile":
            directory = args.get("directory")
            filename = args.get("filename")
            if not directory or not filename:
                return "缺少参数 directory 或 filename"
            return create_file(directory, filename, args.get("content", ""))

        if name == "editTextFile":
            path = args.get("path")
            mode = args.get("mode")
            if not path or not mode:
                return "缺少参数 path 或 mode"
            return edit_text_file(
                path,
                mode,
                content=args.get("content", ""),
                old_text=args.get("old_text", ""),
                new_text=args.get("new_text", ""),
            )

        if name == "createDirectory":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return create_directory(path)

        if name == "deleteDirectory":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return delete_directory(path)

        if name == "deleteFile":
            path = args.get("path")
            if not path:
                return "缺少参数 path"
            return delete_file(path)

        return f"未知工具: {name}"
    except Exception as e:
        return f"工具执行出错: {e}"


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
