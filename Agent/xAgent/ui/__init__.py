"""界面层（ui）。

本包只负责“如何呈现”，不包含任何业务逻辑：

- ``base``    前端统一契约（``Frontend``）与前端注册表
- ``tui``     Textual 终端界面
- ``console`` 纯控制台界面（最简参考实现）
- 未来可新增 ``web`` / ``desktop`` / ``mobile`` 等目录

前端之间互不依赖，均通过 ``core`` 暴露的 ``Agent`` 与事件流协作。
"""

from ui.base import Frontend, FrontendRegistry, create_frontend, registry

__all__ = ["Frontend", "FrontendRegistry", "create_frontend", "registry"]
