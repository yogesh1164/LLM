import sys

import pytest

from app import account_operator


def test_new_account_password_requires_terminal_input(monkeypatch):
    class NonInteractive:
        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr(sys, "stdin", NonInteractive())
    with pytest.raises(ValueError, match="interactive terminal"):
        account_operator.password()


def test_password_confirmation_mismatch_is_rejected_without_echo(monkeypatch, capsys):
    class Interactive:
        @staticmethod
        def isatty():
            return True

    supplied = iter(("synthetic-secret-one", "synthetic-secret-two"))
    monkeypatch.setattr(sys, "stdin", Interactive())
    monkeypatch.setattr(account_operator.getpass, "getpass", lambda _prompt: next(supplied))
    with pytest.raises(ValueError, match="do not match"):
        account_operator.password()
    output = capsys.readouterr()
    assert "synthetic-secret" not in output.out + output.err
