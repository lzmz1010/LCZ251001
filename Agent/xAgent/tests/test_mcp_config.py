"""MCP 配置加载范围的单元测试（方案 B：默认仅当前目录 + 可配置的额外文件）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mcp.config import (
    McpConfigError,
    find_mcp_config,
    load_mcp_config,
    resolve_mcp_files,
)


class _ChdirTestCase(unittest.TestCase):
    """把工作目录临时切换到一个干净的临时目录。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        self.addCleanup(os.chdir, self._cwd)
        self._root = Path(self.tmpdir.name)

    def _write(self, name: str, servers: dict) -> Path:
        path = self._root / name
        path.write_text(
            json.dumps({"mcpServers": servers}, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


class FindMcpConfigTests(_ChdirTestCase):
    """find_mcp_config 只检查当前目录。"""

    def test_current_dir_file_is_found(self) -> None:
        self._write(".mcp.json", {"demo": {"url": "http://127.0.0.1:9000/"}})
        self.assertEqual(find_mcp_config(), self._root / ".mcp.json")

    def test_no_current_file_returns_none(self) -> None:
        self._root.joinpath(".mcp.json").touch()
        self._root.joinpath(".mcp.json").unlink()
        self.assertIsNone(find_mcp_config())

    def test_parent_dir_file_not_picked_default(self) -> None:
        # 在上级目录放置 .mcp.json：默认不应被读取（本方案核心断言）
        parent = self._root.parent
        parent_mcp = parent / ".mcp.json"
        backup = None
        if parent_mcp.exists():
            backup = parent_mcp.read_text(encoding="utf-8")
            parent_mcp.unlink()
        self.addCleanup(
            lambda: parent_mcp.write_text(backup or "{}", encoding="utf-8")
            if backup is not None
            else None
        )
        try:
            parent_mcp.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "peiHospital": {"url": "http://127.0.0.1:8080/"}
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertIsNone(find_mcp_config(), "不应读取上级目录的 .mcp.json")
            loaded = load_mcp_config()
            self.assertEqual(loaded.servers, (), "默认不应加载上级目录的服务器")
        finally:
            parent_mcp.unlink()
            if backup is not None:
                parent_mcp.write_text(backup, encoding="utf-8")


class LoadMcpConfigFilesTests(_ChdirTestCase):
    """load_mcp_config(files=...) 支持显式文件与同名覆盖。"""

    def test_explicit_files_are_loaded(self) -> None:
        path = self._write(
            "mcp1.json", {"demo": {"url": "http://127.0.0.1:9000/"}}
        )
        config = load_mcp_config(files=(str(path),))
        self.assertEqual(len(config.servers), 1)
        self.assertEqual(config.servers[0].name, "demo")
        self.assertEqual(config.servers[0].url, "http://127.0.0.1:9000/")

    def test_relative_path_resolved_against_cwd(self) -> None:
        self._write("mcp2.json", {"demo": {"url": "http://127.0.0.1:9002/"}})
        config = load_mcp_config(files=("mcp2.json",))
        self.assertEqual(len(config.servers), 1)
        self.assertEqual(config.servers[0].url, "http://127.0.0.1:9002/")

    def test_same_name_server_later_overrides(self) -> None:
        first = self._write(
            "a.json", {"demo": {"url": "http://127.0.0.1:1001/"}}
        )
        second = self._write(
            "b.json", {"demo": {"url": "http://127.0.0.1:1002/"}}
        )
        config = load_mcp_config(files=(str(first), str(second)))
        self.assertEqual(len(config.servers), 1)
        self.assertEqual(config.servers[0].url, "http://127.0.0.1:1002/")

    def test_missing_file_is_skipped(self) -> None:
        config = load_mcp_config(files=("no-such-file.json",))
        self.assertEqual(config.servers, ())

    def test_resolve_mcp_files_dedups(self) -> None:
        a = str(self._root / "a.json")
        resolved = resolve_mcp_files([a, a])
        self.assertEqual(len(resolved), 1)

    def test_explicit_path_with_missing_file_raises(self) -> None:
        with self.assertRaises(McpConfigError):
            load_mcp_config(path=str(self._root / "missing.json"))


class McpClientConfigFilesTests(unittest.TestCase):
    """config.ini 的 [mcp] files 解析。"""

    def test_ini_files_parsed(self) -> None:
        from core.config import load_config

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        ini = Path(tmpdir.name) / "config.ini"
        ini.write_text(
            "[llm]\nmodel = demo\n\n"
            "[mcp]\ndefault_timeout = 10\nconnect_timeout = 5\n"
            "files = D:/a/.mcp.json; D:/b/.mcp.json\n",
            encoding="utf-8",
        )
        config = load_config(str(ini))
        self.assertEqual(config.mcp.default_timeout, 10.0)
        self.assertEqual(config.mcp.connect_timeout, 5.0)
        self.assertEqual(
            config.mcp.files, ("D:/a/.mcp.json", "D:/b/.mcp.json")
        )


if __name__ == "__main__":
    unittest.main()