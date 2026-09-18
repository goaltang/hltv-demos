import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import AsyncMock, patch

from hltv_demos import cli


class CliTests(unittest.TestCase):
    def test_missing_event_is_usage_error(self):
        with redirect_stderr(io.StringIO()), self.assertRaisesRegex(SystemExit, "2"):
            cli.main([])

    @patch.object(cli, "run", new_callable=AsyncMock)
    def test_real_run_requires_yes_before_calling_core(self, run):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["--event", "event"])
        self.assertEqual(code, 1)
        self.assertIn("--yes", out.getvalue())
        run.assert_not_awaited()

    @patch.object(cli, "run", new_callable=AsyncMock)
    def test_json_is_clean_and_partial_failure_exits_one(self, run):
        async def fake(**kwargs):
            kwargs["progress"]("working")
            return {"event": "1/e", "errors": [{"teams": "A", "error": "boom"}]}
        run.side_effect = fake
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--event", "event", "--yes", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["errors"][0]["error"], "boom")
        self.assertIn("working", err.getvalue())

    @patch.object(cli, "doctor")
    def test_doctor_exit_reflects_readiness(self, doctor):
        doctor.return_value = {"ok": False, "platform": {"ok": False, "value": "windows/amd64"}}
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--doctor"]), 1)


if __name__ == "__main__":
    unittest.main()
