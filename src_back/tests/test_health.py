import pytest
from flask.testing import FlaskClient

from src_back.app import create_app


def test_health(client: FlaskClient) -> None:
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'environment': 'production'}


@pytest.mark.parametrize(
    ('environment', 'reported'),
    [('', 'production'), ('production', 'production'), ('staging', 'staging')],
)
def test_health_reports_the_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str, reported: str
) -> None:
    monkeypatch.setenv('APP_ENVIRONMENT', environment)
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert app.test_client().get('/api/health').get_json()['environment'] == reported
