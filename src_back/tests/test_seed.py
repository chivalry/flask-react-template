from src_back.seed import seed


def test_seed_reports_that_no_data_is_defined(app, capsys):
    seed(app)
    assert 'No seed data defined.' in capsys.readouterr().out
