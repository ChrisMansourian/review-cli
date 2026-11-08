import os
import subprocess
import tempfile
import unittest

from reviewer.mcp_server import handle_request, TOOLS


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class McpServerTests(unittest.TestCase):
    def test_initialize(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(resp["id"], 1)
        self.assertEqual(resp["result"]["serverInfo"]["name"], "reviewer-mcp-server")
        self.assertIn("tools", resp["result"]["capabilities"])

    def test_tools_list(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 4)
        self.assertEqual(tools, TOOLS)
        for tool in tools:
            self.assertIn("inputSchema", tool)

    def test_unknown_method(self):
        resp = handle_request({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)
        self.assertEqual(resp["id"], 3)

    def test_notification_returns_none(self):
        self.assertIsNone(
            handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_unknown_tool(self):
        resp = handle_request(
            {"id": 4, "method": "tools/call", "params": {"name": "bogus", "arguments": {}}}
        )
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("Unknown tool", resp["result"]["content"][0]["text"])

    def test_malformed_params(self):
        resp = handle_request({"id": 5, "method": "tools/call", "params": "oops"})
        self.assertTrue(resp["result"]["isError"])
        resp = handle_request({"id": 6, "method": "tools/call", "params": {}})
        self.assertTrue(resp["result"]["isError"])
        resp = handle_request({"id": 7, "method": "tools/call", "params": {"name": ["x"]}})
        self.assertTrue(resp["result"]["isError"])
        resp = handle_request({"id": 8, "method": "tools/list", "params": [1]})
        self.assertEqual(len(resp["result"]["tools"]), 4)
        self.assertIsNone(handle_request([1, 2]))

    def _make_repo(self, tmp):
        _git(tmp, "init")
        _git(tmp, "config", "user.name", "Test")
        _git(tmp, "config", "user.email", "t@example.com")
        path = os.path.join(tmp, "a.py")
        with open(path, "w") as f:
            f.write("x = 1\n")
        _git(tmp, "add", ".")
        _git(tmp, "commit", "-m", "feat: add a")
        with open(path, "w") as f:
            f.write("x = 1\ny = 2\n")

    def test_review_diff_on_temp_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            resp = handle_request(
                {"id": 10, "method": "tools/call",
                 "params": {"name": "review_diff", "arguments": {"repo_path": tmp}}}
            )
        content = resp["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("isError", resp["result"])

    def test_missing_arguments_defaults(self):
        resp = handle_request(
            {"id": 11, "method": "tools/call", "params": {"name": "bogus"}}
        )
        self.assertTrue(resp["result"]["isError"])

    def test_non_dict_arguments_coerced(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            old = os.getcwd()
            os.chdir(tmp)
            try:
                resp = handle_request(
                    {"id": 12, "method": "tools/call",
                     "params": {"name": "check_style_guide", "arguments": "bad"}}
                )
            finally:
                os.chdir(old)
        self.assertEqual(resp["id"], 12)
        self.assertIn("content", resp["result"])


if __name__ == "__main__":
    unittest.main()
