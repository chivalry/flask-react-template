import pytest
from flask import Flask

from src_back.seed import seed


def test_seed_reports_that_no_data_is_defined(
    app: Flask, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(app)
    assert 'No seed data defined.' in capsys.readouterr().out
