from src_back.seed import seed


def test_seed_reports_no_data(capsys):
    seed()
    assert capsys.readouterr().out == "No seed data defined.\n"
