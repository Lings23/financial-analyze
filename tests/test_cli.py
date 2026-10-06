import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stock_research.__main__ import _project_tushare_token, main
from stock_research.errors import ValidationError


class CLITests(unittest.TestCase):
    def test_demo_is_offline_and_identifies_synthetic_data(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["demo"]), 0)
        self.assertIn("SYNTHETIC ONLY", output.getvalue())
        self.assertIn("no_visible_data", output.getvalue())

    def test_missing_dsn_is_actionable_without_traceback(self):
        output = io.StringIO()
        with patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(output):
            self.assertEqual(main(["migrate"]), 2)
        self.assertIn("STOCK_RESEARCH_DSN is required", output.getvalue())

    def test_project_tushare_token_and_explicit_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("TUSHARE_TOKEN=project-secret\n", encoding="utf-8")
            with patch("stock_research.__main__.Path", return_value=env_file):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(_project_tushare_token(), "project-secret")
                with patch.dict("os.environ", {"TUSHARE_TOKEN": "process-secret"}, clear=True):
                    self.assertEqual(_project_tushare_token(), "process-secret")

    def test_duplicate_project_tushare_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("TUSHARE_TOKEN=one\nTUSHARE_TOKEN=two\n", encoding="utf-8")
            with patch("stock_research.__main__.Path", return_value=env_file):
                with patch.dict("os.environ", {}, clear=True):
                    with self.assertRaises(ValidationError):
                        _project_tushare_token()
