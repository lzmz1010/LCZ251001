# xAgent

基于 `Practice02/chat-stream-loop-history-tools.py` 重构而来的 LLM Agent 框架，
采用 **core（业务内核） + ui（表现层）** 的分层设计。

核心目标：

- 业务逻辑与界面彻底解耦，`core` 不依赖任何界面代码；
- 一套内核，多套前端：已实现 **TUI（Textual）** 与 **Console**，后续可直接扩展
  **Web / Desktop / Mobile**；
- 工具（函数调用）、模型适配器、会话管理均以抽象接口封装，便于替换与扩展。

---

## 一、目录结构

```
xAgent/
├── main.py                     # 统一入口（组合根）：解析参数 → 装载配置 → 装配 core → 启动前端
├── config.ini                  # 运行配置（模型地址、模型名、系统提示词等）
├── pyproject.toml              # 打包与依赖声明
├── requirements.txt
│
├── core/                       # ── 业务内核（与界面无关，可独立测试与复用）
│   ├── config.py               # 配置装载（ini + 环境变量 + 命令行覆盖）
│   ├── models.py               # 领域模型：Message / ToolCall
│   ├── events.py               # 对外事件（内核唯一的输出通道）
│   ├── session.py              # 会话上下文与历史记录
│   ├── agent.py                # Agent 主循环（用户输入 → 模型 → 工具 → 回传 → 最终回答）
│   ├── bootstrap.py            # 组合根：装配 LLM 客户端 + 工具 + 会话
│   ├── errors.py               # 统一异常
│   ├── llm/                    # 大模型适配层
│   │   ├── base.py             #   LLMClient 抽象接口
│   │   └── openai_client.py    #   OpenAI 兼容协议实现（LM Studio/Ollama/vLLM/DeepSeek…）
│   └── tools/                  # 工具子系统
│       ├── base.py             #   Tool / ToolSpec / ToolParameter 抽象
│       ├── registry.py         #   工具注册表（注册、校验、执行）
│       └── builtin/            #   内置工具（按业务域一个文件一个工具）
│           ├── datetime_tool.py
│           ├── calendar_tool.py
│           ├── search_tool.py  #   联网搜索（百度千帆百度搜索）
│           ├── fetch_tool.py   #   网页正文抓取（curl + trafilatura）
│           └── cli_tool.py     #   本地命令行执行（RunCli）
│
├── ui/                         # ── 表现层（可替换的前端）
│   ├── base.py                 # 前端契约 Frontend + 前端注册表
│   ├── console/                # 控制台前端（最简参考实现）
│   └── tui/                    # Textual 终端前端
│       ├── app.py              #   应用主体：事件 → 界面
│       ├── widgets.py          #   组件：消息气泡 / 工具气泡 / 输入区 / 状态栏
│       └── styles.tcss         #   样式
│
└── tests/                      # 单元测试 + TUI 冒烟测试（不依赖真实模型服务）
```

依赖方向严格单向：

```
        ┌──────────────┐
        │  ui (tui/…)  │  ← 只依赖 core 的公开接口与事件
        └──────┬───────┘
               │
        ┌──────▼───────┐
        │ core (agent) │  ← 不 import 任何 ui
        └──────┬───────┘
               │
        ┌──────▼──────────────────────────┐
        │ llm 适配器 / tools / session …    │
        └──────────────────────────────────┘
```

---

## 二、快速开始

```bash
cd D:/LLM/Agent/xAgent

# 1) 安装依赖
pip install -r requirements.txt
#    网页正文抓取需要本地 curl（Windows 10+ 自带）与 trafilatura

# 2) 配置模型服务（默认指向本地 LM Studio）
#    修改 config.ini 的 [llm] base_url / model / api_key
#    联网搜索在 [search] 中配置 baidu_qianfan_api_key（必填）与 edition

# 3) 启动 Textual 终端界面
python main.py

# 4) 或启动控制台界面
python main.py --ui console

# 5) 查看可用前端
python main.py --list-ui
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--ui/-u {tui,console}` | 选择前端，默认 `tui` |
| `--config/-c PATH` | 指定配置文件 |
| `--model/-m NAME` | 覆盖模型名 |
| `--base-url` / `--api-key` | 覆盖连接参数 |

TUI 快捷键：`Ctrl+Enter` 发送，`Ctrl+L` 清空对话，`Ctrl+Q` 退出。

环境变量亦可覆盖配置：`XAGENT_LLM_BASE_URL`、`XAGENT_LLM_API_KEY`、`XAGENT_LLM_MODEL`、
`XAGENT_SEARCH_API_KEY`、`XAGENT_SEARCH_BASE_URL`、`XAGENT_SEARCH_EDITION`。

### 联网搜索工具 `searchWeb`

Agent 通过 Function Calling 向模型暴露 `searchWeb` 工具。模型需要实时信息时调用它，
工具会请求百度千帆「百度搜索」接口（默认
`https://qianfan.baidubce.com/v2/ai_search/web_search`），将返回的网页摘要整理后，
连同参考来源的标题与 URL 一起回传给模型：

```
搜索摘要：
<网页内容摘要>

参考来源：
1. <网页标题>
   URL: <网页地址>
```

配置项（`config.ini` 的 `[search]` 段）：

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `baidu_qianfan_api_key` | 百度千帆 API Key（必填） | 空 |
| `edition` | 搜索版本：standard / turbo / pro | `standard` |
| `base_url` | 接口地址 | 千帆百度搜索地址 |
| `timeout` | 请求超时（秒） | `60` |

### 网页正文抓取工具 `fetchWeb`

当搜索结果只有摘要、需要阅读网页全文，或用户直接给出网页链接时，模型会调用 `fetchWeb`。
工具通过 `subprocess` 以参数列表方式调用本地 `curl`（不使用 `shell=True`）下载 HTML，
再用 `trafilatura` 提取正文并转换为 Markdown，保留标题、段落、列表、表格和链接，
去除导航栏、广告、页脚等无关内容，最终返回：

```
来源 URL: <原始网址>

<正文 Markdown>
```

仅支持 `http/https` 地址；网页访问失败、超时、curl 缺失、HTML 解析失败、正文无法提取
等情况都会以工具错误结果回传给模型。

### 本地命令行工具 `RunCli`

`RunCli` 用于执行本机已安装的命令行程序。模型需要传入程序名 `command` 和字符串参数
列表 `args`，工具通过 `subprocess.run([command, *args], shell=False)` 执行，避免拼接
Shell 字符串：

```json
{"name": "RunCli", "arguments": {"command": "python", "args": ["--version"]}}
```

执行结果会以“命令 / 退出码 / 标准输出 / 标准错误”的形式返回，模型可据此判断下一步操作。
默认超时 30 秒，单个输出流超过 20000 字符时会截断并标注原始长度；命令不存在、无权限、
超时等情况会以工具错误结果回传。

> 注意：按教学要求，本工具暂不实现命令白名单、黑名单或审批机制。命令以运行 Agent 的
> 当前用户权限执行，仅适用于受控教学实验环境，请勿在生产环境直接开放。

---

## 三、核心设计

### 3.1 事件流：内核与界面之间唯一的通道

`Agent.stream_turn()` 是一个异步生成器，输出 `core/events.py` 中定义的事件：

| 事件 | 含义 |
| --- | --- |
| `UserMessageEvent` | 用户输入已接收 |
| `TextDeltaEvent` | 模型输出的流式增量 |
| `MessageCompleteEvent` | 本轮模型消息生成完毕 |
| `ToolCallEvent` | 模型请求调用工具 |
| `ToolResultEvent` | 工具执行结果 |
| `StatusEvent` | 状态提示（正在执行工具…） |
| `ErrorEvent` | 错误 |
| `TurnCompleteEvent` | 本轮结束，前端恢复输入 |

事件对象均提供 `to_payload()`，可直接序列化为 JSON —— Web 端用它做 SSE / WebSocket 推送。

### 3.2 工具抽象

```python
class MyTool(Tool):
    name = "myTool"
    description = "工具说明"
    parameters = (ToolParameter(name="x", type="string", description="参数说明"),)

    def invoke(self, x: str) -> str:
        return f"收到 {x}"
```

注册后自动生成 OpenAI function calling schema：

```python
from core.tools.registry import ToolRegistry

registry = ToolRegistry([MyTool()])
registry.execute("myTool", '{"x": "hi"}')   # → ToolResult(content="收到 hi", is_error=False)
```

工具执行异常不会抛出，而是以 `is_error=True` 的结果回传给模型，保证对话不中断。

### 3.3 模型适配

`LLMClient` 是抽象接口，`OpenAIChatClient` 是其实现，负责把 OpenAI SDK 的流式分片
转换成内核自有的 `StreamChunk`。新增厂商只需再写一个适配器，`core/agent.py` 无需改动。

---

## 四、如何新增一个前端（Web / Desktop / Mobile）

只需三步，**不需要修改 `core` 中任何一行代码**。

1. 在 `ui/` 下新建目录（例如 `ui/web/`）；
2. 实现 `Frontend` 接口，消费事件流做渲染；
3. 在 `ui/base.py` 的注册表里登记。

```python
# ui/web/app.py
from core.agent import Agent
from core.events import TextDeltaEvent, ToolResultEvent
from ui.base import Frontend


class WebFrontend(Frontend):
    name = "web"

    def run(self, agent: Agent) -> None:
        # 例如：启动 FastAPI，把 agent.stream_turn() 的事件转成 SSE 推给浏览器
        async def stream():
            async for event in agent.stream_turn("你好"):
                yield event.to_payload()   # 已经是可 JSON 序列化的结构
        ...
```

```python
# ui/base.py 中登记
registry.register("web", lambda **kw: importlib.import_module("ui.web.app").WebFrontend(**kw))
```

随后 `python main.py --ui web` 即可启动。
Desktop / Mobile 端同理：只要能拿到 `Agent` 与事件流，就能复用全部业务能力。

---

## 五、如何新增一个工具

1. 在 `core/tools/builtin/` 下新建一个文件，实现 `Tool` 子类；
2. 在 `core/tools/builtin/__init__.py` 的 `build_default_registry()` 中注册；
3. 完成。模型会自动看到新的工具描述并按需调用。

内置工具包括日期时间、闰年判断、文件/目录操作、联网搜索 `searchWeb`、网页正文抓取 `fetchWeb`
和本地命令行执行 `RunCli`。`searchWeb` 使用标准库 `urllib` 发请求；`fetchWeb` 依赖本地
`curl` 与 `trafilatura`；`RunCli` 仅使用标准库 `subprocess`。

---

## 六、测试

```bash
cd D:/LLM/Agent/xAgent
python -m unittest discover -s tests -t .
```

- `tests/test_agent.py`：Agent 主循环、工具调用闭环、工具注册表、配置装载；
- `tests/test_tui.py`：Textual 前端冒烟测试（输入、流式渲染、工具气泡、清空对话）。

测试全部使用脚本化的假模型客户端，**不需要真实模型服务**。

---

## 七、与原脚本的对应关系

| 原 `chat-stream-loop-history-tools.py` | xAgent |
| --- | --- |
| `config.ini` 读取 | `core/config.py` |
| `client = OpenAI(...)` | `core/llm/openai_client.py`（异步 + 适配器） |
| `tools` 列表 | `core/tools/base.py` + `core/tools/registry.py` |
| `get_date` / `is_leap_year` | `core/tools/builtin/` 下两个工具类 |
| `run_tool` 分发 | `ToolRegistry.execute`（含参数校验与异常兜底） |
| `messages` 列表 | `core/session.py`（`Session`） |
| `while True` 主循环 | `core/agent.py`（`Agent.stream_turn`） |
| `print` 直接输出 | `core/events.py` 事件流 → 由各前端自行渲染 |
