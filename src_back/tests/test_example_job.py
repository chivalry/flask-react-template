import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from src_back.jobs import example
from src_back.models import User


def test_main_counts_the_active_accounts(
    app: Flask,
    user: User,
    admin_user: User,
    inactive_user: User,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert example.main(app) == 0
    assert capsys.readouterr().out == 'Example job counted active accounts: 2.\n'


def test_main_builds_the_app_when_none_is_given(
    app: Flask,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # python -m src_back.jobs.example passes no app; the test app stands in for the one
    # create_app() would build from the environment.
    monkeypatch.setattr(example, 'create_app', lambda: app)
    assert example.main() == 0
    assert capsys.readouterr().out == 'Example job counted active accounts: 1.\n'


def test_main_commits_inside_its_own_application_context(
    app: Flask, db: SQLAlchemy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The example only reads, so its commit changes nothing to observe, but a copy that
    # writes depends on it. A commit after the with block would commit the fixture's
    # session here and raise under python -m, so the committing session must be main's.
    fixture_session = db.session()
    committed: list[object] = []
    monkeypatch.setattr(db.session, 'commit', lambda: committed.append(db.session()))
    example.main(app)
    assert len(committed) == 1
    assert committed[0] is not fixture_session
