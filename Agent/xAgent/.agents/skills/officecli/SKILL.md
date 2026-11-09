---
name: officecli
description: 调用本地 officecli-win-x64.exe（OfficeCLI 单文件命令行工具）读取、创建和修改 Word(.docx)、Excel(.xlsx)、PowerPoint(.pptx) 文档
version: 1.0.0
---


# officecli 本地文档操作技能

本技能目标是让 Agent 通过 RunCli 调用本地命令行工具 officecli-win-x64.exe，实现读取、创建、修改 Word、Excel、PowerPoint 文档。OfficeCLI 是 AI-friendly 的 .docx/.xlsx/.pptx 单二进制 CLI，无需安装 Office。

## 可执行文件位置

- 绝对路径: D:\office\.agents\skills\OfficeCli_#SULP#_26sc1d\officecli-win-x64.exe
- 在 Windows 终端也可直接用 officecli-win-x64.exe 启动。

## 使用方式

通过 RunCli 工具调用，command 为 exe 绝对路径，args 为该命令参数列表，示例：
{name: RunCli, arguments: {command: D:\\office\\.agents\\skills\\OfficeCli_#SULP#_26sc1d\\officecli-win-x64.exe, args: [help]}}
注意：cmd 中不要带 .exe 后缀时需谨慎，最稳妥用完整 exe 路径作为 command。

## 策略分层 L1 -> L2 -> L3

优先使用更高层：L1(read) -> L2(DOM edit) -> L3(raw XML)。需要结构化输出加 --json。
对属性名、取值、命令语法不确定时，先运行 help 而不是猜测。

help 用法：
- cmd help           或 cmd --help
- cmd help docx
- cmd help docx paragraph
- cmd help docx set paragraph
- cmd help docx paragraph --json

格式别名：word->docx, excel->xlsx, ppt/powerpoint->pptx；动词 add/set/get/query/remove。

## 快速示例

PPT:
- cmd create slides.pptx
- cmd add slides.pptx / --type slide --prop title="Q4 Report" --prop background=1A1A2E
- cmd add slides.pptx "/slide[1]" --type shape --prop text="Revenue grew 25%" --prop x=2cm --prop y=5cm --prop font=Arial --prop size=24 --prop color=FFFFFF

Word:
- cmd create report.docx
- cmd add report.docx /body --type paragraph --prop text="Executive Summary" --prop style=Heading1
- cmd add report.docx /body --type paragraph --prop text="Revenue increased by 25% year-over-year."

Excel:
- cmd create data.xlsx
- cmd set data.xlsx /Sheet1/A1 --prop value="Name" --prop bold=true
- cmd set data.xlsx /Sheet1/A2 --prop value="Alice"

## L1 创建/读取/检查

- cmd create <file>          创建空白文档（按扩展名识别类型）
- cmd view <file> <mode>     outline|stats|issues|text|annotated|html
- cmd get <file> <path> --depth N  读取节点及其子节点 [--json]
- cmd query <file> <selector>  CSS 式查询
- cmd validate <file>          OpenXML 校验

## L2 DOM 编辑

- cmd set <file> <path> --prop key=value [--prop ...]  修改属性/值
- cmd add <file> <parent> --type <type> [--prop ...]   新增元素
- cmd add <file> <parent> --type <type> --after <path>  在锚点后插入
- cmd move / swap / remove 元素
- cmd batch <file> --commands '[{...}]' --json 批量
- find/replace: cmd set doc.docx / --find draft --replace final

颜色 FF0000/#FF0000/red/rgb(255,0,0)/accent1..accent6；间距 12pt/0.5cm/1.5x/150%；尺寸 914400/2.54cm/1in/72pt/96px。

## 注意

- 路径 1-based（XPath）：docx "/body/p[2]"；--index 0-based。
- 文件打开改前需在 Word/PowerPoint/WPS 中先关闭。
- 属性名不确定时先运行 help，不要猜测。
- 修改后用 validate 或 view issues 验证。

## 禁止

- 不要用相对路径运行脚本前先确认 exe 存在。