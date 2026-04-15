#!/usr/bin/env python3
"""Unit tests for Agent Relay (relay-msg)."""

import importlib
import importlib.util
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch, MagicMock, call

# Load relay-msg as a module (it has no .py extension).
_relay_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay-msg")
loader = importlib.machinery.SourceFileLoader("relay_msg", _relay_path)
spec = importlib.util.spec_from_loader("relay_msg", loader, origin=_relay_path)
relay = importlib.util.module_from_spec(spec)

relay.__file__ = _relay_path

# Prevent _load_env_file from running during import — we control env in tests.
with patch.dict(os.environ, {"RELAY_IDENTITY": "test-agent", "RELAY_DB_NAME": "test_db"}):
    spec.loader.exec_module(relay)

# Register in sys.modules so patch("relay_msg.X") works.
sys.modules["relay_msg"] = relay


def _mock_subprocess(stdout="", returncode=0, stderr=""):
    """Create a mock subprocess.run result."""
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = returncode
    return mock


class TestEsc(unittest.TestCase):
    """Test SQL escaping."""

    def test_escapes_single_quotes(self):
        self.assertEqual(relay._esc("it's"), "it\\'s")

    def test_escapes_backslashes(self):
        self.assertEqual(relay._esc("a\\b"), "a\\\\b")

    def test_no_change_for_safe_strings(self):
        self.assertEqual(relay._esc("hello world"), "hello world")

    def test_empty_string(self):
        self.assertEqual(relay._esc(""), "")

    def test_both_quotes_and_backslashes(self):
        self.assertEqual(relay._esc("it's a\\path"), "it\\'s a\\\\path")


class TestDetectSelf(unittest.TestCase):
    """Test agent identity detection."""

    def test_env_var_wins(self):
        with patch.dict(os.environ, {"RELAY_IDENTITY": "alice"}):
            self.assertEqual(relay.detect_self(), "alice")

    def test_cwd_pattern_match(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove RELAY_IDENTITY to test CWD fallback.
            env = os.environ.copy()
            env.pop("RELAY_IDENTITY", None)
            with patch.dict(os.environ, env, clear=True):
                with patch("relay_msg.run_sql_raw", return_value=["bob\tmy-project-bob"]):
                    with patch("os.getcwd", return_value="/home/user/my-project-bob"):
                        self.assertEqual(relay.detect_self(), "bob")

    def test_cwd_no_match_falls_back_to_default(self):
        env = os.environ.copy()
        env.pop("RELAY_IDENTITY", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("relay_msg.run_sql_raw", return_value=["bob\tmy-project-bob"]):
                with patch("os.getcwd", return_value="/some/other/path"):
                    self.assertEqual(relay.detect_self(), "default")

    def test_db_failure_falls_back_to_default(self):
        env = os.environ.copy()
        env.pop("RELAY_IDENTITY", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("relay_msg.run_sql_raw", side_effect=SystemExit(2)):
                self.assertEqual(relay.detect_self(), "default")


class TestGetTransport(unittest.TestCase):
    """Test transport detection."""

    def test_returns_transport_from_db(self):
        with patch("relay_msg.detect_self", return_value="alice"):
            with patch("relay_msg.run_sql_raw", return_value=["remote"]):
                self.assertEqual(relay._get_transport(), "remote")

    def test_defaults_to_local_when_not_registered(self):
        with patch("relay_msg.detect_self", return_value="unknown"):
            with patch("relay_msg.run_sql_raw", return_value=[]):
                self.assertEqual(relay._get_transport(), "local")

    def test_defaults_to_local_on_db_error(self):
        with patch("relay_msg.detect_self", return_value="alice"):
            with patch("relay_msg.run_sql_raw", side_effect=Exception("connection refused")):
                self.assertEqual(relay._get_transport(), "local")


class TestRunSqlRaw(unittest.TestCase):
    """Test raw SQL execution."""

    def test_local_transport_calls_mysql_directly(self):
        with patch.dict(os.environ, {"RELAY_TRANSPORT": "local"}):
            with patch("subprocess.run", return_value=_mock_subprocess("row1\nrow2")) as mock_run:
                result = relay.run_sql_raw("SELECT 1", fetch=True)
                self.assertEqual(result, ["row1", "row2"])
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                self.assertEqual(args[0], "mysql")

    def test_local_transport_returns_empty_on_failure(self):
        with patch.dict(os.environ, {"RELAY_TRANSPORT": "local"}):
            with patch("subprocess.run", return_value=_mock_subprocess(returncode=1)):
                result = relay.run_sql_raw("BAD SQL", fetch=True)
                self.assertEqual(result, [])

    def test_remote_transport_uses_proxy(self):
        with patch.dict(os.environ, {"RELAY_TRANSPORT": "remote", "RELAY_PROXY_CMD": "my-proxy"}):
            with patch("subprocess.run", return_value=_mock_subprocess("row1")) as mock_run:
                result = relay.run_sql_raw("SELECT 1", fetch=True)
                self.assertEqual(result, ["row1"])
                mock_run.assert_called_once()
                # Should use shell=True for proxy commands.
                self.assertTrue(mock_run.call_args[1].get("shell"))

    def test_remote_transport_no_proxy_returns_empty(self):
        env = os.environ.copy()
        env["RELAY_TRANSPORT"] = "remote"
        env.pop("RELAY_PROXY_CMD", None)
        with patch.dict(os.environ, env, clear=True):
            with patch("relay_msg._get_proxy_cmd", return_value=None):
                result = relay.run_sql_raw("SELECT 1", fetch=True)
                self.assertEqual(result, [])


class TestRunSql(unittest.TestCase):
    """Test SQL execution with transport routing."""

    def test_local_calls_mysql(self):
        with patch("relay_msg._get_transport", return_value="local"):
            with patch("subprocess.run", return_value=_mock_subprocess("ok")) as mock_run:
                result = relay.run_sql("SELECT 1", fetch=True)
                self.assertEqual(result, ["ok"])

    def test_remote_calls_proxy(self):
        with patch("relay_msg._get_transport", return_value="remote"):
            with patch("relay_msg._get_proxy_cmd", return_value="my-proxy"):
                with patch("subprocess.run", return_value=_mock_subprocess("ok")) as mock_run:
                    result = relay.run_sql("SELECT 1", fetch=True)
                    self.assertEqual(result, ["ok"])
                    self.assertTrue(mock_run.call_args[1].get("shell"))

    def test_remote_no_proxy_exits(self):
        with patch("relay_msg._get_transport", return_value="remote"):
            with patch("relay_msg._get_proxy_cmd", return_value=None):
                with self.assertRaises(SystemExit) as ctx:
                    relay.run_sql("SELECT 1")
                self.assertEqual(ctx.exception.code, 2)

    def test_local_mysql_error_exits(self):
        with patch("relay_msg._get_transport", return_value="local"):
            with patch("subprocess.run", return_value=_mock_subprocess(returncode=1, stderr="access denied")):
                with self.assertRaises(SystemExit) as ctx:
                    relay.run_sql("SELECT 1")
                self.assertEqual(ctx.exception.code, 2)


class TestCmdSend(unittest.TestCase):
    """Test sending messages."""

    def test_send_to_agent(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice", "bob"]):
                    with patch("relay_msg._get_all_groups", return_value=[]):
                        with patch("relay_msg._resolve_alias", return_value="bob"):
                            with patch("relay_msg.run_sql") as mock_sql:
                                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                                    relay.cmd_send("bob", "hello")
                                    sql = mock_sql.call_args[0][0]
                                    self.assertIn("bob", sql)
                                    self.assertIn("hello", sql)
                                    self.assertIn("alice", sql)  # sender
                                    self.assertIn("Message sent to bob", mock_out.getvalue())

    def test_send_to_group(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice", "bob", "carol"]):
                    with patch("relay_msg._get_all_groups", return_value=["backend"]):
                        with patch("relay_msg._get_group_members", return_value=["alice", "bob", "carol"]):
                            with patch("relay_msg.run_sql") as mock_sql:
                                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                                    relay.cmd_send("backend", "deploy done")
                                    sql = mock_sql.call_args[0][0]
                                    # Should send to bob and carol, not alice (sender).
                                    self.assertIn("bob", sql)
                                    self.assertIn("carol", sql)
                                    self.assertIn("[broadcast:backend]", sql)
                                    output = mock_out.getvalue()
                                    self.assertIn("Broadcast (backend)", output)

    def test_send_to_all(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice", "bob", "carol"]):
                    with patch("relay_msg._get_all_groups", return_value=[]):
                        with patch("relay_msg.run_sql") as mock_sql:
                            with patch("sys.stdout", new_callable=StringIO):
                                relay.cmd_send("all", "maintenance")
                                sql = mock_sql.call_args[0][0]
                                self.assertIn("bob", sql)
                                self.assertIn("carol", sql)
                                # alice appears as sender but NOT as a target (recipient).
                                # Targets are the first field in each tuple.
                                values_part = sql.split("VALUES")[1]
                                self.assertNotIn("('alice'", values_part)  # sender excluded from recipients

    def test_send_all_no_peers_exits(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice"]):
                    with patch("relay_msg._get_all_groups", return_value=[]):
                        with self.assertRaises(SystemExit):
                            relay.cmd_send("all", "hello?")

    def test_send_to_alias(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice", "bob"]):
                    with patch("relay_msg._get_all_groups", return_value=[]):
                        with patch("relay_msg._resolve_alias", return_value="bob"):
                            with patch("relay_msg.run_sql") as mock_sql:
                                with patch("sys.stdout", new_callable=StringIO):
                                    relay.cmd_send("robert", "hey")
                                    sql = mock_sql.call_args[0][0]
                                    self.assertIn("bob", sql)

    def test_send_to_unknown_still_delivers(self):
        """Sending to an unknown target resolves via alias and delivers anyway."""
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="alice"):
                with patch("relay_msg._get_all_agents", return_value=["alice"]):
                    with patch("relay_msg._get_all_groups", return_value=[]):
                        with patch("relay_msg._resolve_alias", return_value="unknown"):
                            with patch("relay_msg.run_sql") as mock_sql:
                                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                                    relay.cmd_send("unknown", "hello")
                                    sql = mock_sql.call_args[0][0]
                                    self.assertIn("unknown", sql)
                                    self.assertIn("Message sent to unknown", mock_out.getvalue())


class TestCmdCheck(unittest.TestCase):
    """Test checking messages."""

    def test_check_prints_unread(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="bob"):
                with patch("relay_msg._get_aliases", return_value=[]):
                    with patch("relay_msg.run_sql") as mock_sql:
                        mock_sql.side_effect = [
                            # First call: SELECT messages.
                            ["1\talice\t2026-04-14 12:00:00\thello bob\tNULL"],
                            # Second call: UPDATE read_at.
                            [],
                        ]
                        with patch("sys.stdout", new_callable=StringIO) as mock_out:
                            relay.cmd_check()
                            output = mock_out.getvalue()
                            self.assertIn("[alice]", output)
                            self.assertIn("hello bob", output)
                            # Should have called UPDATE to mark as read.
                            self.assertEqual(mock_sql.call_count, 2)

    def test_check_peek_does_not_mark_read(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="bob"):
                with patch("relay_msg._get_aliases", return_value=[]):
                    with patch("relay_msg.run_sql") as mock_sql:
                        mock_sql.return_value = ["1\talice\t2026-04-14 12:00:00\thello\tNULL"]
                        with patch("sys.stdout", new_callable=StringIO):
                            relay.cmd_check(peek=True)
                            # Only the SELECT, no UPDATE.
                            self.assertEqual(mock_sql.call_count, 1)

    def test_check_no_messages_silent(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="bob"):
                with patch("relay_msg._get_aliases", return_value=[]):
                    with patch("relay_msg.run_sql", return_value=[]):
                        with patch("sys.stdout", new_callable=StringIO) as mock_out:
                            relay.cmd_check()
                            self.assertEqual(mock_out.getvalue(), "")

    def test_check_history_shows_read_messages(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="bob"):
                with patch("relay_msg._get_aliases", return_value=[]):
                    with patch("relay_msg.run_sql") as mock_sql:
                        mock_sql.return_value = [
                            "1\talice\t2026-04-14 12:00:00\told msg\t2026-04-14 12:01:00"
                        ]
                        with patch("sys.stdout", new_callable=StringIO) as mock_out:
                            relay.cmd_check(history=True)
                            output = mock_out.getvalue()
                            self.assertIn("[read]", output)
                            self.assertIn("old msg", output)

    def test_check_includes_aliases(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.detect_self", return_value="bob"):
                with patch("relay_msg._get_aliases", return_value=["robert"]):
                    with patch("relay_msg.run_sql") as mock_sql:
                        mock_sql.return_value = []
                        relay.cmd_check()
                        sql = mock_sql.call_args[0][0]
                        self.assertIn("'bob'", sql)
                        self.assertIn("'robert'", sql)


class TestCmdRegister(unittest.TestCase):
    """Test agent registration."""

    def test_register_basic(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql") as mock_sql:
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_register("alice")
                    output = mock_out.getvalue()
                    self.assertIn("Registered: alice", output)
                    # INSERT + DELETE groups + DELETE aliases = 3 calls.
                    self.assertEqual(mock_sql.call_count, 3)

    def test_register_with_groups(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql") as mock_sql:
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_register("alice", groups=["backend", "infra"])
                    output = mock_out.getvalue()
                    self.assertIn("groups: backend, infra", output)
                    # INSERT + DELETE groups + 2 group INSERTs + DELETE aliases = 5.
                    self.assertEqual(mock_sql.call_count, 5)

    def test_register_with_aliases(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql") as mock_sql:
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_register("alice", aliases=["al", "a1"])
                    output = mock_out.getvalue()
                    self.assertIn("aliases: al, a1", output)

    def test_register_with_cwd_and_transport(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql") as mock_sql:
                with patch("sys.stdout", new_callable=StringIO):
                    relay.cmd_register("alice", cwd_pattern="my-proj", transport="remote")
                    insert_sql = mock_sql.call_args_list[0][0][0]
                    self.assertIn("remote", insert_sql)
                    self.assertIn("my-proj", insert_sql)


class TestCmdUnregister(unittest.TestCase):
    """Test agent removal."""

    def test_unregister(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql") as mock_sql:
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_unregister("alice")
                    self.assertIn("Unregistered: alice", mock_out.getvalue())
                    sql = mock_sql.call_args[0][0]
                    self.assertIn("DELETE FROM relay_agents", sql)
                    self.assertIn("alice", sql)


class TestCmdList(unittest.TestCase):
    """Test agent listing."""

    def test_list_agents(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql", return_value=[
                "alice\tlocal\tmy-proj\tbackend\tal"
            ]):
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_list()
                    output = mock_out.getvalue()
                    self.assertIn("alice", output)
                    self.assertIn("local", output)
                    self.assertIn("backend", output)

    def test_list_empty(self):
        with patch("relay_msg.ensure_schema"):
            with patch("relay_msg.run_sql", return_value=[]):
                with patch("sys.stdout", new_callable=StringIO) as mock_out:
                    relay.cmd_list()
                    self.assertIn("No agents registered", mock_out.getvalue())


class TestLoadEnvFile(unittest.TestCase):
    """Test .relay-env file loading."""

    def test_loads_key_value_pairs(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("MY_TEST_KEY=my_test_value\n")
            f.write("# comment line\n")
            f.write("\n")
            f.write("ANOTHER_KEY='quoted_value'\n")
            path = f.name
        try:
            env = os.environ.copy()
            env.pop("MY_TEST_KEY", None)
            env.pop("ANOTHER_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                # Manually simulate _load_env_file with our test file.
                with open(path) as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip().strip("'\"")
                            if key and key not in os.environ:
                                os.environ[key] = value
                self.assertEqual(os.environ.get("MY_TEST_KEY"), "my_test_value")
                self.assertEqual(os.environ.get("ANOTHER_KEY"), "quoted_value")
        finally:
            os.unlink(path)

    def test_env_vars_take_precedence(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("MY_EXISTING_KEY=from_file\n")
            path = f.name
        try:
            with patch.dict(os.environ, {"MY_EXISTING_KEY": "from_env"}):
                with open(path) as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip().strip("'\"")
                            if key and key not in os.environ:
                                os.environ[key] = value
                # Env var should win.
                self.assertEqual(os.environ["MY_EXISTING_KEY"], "from_env")
        finally:
            os.unlink(path)


class TestMain(unittest.TestCase):
    """Test CLI argument parsing."""

    def test_no_args_prints_help(self):
        with patch("sys.argv", ["relay-msg"]):
            with self.assertRaises(SystemExit) as ctx:
                relay.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_unknown_command_exits(self):
        with patch("sys.argv", ["relay-msg", "bogus"]):
            with self.assertRaises(SystemExit) as ctx:
                with patch("sys.stderr", new_callable=StringIO):
                    relay.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_send_missing_args_exits(self):
        with patch("sys.argv", ["relay-msg", "send", "alice"]):
            with self.assertRaises(SystemExit) as ctx:
                with patch("sys.stderr", new_callable=StringIO):
                    relay.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_register_missing_name_exits(self):
        with patch("sys.argv", ["relay-msg", "register"]):
            with self.assertRaises(SystemExit) as ctx:
                with patch("sys.stderr", new_callable=StringIO):
                    relay.main()
            self.assertEqual(ctx.exception.code, 1)

    def test_register_parses_all_flags(self):
        with patch("sys.argv", [
            "relay-msg", "register", "alice",
            "--group", "backend",
            "--group", "infra",
            "--cwd", "my-proj",
            "--transport", "remote",
            "--alias", "al",
        ]):
            with patch("relay_msg.cmd_register") as mock_reg:
                relay.main()
                mock_reg.assert_called_once_with(
                    "alice",
                    groups=["backend", "infra"],
                    cwd_pattern="my-proj",
                    transport="remote",
                    aliases=["al"],
                )


if __name__ == "__main__":
    unittest.main()
