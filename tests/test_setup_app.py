"""The guided setup script (setup_app.py): it fills in missing settings but never changes one
that is already set. The full run (venv, packages, database) was checked on a fresh copy."""

import pytest

import setup_app


def test_missing_value_is_added(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AI_PROVIDER=gemini\n")
    assert setup_app.set_env_value(env, "INSIGHTSQL_SECRET_KEY", "new")
    assert env.read_text() == "AI_PROVIDER=gemini\nINSIGHTSQL_SECRET_KEY=new\n"


def test_empty_value_is_filled_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# key\nINSIGHTSQL_SECRET_KEY=\nGEMINI_MODEL=x\n")
    assert setup_app.set_env_value(env, "INSIGHTSQL_SECRET_KEY", "new")
    assert env.read_text() == "# key\nINSIGHTSQL_SECRET_KEY=new\nGEMINI_MODEL=x\n"


def test_existing_value_is_never_changed(tmp_path):
    env = tmp_path / ".env"
    env.write_text("INSIGHTSQL_SECRET_KEY=keep-me\n")
    assert not setup_app.set_env_value(env, "INSIGHTSQL_SECRET_KEY", "new")
    assert env.read_text() == "INSIGHTSQL_SECRET_KEY=keep-me\n"


def test_comments_that_mention_a_setting_are_not_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# GEMINI_BASE_URL=https://example.com (default)\n")
    assert setup_app.env_value(env, "GEMINI_BASE_URL") == ""
    assert setup_app.env_value(tmp_path / "missing.env", "X") == ""


@pytest.mark.parametrize("given, default, expected", [("", True, True), ("", False, False), ("y", False, True),
                                                      ("yes", False, True), ("n", True, False)])
def test_yes_no_questions(monkeypatch, given, default, expected):
    monkeypatch.setattr("builtins.input", lambda prompt: given)
    assert setup_app.ask_yes_no("?", default, assume_yes=False) is expected


def test_yes_flag_takes_the_default_without_asking(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("asked a question"))
    assert setup_app.ask_yes_no("?", False, assume_yes=True) is False


def test_too_old_python_stops_with_a_clear_message(monkeypatch, capsys):
    monkeypatch.setattr(setup_app.sys, "version_info", (3, 10, 0))
    assert setup_app.main(["--yes"]) == 1
    assert "3.12 or newer is needed" in capsys.readouterr().out


def test_a_port_already_in_use_is_skipped():
    import socket
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert setup_app.free_port(taken, tries=5) != taken
