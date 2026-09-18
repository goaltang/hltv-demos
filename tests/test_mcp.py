import unittest
from unittest.mock import patch

import hltv_demos.mcp_server as server


def prepared_plan():
    return {
        "event": "1/event", "event_url": "https://www.hltv.org/events/1/event",
        "wanted": ["Inferno"], "keep_rars": True,
        "csgo_config": "", "download_config": "",
        "plan": [{
            "teams": "A vs B", "score": "2-0", "played": ["Inferno"],
            "hit": ["Inferno"], "name": "demo.rar", "size": 10,
            "demo_id": "7", "r2": "https://r2-demos.hltv.org/demo.rar",
        }],
    }


class McpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._PLANS.clear()

    @patch.object(server, "_execute_download_plan")
    @patch.object(server, "discover_csgo", return_value="/csgo")
    @patch.object(server, "doctor", return_value={"ok": True})
    @patch.object(server, "_build_download_plan", side_effect=lambda *args: prepared_plan())
    async def test_plan_then_approved_execution_is_frozen_and_single_use(
            self, _build, _doctor, _discover, execute):
        execute.return_value = {"event": "1/event", "errors": [], "extracted": []}
        planned = await server.plan_download(event="event", maps="Inferno", latest=1)
        self.assertTrue(planned["ready"])
        token = planned["approval_token"]

        executed = await server.execute_approved_plan(token)
        self.assertTrue(executed["ok"])
        self.assertFalse((await server.execute_approved_plan(token))["ok"])
        frozen = execute.call_args.args[0]
        self.assertEqual(frozen["plan"][0]["demo_id"], "7")
        self.assertEqual(frozen["resolved_csgo"], "/csgo")
        execute.assert_called_once()

    async def test_unbounded_or_invalid_request_never_gets_token(self):
        result = await server.plan_download(event="event", maps="", latest=0)
        self.assertFalse(result["ready"])
        self.assertNotIn("approval_token", result)
        result = await server.plan_download(event="event", maps="Inferno", latest=101)
        self.assertFalse(result["ready"])

    @patch.object(server, "doctor", return_value={"ok": False})
    async def test_failed_doctor_never_gets_token(self, _doctor):
        result = await server.plan_download(event="event", maps="Inferno", latest=1)
        self.assertFalse(result["ready"])
        self.assertNotIn("approval_token", result)

    async def test_invalid_token_does_not_execute(self):
        result = await server.execute_approved_plan("wrong")
        self.assertFalse(result["ok"])


class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_lists_three_tools_without_stdout_noise(self):
        import sys
        from pathlib import Path

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        command = str(Path(sys.executable))
        params = StdioServerParameters(command=command, args=["-m", "hltv_demos.mcp_server"])
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
        self.assertEqual(
            {tool.name for tool in tools.tools},
            {"check_environment", "plan_download", "execute_approved_plan"},
        )


if __name__ == "__main__":
    unittest.main()
